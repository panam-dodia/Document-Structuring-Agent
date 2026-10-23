"""Fill the W-9 from a client's data: crm.json, then the client's PDFs.

Pipeline: load sources -> resolve one value per field -> validate against the
schema -> fill the PDF -> write a provenance report and print a summary.
Valid values are filled; missing, malformed or unverified ones are left
blank and reported, and the exit code is 1 so a script can't mistake it for
complete.

Usage:
    python -m w9_filler.fill_w9 [client_dir] [--refresh]
    (--refresh ignores the cached LLM answer and calls the model again)
"""
import json
import sys
from pathlib import Path

from w9_filler.field_map import FOREIGN_PARTNERS, TAX_CLASSIFICATION, TEXT_FIELDS
from w9_filler.pdf_form import fill_pdf
from w9_filler.provenance import resolve, to_report
from w9_filler.schema import W9_SCHEMA, validate
from w9_filler.sources.crm import load_crm
from w9_filler.sources.document import load_document
from w9_filler.sources.patterns import extract_numbers

TEMPLATE = "forms/fw9.pdf"
DEFAULT_CLIENT = "clients/bluebird_bakery"


def output_dir(client_dir):
    return Path("output") / Path(client_dir).name


def prepare(client_dir, refresh=False):
    """Load, resolve and validate a client's data. Returns (accepted, issues).

    Priority: crm.json first; documents only fill fields the CRM lacks.
    """
    client_dir = Path(client_dir)
    candidates = load_crm(client_dir / "crm.json")
    priority = ["crm.json"]

    doc_issues = []
    for pdf in sorted(client_dir.glob("*.pdf")):
        llm_found, rejected, pages = load_document(pdf, output_dir(client_dir), refresh=refresh)
        regex_found, ambiguous = extract_numbers(pages, pdf.name)
        # If regex saw several labelled EINs, don't let the LLM pick one.
        blocked = {i.key for i in ambiguous}
        candidates += regex_found + [fv for fv in llm_found if fv.key not in blocked]
        doc_issues += rejected + ambiguous
        priority.append(pdf.name)

    resolved, _all_candidates = resolve(candidates, priority)
    # A rejected document value only needs review if nothing else filled
    # that field; otherwise it's noise (it stays in the extraction log).
    doc_issues = [i for i in doc_issues if i.key not in resolved]
    accepted, issues = validate(resolved, known_issues=doc_issues)
    return accepted, doc_issues + issues


def build_field_values(data):
    """Translate schema keys {key: value} into {pdf field name: value}."""
    values = {}
    for key, field in TEXT_FIELDS.items():
        if data.get(key):
            values[field] = data[key]

    # Line 6 is one PDF field but three schema fields.
    city_state = ", ".join(p for p in (data.get("city"), data.get("state")) if p)
    line6 = " ".join(p for p in (city_state, data.get("zip")) if p)
    if line6:
        values[TEXT_FIELDS["city_state_zip"]] = line6

    if data.get("ein"):
        first, last = data["ein"].split("-")
        values[TEXT_FIELDS["ein_part1"]] = first
        values[TEXT_FIELDS["ein_part2"]] = last
    if data.get("ssn"):
        a, b, c = data["ssn"].split("-")
        values[TEXT_FIELDS["ssn_part1"]] = a
        values[TEXT_FIELDS["ssn_part2"]] = b
        values[TEXT_FIELDS["ssn_part3"]] = c

    # Set every 3a box explicitly so at most one is on.
    chosen = data.get("tax_classification")
    for key, (field, on_value) in TAX_CLASSIFICATION.items():
        values[field] = on_value if key == chosen else "/Off"

    field, on_value = FOREIGN_PARTNERS
    values[field] = on_value if data.get("foreign_partners") else "/Off"
    return values


def plain_values(accepted):
    return {key: fv.value for key, fv in accepted.items()}


def print_summary(client_dir, accepted, issues, pdf_path, report_path):
    print(f"W-9 for {client_dir}\n")
    print(f"Filled ({len(accepted)}):")
    for spec in W9_SCHEMA:
        fv = accepted.get(spec.key)
        if fv:
            locator = fv.locator if len(fv.locator) <= 60 else fv.locator[:57] + "..."
            conf = f"  (confidence {fv.confidence:.2f})" if fv.confidence is not None else ""
            method = f" [{fv.method}]" if fv.method and fv.method != "lookup" else ""
            print(f"  {spec.key:<20} {str(fv.value):<30} {fv.source}{method} : {locator}{conf}")

    print(f"\nNeeds attention ({len(issues)}):")
    for issue in issues:
        found = f" (found {issue.found!r} in {issue.source})" if issue.found is not None else ""
        print(f"  {issue.kind.upper():<8} {issue.message}{found}")
    if not issues:
        print("  nothing")

    print(f"\nWrote {pdf_path}\nWrote {report_path}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--refresh"]
    client_dir = args[0] if args else DEFAULT_CLIENT
    accepted, issues = prepare(client_dir, refresh="--refresh" in sys.argv)

    out = output_dir(client_dir)
    pdf_path, report_path = out / "w9_filled.pdf", out / "w9_provenance.json"
    fill_pdf(TEMPLATE, build_field_values(plain_values(accepted)), pdf_path)
    report_path.write_text(json.dumps(to_report(accepted, issues), indent=2), encoding="utf-8")

    print_summary(client_dir, accepted, issues, pdf_path, report_path)
    sys.exit(1 if issues else 0)
