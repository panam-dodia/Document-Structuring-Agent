"""Find fixed-format numbers (EIN, SSN) in document text with regex.

Regex reads digits exactly: it never re-types or mistypes them, costs
nothing, and gives the same answer every run. What it can't do on shape
alone is tell an EIN from any other 2-7 digit number (a file reference, an
account number). So a match only counts when a label such as "EIN" or
"Employer Identification Number" sits just before it.

ZIP codes are deliberately not here: a document can hold several addresses
(e.g. a registered agent's), and choosing the W-9 mailing address needs
context, which the LLM handles.
"""
import re

from w9_filler.provenance import FieldValue
from w9_filler.schema import SCHEMA, Issue

# What may sit between the label and the number: "(EIN): ", " on file: ", " is "
GAP = r"[^\d]{0,30}?"

PATTERNS = {
    "ein": (
        r"\b(?:EIN|FEIN|Employer\s+Identification\s+(?:Number|No)"
        r"|Federal\s+(?:Tax|Employer)\s+(?:ID|Identification)(?:\s+(?:Number|No))?"
        r"|Tax\s+ID(?:\s+(?:Number|No))?)\b",
        r"\d{2}-?\d{7}",
    ),
    "ssn": (
        r"\b(?:SSN|Social\s+Security\s+(?:Number|No))\b",
        r"\d{3}-?\d{2}-?\d{4}",
    ),
}

REGEXES = {
    key: re.compile(label + GAP + rf"(?<![\d-])({number})(?![\d-])", re.IGNORECASE)
    for key, (label, number) in PATTERNS.items()
}


def digits(text):
    return re.sub(r"\D", "", text)


def extract_numbers(pages, source):
    """Return (candidates, issues) for labelled EIN/SSN numbers in page texts.

    One distinct number for a field -> a candidate. Several different ones
    -> an "ambiguous" issue and no candidate: we don't guess between them.
    """
    candidates, issues = [], []
    for key, rx in REGEXES.items():
        found = {}  # digits -> (page, matched snippet, number as written)
        for page_no, text in enumerate(pages, start=1):
            for m in rx.finditer(text):
                found.setdefault(digits(m.group(1)), (page_no, m.group(0), m.group(1)))

        if len(found) == 1:
            page_no, snippet, number = next(iter(found.values()))
            candidates.append(FieldValue(
                key, number, source=source, locator=f'page {page_no}: "{snippet}"',
                raw=number, method="regex"))
        elif len(found) > 1:
            numbers = ", ".join(v[2] for v in found.values())
            issues.append(Issue(key, "ambiguous",
                                f"{SCHEMA[key].label}: several labelled numbers found ({numbers}); not filled",
                                found=numbers, source=source))
    return candidates, issues
