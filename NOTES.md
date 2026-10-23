# W-9 Filler: Engineering Notes

A log of decisions, problems, and fixes while building the W-9 filler
(`w9_filler/`).
- Step 1: fill the form with hardcoded values.
- Step 2: fill from a client's structured data (`crm.json`), with a schema,
  validation, and per-field provenance.
- Step 3: fill gaps from a client document with the LLM, with verbatim
  quotes checked against the text.

## Layout

```
forms/fw9.pdf              blank W-9 (Rev. March 2024) from irs.gov
clients/<client>/crm.json  synthetic CRM record per client
w9_filler/
  inspect_fields.py        dump every field -> output/w9_fields.txt
  field_map.py             schema keys -> PDF field names
  pdf_form.py              generic fill/read helpers (pypdf)
  debug_fill.py            fill each field with its own name -> output/w9_debug.pdf
  schema.py                W-9 fields: type, required, format rule; validate()
  provenance.py            FieldValue (value + source + locator); resolve()
  sources/crm.py           crm.json -> FieldValue candidates
  sources/document.py      client PDF -> LLM extraction -> quote-checked candidates
  sources/patterns.py      client PDF text -> labelled EIN/SSN via regex
  make_test_documents.py   builds the synthetic PDFs (kept unless --force)
clients/test_ein_from_document/   test client: CRM without EIN + bank summary PDF
  fill_w9.py               pipeline -> output/<client>/w9_filled.pdf + w9_provenance.json
  verify.py                read the output back and check the stored values
```

The filler is a separate package, so the existing Streamlit app is untouched.

Run order:
```
python -m w9_filler.inspect_fields
python -m w9_filler.debug_fill
python -m w9_filler.fill_w9 clients/bluebird_bakery   # exit 1 = needs attention
python -m w9_filler.verify  clients/bluebird_bakery
```
`fill_w9 ... --refresh` ignores the cached LLM answer and calls the model again.

## Library choice

**pypdf** (chosen). It was already in `requirements.txt` (v6.0.0), it's
pure Python with a BSD license, and it can read and write AcroForm fields,
including checkbox `/AS` states. Its weakness is appearance-stream generation
(problem 4).

Alternatives:
| Library | Pros | Cons |
|---|---|---|
| PyMuPDF (fitz) | Best appearance generation (handles comb, alignment) | AGPL license: a problem for closed-source/commercial use |
| pdfrw | Simple, low-level | Unmaintained; you write everything yourself |
| pdftk (CLI) | Battle-tested, good with XFA hybrids | External binary, not pip-installable |
| reportlab overlay | Total control of layout | Doesn't fill fields at all: just draws text on top. The result isn't a filled form (fails step 5) |
| pdfplumber | Already in the project | Read-only; can't write fields |

We also use **pypdfium2** (Chrome's PDF engine, already installed as a
pdfplumber dependency) to render pages to PNG to check the output visually.

## Problems log

### 1. Tooltips (/TU) were empty for all 23 fields
- **Symptom:** the inspector printed `tooltip:` blank for every field.
- **Investigation:** `/Creator` is "Designer 6.5" (Adobe LiveCycle), and
  the AcroForm has an `/XFA` key. That makes this a **hybrid form**: the
  same form is defined twice, as AcroForm (classic PDF fields) and as XFA
  (an XML form definition embedded in the PDF).
- **Finding:** the descriptions only exist in the XFA template, as
  `<assist><speak>` (screen-reader text) and `<caption>`. The AcroForm
  copy never got `/TU`.
- **Fix:** parse the XFA `template` packet with ElementTree and join it to
  the AcroForm fields by full path.

### 2. XFA names are not unique
- **Symptom:** all seven 3a checkboxes are named `c1_1` in XFA.
- **Fix:** rebuild the indexed path the same way the AcroForm names are
  built (`Boxes3a-b_ReadOrder[0].c1_1[3]`): count same-named siblings,
  and skip unnamed subforms, which add no path segment. All 23 fields
  matched exactly. This is a join on a real key, not on document order.

### 3. Max length missing from `get_fields()`
- **Symptom:** the debug fill wrote "f1_11" into a 3-character SSN box.
- **Cause:** pypdf's `get_fields()` returns a summary dict that omits
  `/MaxLen`.
- **Fix:** read `/MaxLen` from the widget annotation itself, walking up
  `/Parent` because field attributes are inheritable.

### 4. SSN/EIN digits crammed into the first box (viewer-dependent)
- **Symptom:** in a render using only the stored appearance streams, "14"
  sat in the first EIN box instead of one digit per box. Centered fields
  were left-aligned. In a render where the viewer regenerates fields, it
  looked correct.
- **Background:** a field has a *value* (`/V`) and an *appearance stream*
  (`/AP`): the drawing commands a viewer paints. `/NeedAppearances true`
  asks the viewer to rebuild appearances from `/V`. Acrobat and Chrome
  usually do; macOS Preview, some mobile viewers, and print or flatten
  pipelines often draw `/AP` as-is.
- **Cause:** the SSN/EIN parts have the **Comb** flag (`/Ff` bit 25) plus
  `/MaxLen`, meaning "space characters evenly across MaxLen cells." Five
  fields have `/Q 1` (center). pypdf's appearance generator ignores both.
- **Fix:** `pdf_form._fix_text_appearances` rewrites `/AP /N` for comb and
  aligned fields. It uses the real glyph widths from the form's font in
  `/AcroForm /DR` to center each character in its cell (comb) or the line
  in the box (`/Q`). It reuses pypdf's `/Resources` and `/BBox`.
- **A testing mistake along the way:** my first render came out completely
  blank, even for the IRS's own checkbox appearances. pypdfium2 with
  `may_draw_forms=False` doesn't draw widgets at all. The correct way to
  simulate a "stored appearances only" viewer is to enable the form engine
  but set `/NeedAppearances false` in a scratch copy.

### 5. Hybrid XFA vs. Adobe Reader
- **Problem:** with `/XFA` present, Adobe Reader renders the XFA definition
  and its own data (the `datasets` packet), ignoring values written to the
  AcroForm fields. The form looks blank in Acrobat but filled in Chrome or
  Preview. This is the classic "values don't show in some viewers" issue
  with IRS forms.
- **Fix:** delete `/XFA` from `/AcroForm` so every viewer uses the AcroForm.
  The form's static content is ordinary PDF, so nothing visible is lost.
  The alternative is to write matching XML into the XFA `datasets` packet
  as well. That's more work and only matters if you need XFA scripting.
- Removing the key turned out not to be enough on its own; see problem 8.

### 6. Checkboxes
- **How they work:** a checkbox is ticked when its value `/V` and its
  appearance state `/AS` both equal its "on" name. That name is **not**
  always `/Yes`. Here each 3a box has its own: `/1`…`/7` (LLC = `/6`),
  found in the widget's `/AP /N` keys (anything that isn't `/Off`).
  Writing `/Yes` would set a value with no matching appearance, so the box
  would stay visually empty.
- **Not a radio group:** the seven boxes are independent fields, so the PDF
  won't stop two being ticked. `build_field_values` sets every 3a box
  explicitly, with exactly one on.

### 7. Choosing the tax classification
A single-member LLC is a disregarded entity and must tick its *owner's*
classification, not "LLC". To show the LLC box plus code, Bluebird Bakery is
modelled as a multi-member LLC taxed as a partnership: LLC box + "P".

### 8. Form blank in Microsoft Edge even though `verify.py` passed
- **Symptom:** in Edge, which uses Adobe's PDF engine, both `w9_filled.pdf`
  and `w9_debug.pdf` showed a blank form, and Edge didn't even draw its
  blue form-field highlight. Edge wasn't treating the file as a fillable
  form. Chrome's engine (pdfium) showed the values fine, and `verify.py`
  passed because the values really were stored in the file.
- **Suspects found in the file:**
  1. `/Perms /UR3`: an Adobe "usage rights" signature over the original
     bytes (IRS forms are Reader-extended), with `SigFlags 2`
     (append-only). Our edit invalidates it.
  2. `%PDF-1.3` header: pypdf's default, but the source is PDF 1.7.
  3. Document-level JavaScript: checked, and it's only an Adobe version
     check, so not the cause.
  4. Leftover XFA: deleting `/XFA` unlinks the 8 XFA packets, but pypdf
     still wrote them into the file as unreferenced objects (~49 KB).
- **Experiment:** two copies, each changing one thing, opened in Edge:
  - A: removed `/Perms` only, still 1.3. Result: filled.
  - B: header changed to 1.7 only, `/Perms` kept. Result: filled, with
    "Some signatures are invalid".
  
  Neither single change can be the fix, since each one was absent from
  one working file. What A and B shared was a second pass through pypdf,
  which dropped the unreferenced objects. Re-opening the original confirmed
  it was still blank, so it wasn't a stale view.
- **Conclusion:** the leftover XFA objects. The object index was valid
  (checked strictly), so exactly why Adobe's engine reacts to unreferenced
  data is unknown; the experiment just shows that removing it fixes it.
- **Fix in `fill_pdf`:**
  - Write to memory, then `PdfWriter(clone_from=...)` again. Cloning copies
    only objects reachable from the root. `compress_identical_objects
    (remove_orphans=True)` was tried first, but it missed the unlinked
    `/Perms` signature dict.
  - Remove `/Perms` and reset `/SigFlags`, so there's no "invalid
    signature" banner (seen in test B).
  - Set the header to `%PDF-1.7`.
- **Lesson:** `verify.py` checked the data but not whether a real viewer
  would display it. It now also fails on `/Perms` and on any unreferenced
  objects. Still, test in the viewers your users have (Acrobat/Edge,
  Chrome, Preview), because a data check can't prove what a viewer shows.

## Verification (`verify.py`)
Reads `output/<client>/w9_filled.pdf` back with a fresh reader and checks:
1. every expected field's `/V` matches, and every other field is empty
2. each checkbox's `/AS` agrees with its `/V`
3. `/XFA` is gone, `/NeedAppearances` is set, `/Perms` is gone, and the
   file has no unreferenced objects (problem 8)
4. No filled value (6+ characters) appears in the page's content stream
   (pdfplumber text).
   This proves the value lives in a form field, not as text stamped on
   the page (the reportlab-overlay approach would fail this).

Run against the blank template, it reports problems, so the checks
actually catch failures.

---

# Step 2: Fill from structured data

## Pipeline

```
sources (crm.json; documents later)
   -> [FieldValue candidates]        each value carries source + locator
   -> resolve()                      one value per field, by source priority
   -> validate()                     normalize, check format, required, cross-field
   -> accepted values  +  issues
   -> build_field_values()           schema keys -> PDF field names
   -> fill_pdf()                     the Step 1 engine, unchanged
   -> w9_filled.pdf + w9_provenance.json + summary
```

Each stage knows one thing. Sources know where data lives, the schema
knows what valid W-9 data looks like, `field_map` knows where it goes on
the PDF, and `pdf_form` knows how to write PDFs.

## Design decisions

**The CRM has its own vocabulary.** `crm.json` nests data
(`company.address.postal_code`) and says `"entity_type": "LLC"`. The
translation lives in `sources/crm.py` (`CRM_PATHS`, `ENTITY_TYPES`), so
neither the schema nor the PDF code knows CRM field names. Swapping CRMs
means writing one new source file.

**The schema describes data, not the form.** The PDF has one "City, state,
and ZIP" line, but the schema has `city`, `state` and `zip` as separate
fields, so the ZIP rule can be checked on its own. `build_field_values`
joins them into one line at the last moment.

**Field specs are data, not code.** Each `FieldSpec` holds a type,
`required`, `required_if=("tax_classification", "llc")`, choices, and an
optional pattern. Conditional requirements are tuples rather than lambdas,
so they can be printed in reports ("required because tax_classification is
'llc'") and, later, serialized.

**Types own normalization plus a default rule.** `ein` turns `000000000`,
`00 0000000` or `00-0000000` into `00-0000000`, then checks
`\d{2}-\d{7}`. Normalization lives in the schema, not the source, so values
from every source (CRM, LLM output, OCR) get the same clean-up. The CRM
stores the EIN without a dash on purpose, to exercise this. ZIP accepts
ZIP+4 (`12345-6789`), since the W-9 allows it.

**Real rules from the W-9 instructions:** exempt payee codes are 1 to 13,
FATCA codes are A to M, the LLC code is C, S or P, and there must be
exactly one of EIN or SSN.

**Missing vs. format vs. rule issues.** Each problem is an `Issue` with a
kind, so a UI can treat them differently later ("ask the client" vs. "fix
the typo").

**Fill what's valid, flag the rest, and exit 1.** The alternative was to
refuse to produce a PDF until the data is complete. A partly filled draft
with a clear to-do list is more useful to a reviewer, and the non-zero exit
code stops automation from treating it as done. Invalid values are never
written, so blanks are always explained in the summary and never silent.

**`verify.py` vs. validation:** two different questions. Validation asks
whether the data is complete and well-formed. `verify` asks whether the
PDF contains exactly what we intended to write. Bluebird's form is
"verified" (the PDF is correct) but "needs attention" (the data is
incomplete).

## Provenance, and why it's built for multiple sources

`FieldValue(key, value, source, locator, raw)`:
- `source`: which input, such as `crm.json` (later
  `articles_of_organization.pdf`).
- `locator`: where inside it, such as the JSON path `tax.ein` (later
  "page 2" or a text snippet).
- `raw`: the value before normalization, such as `"LLC"` or `"000000000"`,
  so an auditor can see what the source actually said.

Sources return **lists of candidates** rather than a finished dict, and
`resolve()` keeps all of them while choosing one per field by source
priority. With one source this looks like overkill. With two, it's what
allows "the CRM says X, the Articles say Y" to be detected and shown rather
than silently overwritten. Tested in memory: with two disagreeing
candidates, changing the priority changes the winner, and both candidates
are kept.

Adding documents later means writing a `sources/documents.py` that returns
`FieldValue`s and adding it to the list in `prepare()`. Nothing else
changes. Likely additions then, deliberately not built yet:
- a `confidence` score on `FieldValue` for LLM-extracted values,
- conflict reporting when candidates disagree,
- priority per field (for example, trust a document over the CRM for the
  EIN but not for the address).

`output/<client>/w9_provenance.json` records every filled value with its
source, locator and raw value, plus every issue: an audit trail per form.

## Step 2 problems log

### 9. A broken rule still let values reach the PDF
- **How it was found:** tested the validator against deliberately broken
  records (bad EIN, ZIP and state, unknown entity type, both TINs, missing
  address, a whitespace-only name) before trusting it.
- **Bug A:** with both an EIN and an SSN, the rule reported the problem but
  both values stayed "accepted", so both would have been printed.
- **Bug B:** with an invalid or non-LLC classification, the LLC code "P"
  was still accepted and would have printed next to an unticked LLC box.
- **Fix, one principle:** a value that breaks a rule never reaches the
  form. Conditional fields whose condition isn't met are removed and
  reported ("only applies when tax_classification is 'llc'; not filled").
  With both TINs, neither is filled, because we can't know which is right.
- **Lesson:** "reported" and "excluded" are separate steps. Check that the
  data passed to the filler matches the report.

### 10. The LLC classification gap is a real-world one
`crm.json` deliberately omits `tax.llc_tax_classification`. CRMs commonly
record "LLC" without how it's taxed, and the W-9 can't be completed without
it. A single-member LLC shouldn't even tick the LLC box (it ticks its
owner's), so an `"entity_type": "LLC"` alone is never enough. The schema
catches it through `required_if`. The form is filled with the LLC box
ticked and the code blank, and the summary says why.

---

# Step 3: Fill gaps from a document with the LLM

## Flow

```
articles_of_organization.pdf
  -> existing DocumentProcessor (pdfplumber + AdvancedTextCleaner), once per page
  -> "=== Page N ===" text  ->  gpt-4-turbo, strict structured output
  -> per field: value, quote, page, confidence
  -> check each: quote found? on that page? value inside quote? confidence >= 0.8?
       pass -> FieldValue(source=PDF name, locator='page N: "quote"', confidence)
       fail -> Issue(kind="unverified") with the reasons
  -> resolve(priority = crm.json, then PDFs)   documents only fill CRM gaps
  -> validate -> fill -> verify
```

Result for Bluebird: the CRM's missing LLC tax classification is filled with
"P" from page 2 ("...elected to be taxed as a partnership"). Nothing needs
attention, and the exit code is 0.

## The synthetic document
`make_test_documents.py` uses reportlab, so the PDF has a real text layer.
It's two pages, with the tax election on page 2, so page numbers are
actually tested. It contains traps on purpose:
- A registered-office address that differs from the CRM's. A registered
  agent's address isn't the W-9 mailing address. The model correctly
  returned null.
- The formation state "Example State" isn't the address state.
- An apostrophe ("Company's") that the cleaner removes.
- Sentences that wrap across lines.

## How the LLM is prompted for structured output

**The output schema is generated from the W-9 schema**
(`build_output_model`). There's one nullable object per schema field, each
with `value`, `quote`, `page` and `confidence`. Choice fields become enums,
so the model can't invent a tax classification. Fixed slots per field (not
a free list) mean every field gets considered and none can appear twice.
Field descriptions come from the schema labels and rules, plus a few
`FIELD_HINTS` with W-9 domain rules.

**Strict mode:** `with_structured_output(..., method="function_calling",
strict=True)`. OpenAI then restricts generation to the JSON schema, so the
reply always parses and enums are respected. gpt-4-turbo (the model
`doc_processor.py` uses) supports strict mode through function calling. The
newer `json_schema` response format needs gpt-4o or later. Temperature is 0.

**Prompt rules** (`SYSTEM_PROMPT`):
- Use only what the document says, with no default tax rules.
- Quote the *shortest* passage that proves the value, character for
  character, with no ellipses and no joining of separate passages.
- The page number comes from the `=== Page N ===` marker, and the quote
  must not include the marker.
- Confidence 1.0 means the quote states the value directly.
- If the field isn't there, return null; "a missing value is better than a
  guess".
- A registered office address is not a W-9 address.

## Quote verification, and what happens when quotes don't match exactly
`find_quote` works in two stages:
1. **Exact substring** of a page's text.
2. **Canonical match:** both quote and page go through `canonical()`, which
   undoes only what extraction and cleanup change. That means Unicode forms,
   curly quotes and dashes, the characters `AdvancedTextCleaner` replaces
   with spaces, whitespace runs (line breaks, double spaces), and case.
   Every word must still match exactly.

**Deliberately not fuzzy.** A similarity threshold would accept "the LLC
elected partnership taxation" as "close enough" to the real sentence,
which defeats the point of demanding a quote. Paraphrases are rejected.

Other checks:
- The quote must be at least 10 characters, because "LLC" or "P" match
  almost anywhere.
- For literal fields (names, EIN, ZIP…) the value must appear inside its
  own quote, which catches a real quote paired with an invented value.
- Confidence must be at least 0.8.
- A wrong page alone is *corrected* rather than rejected, since we found the
  real page ourselves.

Offline tests (no API) covered exact, tidied whitespace, a line break in the
quote, a restored apostrophe, a paraphrase, a wrong page, a value not in its
quote, a too-short quote and low confidence. All behaved as intended. In the
live run, all three quotes happened to match exactly, so the canonical path
has only been exercised by those tests so far.

## Provenance with two sources
Document values carry `source="articles_of_organization.pdf"`,
`locator='page 2: "the members have agreed that the Company has elected to
be taxed as a partnership"'`, and `confidence`, which is new on
`FieldValue` and `None` for CRM values. Priority is explicit: `["crm.json",
*pdf names]`. The document also returned the legal name, which the CRM
already had, so it wasn't used. Conflict reporting is still deliberately
not built.

Rejected document values become issues only if no other source filled the
field. Otherwise they'd be noise. Everything, including page texts, the raw
model answer, and every check with its reasons, is saved in
`output/<client>/<pdf>.extraction.json`.

## Step 3 problems log

### 11. Existing ingestion loses page numbers
`extract_text_from_pdf` joins all pages into one string, so a quote can't
be tied to a page. Instead of changing it, `read_pages` splits the PDF into
one-page PDFs and runs the **unchanged** `DocumentProcessor` on each, so the
same ingestion and cleanup still apply.

### 12. Cleanup alters the text the quotes must match
Running the existing pipeline on the Articles showed:
- `(the "Company")` becomes `the  Company  .` with double spaces. The
  cleaner collapses whitespace *before* replacing `( " )` with spaces.
- "Company's" becomes "Company s".

A model that tidies spacing or restores the apostrophe in its quote would
fail an exact match. Fix: `canonical()` applies the same character set
the cleaner keeps (`[^\w\s.,!?;:-]` becomes a space) to both sides, then
collapses whitespace.

**Open risk, not fixed:** the model only sees *cleaned* text, so a value
containing a removed character is extracted without it. "Smith & Sons LLC"
would become "Smith Sons LLC", and the quote check still passes, because it
compares cleaned with cleaned. Bluebird is unaffected. A fix would extract
from uncleaned per-page text, or a less destructive cleanup, but that means
changing the shared ingestion, which is your call.

### 13. Verified quote, wrong interpretation
- **Symptom:** the first live run returned `tax_classification =
  "partnership"` with confidence 1.0 and an exact, verified quote ("...elected
  to be taxed as a partnership..."). For the W-9 that's wrong: an LLC taxed
  as a partnership ticks **LLC** and writes "P".
- **Why the form was still right:** the CRM's "LLC" outranked it. With no
  entity type in the CRM, the form would have ticked Partnership, and the
  schema would have dropped the "P".
- **Fix:** a `FIELD_HINTS` rule ("an LLC is always 'llc', even if it
  elected partnership or corporate taxation; that goes in
  llc_tax_class_code"), plus a prompt-version bump to invalidate the cache.
  The rerun returned `llc`, quoting Article II.
- **Regression check:** a scratch client with `entity_type` removed from the
  CRM. The document alone now gives LLC + P.
- **Lesson:** quote checking catches *invented* text, not *misread* text.
  Confidence didn't help either: the model was 100% sure and wrong. Domain
  rules belong in the prompt *and* in schema cross-checks (the
  `required_if` rule on the LLC code is what would have flagged it), and
  every source should be tested on its own, not only behind a
  higher-priority one.

### 14. verify.py would have called the LLM again
`verify.py` rebuilt "expected" values by re-running the pipeline. With an
LLM in it, that costs money and could return a *different* answer than the
fill run, making verify compare against the wrong thing. Two fixes:
- `verify` now reads the expected values from `w9_provenance.json`, i.e.
  what the fill run actually wrote.
- The model's answer is cached in the extraction log, keyed by (PDF SHA-256,
  model, `PROMPT_VERSION`). Reruns are free and repeatable; changing the
  document, the model or the prompt invalidates the cache, and `--refresh`
  forces a new call. Checked by rerunning with a deliberately invalid API key:
  it still succeeds, so no call is made.

### 15. Noise from the existing code
`doc_processor.py` uses the deprecated `langchain_community` ChatOpenAI
(which logs a deprecation warning) and prints a line per extracted file. Both
are silenced around the call. The extractor uses `langchain_openai`
ChatOpenAI with temperature 0, not the processor's `.llm` (temperature 0.2,
no strict structured output).

---

# Step 3b: Hybrid extraction (regex + LLM)

## Why
An LLM never copies text; it re-types it, predicting chunks of up to 3
digits (`12-3456789` is the tokens `12 - 345 678 9`). Digits have no meaning
to keep it on track, and runs like `000000000` are easy to over- or
under-count. A regex reads the digits exactly, for free, the same way every
time. What regex can't do is tell *which* 9-digit number is the EIN. That
needs a label or context.

## Design: each tool does what it's good at
| Field | Method | Why |
|---|---|---|
| EIN, SSN | regex, **only with a label just before the number** ("EIN", "Employer Identification Number", "Tax ID", "SSN"…), up to 30 characters away | fixed format; the label resolves which number |
| ZIP, state, city, address | LLM | which address (mailing vs. registered agent) needs context |
| Name, tax classification, LLC code | LLM | needs reading comprehension |

- **Regex outranks the LLM within a document.** `FieldValue.method` is
  `lookup` / `regex` / `llm`, and `resolve()` ranks by (source priority,
  method). Provenance and the summary show the method (`[regex]`).
- **The LLM picks, the code verifies:** an EIN, SSN or ZIP from the LLM
  must equal, digit for digit, a whole number inside its own quote.
  Comparing digits only makes `12-3456789` and `123456789` the same
  number, which fixed a false rejection. Comparing whole numbers stops
  digits being stitched together from two adjacent numbers.
- **Ambiguity is never guessed:** two *different* labelled EINs in one
  document give an "ambiguous" issue, and the LLM's EIN for that document
  is blocked too.
- Regex runs on the same cleaned page texts the LLM saw (returned by
  `load_document`), so locators match.

Offline tests: a labelled EIN, an EIN without a dash, an unlabelled
EIN-shaped reference (ignored), a distractor plus a labelled EIN, the same
EIN in two formats (one candidate), two different EINs (ambiguous), "Being
12-3456789" (no false label), a label too far away (ignored), part of a
longer number (ignored), an SSN; on the LLM side, a model-added dash
(accepted), a one-digit typo (rejected), and digits stitched across numbers
(rejected).

**Test client** `clients/test_ein_from_document/`: its CRM has no EIN, and
`bank_account_summary.pdf` has the labelled EIN among look-alikes (an
EIN-shaped "application reference", a 9-digit account number, a phone
number). Result: EIN `00-0000000` filled from the PDF by `[regex]`; the
LLM agreed but ranks lower.

`make_test_documents.py` now keeps existing PDFs unless `--force` and
builds them with `rl_config.invariant = 1`. A rebuilt PDF has a new hash,
which would invalidate the LLM cache and trigger a paid call.

## Step 3b problems log

### 16. A dash made a correct EIN fail
The "value inside its quote" check compared text, so `12-3456789` vs.
`123456789` failed. It failed safe (the value went to review), but it was
still a false alarm. Number fields now compare digits (see above).

### 17. The LLM put the client's bank account number on line 7
- **Symptom:** on the bank summary, the LLM filled line 7 ("List account
  number(s)") with `000123456`, the client's bank account. The quote was
  real and the confidence 1.0.
- **Why it's wrong:** line 7 is for the *requester's* reference numbers,
  and a W-9 is handed to the paying business, so this would leak a bank
  account number. It's the same pattern as problem 13: a correct quote,
  misread.
- **Fix:** a new `FieldSpec.from_documents=False` for `account_numbers` and
  `requester_name_address`. Both describe the requester's side, so they're
  left out of the LLM's output schema entirely and ignored even if present.
- **Lesson:** decide per field which sources may supply it at all. Not
  every field is extractable just because text that looks like it exists.

### 18. "Shortest passage" made quotes prove nothing
- **Symptom:** asked for the *shortest* proving passage, the model quoted
  only the value: `"00-0000000"`, `"Anytown"`, `"ST"`, `"00000"`. A bare
  number proves the digits exist, not that they're the EIN. (The short
  ones were rejected as "too short"; `00-0000000` is exactly 10 characters
  and slipped through.)
- **Fix:** a prompt rule saying the quote must show what the value *is*,
  including its label ("EIN on file: 12-3456789", not "12-3456789").
  `PROMPT_VERSION` 3. After: `"Federal Employer Identification Number  EIN
  on file: 00-0000000"` and `"Mailing address on file: 123 Example Street,
  Suite 0, Anytown, ST 00000"`, and city, state and ZIP are now accepted.
- **Still weak:** on the bank summary, `tax_classification = llc` is backed
  only by `"Bluebird Bakery LLC"`, i.e. the name's suffix. It's plausible,
  but it's inference from a name, not a statement. The CRM outranks it
  here.

### Not built yet
- Flagging when regex and LLM *disagree* on a number. Today regex wins
  silently. That's conflict reporting, which is the planned next step.
- API calls so far in Step 3/3b: 5 gpt-4-turbo calls (Articles ×3 for
  prompt v1–v3, bank summary ×2 for v2–v3). Reruns are cached.

## Interview talking points
- AcroForm vs. XFA, and why hybrid forms behave differently across viewers.
- Value (`/V`) vs. appearance (`/AP`, `/AS`): data vs. pixels.
- Checkbox export values aren't always `/Yes`: read them from the form.
- Field flags (Comb, Multiline) and `/Q`, and why generic fillers miss them.
- Inheritable attributes: always walk `/Parent`.
- Verify by reading back the data, not just by looking at a screenshot,
  *and* open the file in real viewers: data checks passed while Edge showed
  a blank form (problem 8).
- Debug by changing one variable at a time (the A/B test in problem 8).
- Reader-extended PDFs (`/Perms /UR3`) and why editing breaks them.
- Separation of concerns: source adapters, schema, field map, PDF writer.
- Provenance as candidates + resolution, not overwrite: it makes multiple
  sources auditable.
- Validation vs. verification: is the data right, and is the file right?
- Fail loudly but usefully: a partial draft plus a to-do list plus exit 1.
- LLM extraction you can audit: strict structured output generated from the
  schema, verbatim quotes, deterministic checks, and no fuzzy acceptance.
- Grounding catches invention but not misinterpretation (problem 13), and
  self-reported confidence is not calibration.
- Cache LLM answers by input hash + model + prompt version, for repeatable
  runs.
- Hybrid extraction: regex for fixed formats (exact, free, deterministic),
  LLM for meaning, and code checking the LLM's digits against the text.
- Field-level source policy: some fields must never come from documents.
- Prompt wording has side effects: "shortest quote" produced quotes that
  proved nothing.
