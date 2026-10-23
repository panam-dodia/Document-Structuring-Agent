"""Extract W-9 values from a client document with the LLM, with quote checks.

(Fixed-format numbers are also found by regex in patterns.py; for EIN/SSN a
regex match outranks the LLM. This module checks the LLM's numbers digit
for digit against its quote.)

1. Ingest: the existing DocumentProcessor (pdfplumber + AdvancedTextCleaner),
   run once per page so page numbers survive. (It joins all pages into one
   string, so a whole-document call can't tell us where a quote came from.)
2. Extract: the LLM fills a structured-output schema generated from
   schema.W9_SCHEMA. Each value comes with a verbatim quote, a page and a
   confidence score.
3. Check: every quote must be found in the text the model was given. Values
   whose quote can't be found, or that the quote doesn't contain, or with low
   confidence are rejected as issues and never become candidates.

The model's answer is cached per (document hash, model, prompt version), so
re-running the pipeline is free and gives the same answer.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import tempfile
import tomllib
import unicodedata
import warnings
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field, create_model
from pypdf import PdfReader, PdfWriter

from w9_filler.provenance import FieldValue
from w9_filler.schema import W9_SCHEMA, Issue

MODEL = "gpt-4-turbo"      # same model as doc_processor.py
PROMPT_VERSION = 3         # bump when the prompt or schema changes (invalidates cache)
MIN_CONFIDENCE = 0.8
MIN_QUOTE_CHARS = 10       # shorter quotes ("LLC", "P") match almost anywhere
LITERAL_TYPES = {"text", "state"}      # value must appear in its quote
NUMBER_TYPES = {"ein", "ssn", "zip"}   # value must equal a number in its quote, digit for digit

SYSTEM_PROMPT = """You extract data for IRS Form W-9 from one business document.

Rules:
- Use only what the document states. Do not use outside knowledge or default
  tax rules: for example, never assume an LLC's tax classification unless the
  document states an election.
- For every value, set `quote` to a short passage that proves it, copied
  character for character from the document text: same spelling, spacing,
  punctuation and capitalization. No ellipses, no paraphrasing, and no text
  joined from two different places.
- The quote must show what the value IS, not just the value: include the
  label or words that identify it. "EIN on file: 12-3456789", not
  "12-3456789"; "Mailing address on file: 1 Main St, Town, ST 12345", not
  "Town".
- `page` is the number in the "=== Page N ===" marker above the quote. Never
  include the marker in a quote.
- `confidence` (0.0 to 1.0): 1.0 when the quote states the value directly;
  lower when you had to interpret it.
- If the document does not state a field, return null for it. A missing value
  is better than a guess.
- The W-9 address is the company's mailing or business address. A registered
  office or registered agent address is NOT a W-9 address; return null for
  address, city, state and zip unless a mailing/business address is given."""

# Extra guidance per field, on top of the schema label and rule.
FIELD_HINTS = {
    "legal_name": "The entity's exact legal name, including any suffix such as LLC.",
    "business_name": "A trade name / DBA only if the document gives one different from the legal name.",
    # Without the second sentence, gpt-4-turbo answered 'partnership' for an
    # LLC taxed as a partnership: a verified quote, confidence 1.0, and wrong
    # for the W-9 (NOTES.md, problem 12).
    "tax_classification": "The legal entity type, not its tax election. A limited liability "
                          "company is always 'llc', even if it elected to be taxed as a "
                          "partnership or corporation; that election goes in llc_tax_class_code.",
    "llc_tax_class_code": "Only for an LLC, and only if the document states its tax election: "
                          "C = taxed as a C corporation, S = S corporation, P = partnership.",
}


# ---------- 1. ingestion -------------------------------------------------

def read_pages(pdf_path, processor):
    """Cleaned text per page via the existing DocumentProcessor, unchanged."""
    reader = PdfReader(pdf_path)
    pages = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, page in enumerate(reader.pages, start=1):
            single = Path(tmp) / f"page_{i}.pdf"
            writer = PdfWriter()
            writer.add_page(page)
            writer.write(single)
            with contextlib.redirect_stdout(io.StringIO()):  # it prints per file
                pages.append(processor.extract_text_from_file(str(single), "pdf"))
    return pages


# ---------- 2. structured extraction -------------------------------------

def _value_type(spec):
    return Literal[spec.choices] if spec.choices else str


def build_output_model():
    """Pydantic model for the LLM's answer, generated from the W-9 schema.

    One nullable object per schema field (rather than a free list) forces the
    model to consider every field and makes duplicates impossible. Choice
    fields become enums, so the model can't invent a classification.
    """
    fields = {}
    for spec in W9_SCHEMA:
        if not spec.from_documents:
            continue
        item = create_model(
            f"Extracted_{spec.key}",
            value=(_value_type(spec), Field(description=spec.label)),
            quote=(str, Field(description="Verbatim passage from the document proving the value")),
            page=(int, Field(description="Page number from the === Page N === marker")),
            confidence=(float, Field(description="0.0 to 1.0")),
        )
        desc = " ".join(filter(None, [spec.label, spec.rule, FIELD_HINTS.get(spec.key)]))
        fields[spec.key] = (Optional[item], Field(description=desc))
    return create_model("W9Extraction", **fields)


def format_pages(pages):
    return "\n\n".join(f"=== Page {i} ===\n{text}" for i, text in enumerate(pages, start=1))


def call_llm(pages, filename, api_key, model=MODEL):
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(model=model, temperature=0, api_key=api_key)
    # strict=True: OpenAI constrains decoding to the JSON schema, so the reply
    # always parses and enums are respected. gpt-4-turbo supports strict mode
    # through function calling (not the newer json_schema response format).
    structured = llm.with_structured_output(build_output_model(), method="function_calling", strict=True)
    answer = structured.invoke([
        ("system", SYSTEM_PROMPT),
        ("human", f"Document: {filename}\n\n{format_pages(pages)}"),
    ])
    return answer.model_dump()


# ---------- 3. quote verification ----------------------------------------

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         "–": "-", "—": "-", " ": " "})


def canonical(text):
    """Make text comparable across PDF/cleanup/model quirks, nothing more.

    Undoes only what extraction and cleanup change: Unicode forms, curly
    quotes and dashes, the characters AdvancedTextCleaner replaces with spaces,
    whitespace runs (line breaks, double spaces) and case. Words must still
    match exactly; this is not fuzzy matching.
    """
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES)
    text = re.sub(r"[^\w\s.,!?;:-]", " ", text)   # same set advanced_cleaner keeps
    return re.sub(r"\s+", " ", text).strip().casefold()


def find_quote(quote, pages):
    """Return (page number, 'exact' | 'normalized') or (None, None)."""
    for i, text in enumerate(pages, start=1):
        if quote and quote in text:
            return i, "exact"
    target = canonical(quote)
    for i, text in enumerate(pages, start=1):
        if target and target in canonical(text):
            return i, "normalized"
    return None, None


def numbers_in(text):
    """Digit strings of each number in text: '12-3456789 and 555' -> {'123456789', '555'}."""
    return {re.sub(r"\D", "", n) for n in re.findall(r"\d[\d-]*\d|\d", text)}


def check_extraction(spec, item, pages, min_confidence=MIN_CONFIDENCE):
    """Return a result dict: status 'accepted' or 'rejected', with reasons."""
    quote, value = item["quote"], str(item["value"])
    page, match = find_quote(quote, pages)
    result = {"key": spec.key, "value": value, "quote": quote, "claimed_page": item["page"],
              "page": page, "match": match, "confidence": item["confidence"], "reasons": []}

    if len(canonical(quote)) < MIN_QUOTE_CHARS:
        result["reasons"].append("quote too short to verify")
    if page is None:
        result["reasons"].append("quote not found in document text")
    elif page != item["page"]:
        result["reasons"].append(f"quote is on page {page}, model said page {item['page']}")
    if spec.type in LITERAL_TYPES and canonical(value) not in canonical(quote):
        result["reasons"].append("value does not appear in its quote")
    if spec.type in NUMBER_TYPES and re.sub(r"\D", "", value) not in numbers_in(quote):
        # The model chooses the number; the code checks its digits against the
        # text. Digits only, so "12-3456789" and "123456789" are the same number,
        # and whole numbers only, so digits can't be stitched across two numbers.
        result["reasons"].append("number does not match any number in its quote")
    if item["confidence"] < min_confidence:
        result["reasons"].append(f"confidence {item['confidence']:.2f} below {min_confidence}")

    # A wrong page alone is corrected (we found the real one), not rejected.
    blocking = [r for r in result["reasons"] if not r.startswith("quote is on page")]
    result["status"] = "rejected" if blocking else "accepted"
    return result


# ---------- putting it together ------------------------------------------

def load_api_key():
    key = os.getenv("OPENAI_API_KEY")
    secrets = Path(".streamlit/secrets.toml")
    if not key and secrets.exists():
        key = tomllib.loads(secrets.read_text(encoding="utf-8")).get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("No OPENAI_API_KEY in the environment or .streamlit/secrets.toml")
    return key


def _cache_key(pdf_path, model):
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    return f"{digest}:{model}:v{PROMPT_VERSION}"


def load_document(pdf_path, log_dir, refresh=False, model=MODEL):
    """Extract candidates from one PDF. Returns (candidates, rejected_issues, pages).

    pages (the cleaned page texts) are returned so other extractors, like
    the regex in patterns.py, read exactly the text the LLM read.

    Writes <log_dir>/<pdf stem>.extraction.json: page texts, the raw model
    answer, and the verification result for every value (an audit trail and
    the cache for the next run).
    """
    pdf_path, log_dir = Path(pdf_path), Path(log_dir)
    log_path = log_dir / f"{pdf_path.stem}.extraction.json"
    cache_key = _cache_key(pdf_path, model)

    cached = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else None
    if cached and cached.get("cache_key") == cache_key and not refresh:
        pages, answer = cached["pages"], cached["model_output"]
    else:
        from doc_processor import DocumentProcessor

        api_key = load_api_key()
        with warnings.catch_warnings():
            # doc_processor uses the deprecated langchain_community ChatOpenAI
            warnings.simplefilter("ignore")
            processor = DocumentProcessor(api_key, advanced_cleaning=True)
        pages = read_pages(pdf_path, processor)
        answer = call_llm(pages, pdf_path.name, api_key, model)

    candidates, issues, results = [], [], []
    for spec in W9_SCHEMA:
        item = answer.get(spec.key)
        if not item or not spec.from_documents:
            continue
        result = check_extraction(spec, item, pages)
        results.append(result)
        if result["status"] == "accepted":
            candidates.append(FieldValue(
                spec.key, item["value"], source=pdf_path.name,
                locator=f'page {result["page"]}: "{item["quote"]}"',
                raw=item["value"], confidence=item["confidence"], method="llm"))
        else:
            issues.append(Issue(spec.key, "unverified",
                                f"{spec.label}: not used ({'; '.join(result['reasons'])})",
                                found=item["value"], source=pdf_path.name))

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps({
        "cache_key": cache_key, "document": pdf_path.name, "model": model,
        "pages": pages, "model_output": answer, "checks": results,
    }, indent=2), encoding="utf-8")
    return candidates, issues, pages
