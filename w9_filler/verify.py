"""Read the filled W-9 back and confirm values are stored in the form fields.

Checks, from a fresh read of the output file:
  1. every expected field's /V equals what we wrote; all other fields are empty
  2. each checkbox's /AS (drawn appearance) agrees with its /V
  3. the XFA layer is gone, /NeedAppearances is set, the broken usage-rights
     signature (/Perms) is removed, and no unreferenced objects remain
     (leftover XFA packets made Edge show the form blank)
  4. the values are NOT in the page's content stream, i.e. they live in the
     form fields rather than being stamped onto the page as plain text

This checks the PDF matches what the pipeline intended to write, as recorded
in w9_provenance.json by the fill run. (It doesn't re-run the pipeline: that
could call the LLM again and compare against a different answer.) Whether
the *data* is complete is a separate question, answered by schema
validation in fill_w9.py.

Usage:
    python -m w9_filler.verify [client_dir]
"""
import json
import sys

import pdfplumber
from pypdf import PdfReader

from w9_filler.fill_w9 import DEFAULT_CLIENT, build_field_values, output_dir
from w9_filler.pdf_form import read_values, unreferenced_objects, widget_states


def verify(pdf_path, expected):
    problems = []
    stored = read_values(pdf_path)

    for name, value in stored.items():
        want = expected.get(name)
        got = str(value) if value is not None else None
        if want in (None, "/Off"):
            if got not in (None, "", "/Off"):
                problems.append(f"{name}: expected empty, found {got!r}")
        elif got != want:
            problems.append(f"{name}: expected {want!r}, found {got!r}")
    for name in expected.keys() - stored.keys():
        problems.append(f"{name}: field not found in output")

    for name, state in widget_states(pdf_path).items():
        if str(state) != str(stored.get(name) or "/Off"):
            problems.append(f"{name}: /AS {state} disagrees with /V {stored.get(name)}")

    root = PdfReader(pdf_path).trailer["/Root"]
    acro = root["/AcroForm"]
    if "/XFA" in acro:
        problems.append("XFA still present: Adobe Reader would show a blank form")
    if not acro.get("/NeedAppearances"):
        problems.append("/NeedAppearances not set")
    if "/Perms" in root:
        problems.append("/Perms usage-rights signature present: viewers will flag it invalid")
    orphans = unreferenced_objects(pdf_path)
    if orphans:
        problems.append(f"{len(orphans)} unreferenced objects (e.g. leftover XFA): Edge shows the form blank")

    with pdfplumber.open(pdf_path) as pdf:
        page_text = pdf.pages[0].extract_text() or ""
    # Long values only: short ones like "P" or "00" occur in the form's own text.
    for value in expected.values():
        if len(value) >= 6 and value in page_text:
            problems.append(f"{value!r} found in page content: it was stamped, not filled")

    return stored, problems


if __name__ == "__main__":
    client_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CLIENT
    out = output_dir(client_dir)
    report = json.loads((out / "w9_provenance.json").read_text(encoding="utf-8"))
    expected = build_field_values({k: f["value"] for k, f in report["fields"].items()})
    pdf_path = out / "w9_filled.pdf"
    stored, problems = verify(pdf_path, expected)
    for name, value in stored.items():
        if value not in (None, "", "/Off"):
            print(f"  {name.split('.')[-1]:<10} = {value}")
    if problems:
        print("\nFAILED:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print(f"\nOK: {len(stored)} fields checked in {pdf_path}")
