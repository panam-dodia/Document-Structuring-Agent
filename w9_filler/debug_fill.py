"""Diagnostic: fill each text field with its own short name and tick every box.

Open output/w9_debug.pdf to see where each field lands on the page.
Fields with a max length can't hold "f1_11", so they get just the field
number, trimmed to fit (f1_11 with max_len 3 -> "11", f1_03 with max_len 1 -> "3").

Usage:
    python -m w9_filler.debug_fill
"""
from w9_filler.inspect_fields import list_fields
from w9_filler.pdf_form import fill_pdf

TEMPLATE = "forms/fw9.pdf"
OUTPUT = "output/w9_debug.pdf"


def debug_values(template_path):
    # list_fields reads /MaxLen from the widget itself; pypdf's get_fields()
    # summary dict leaves /MaxLen out, so it can't be used for this.
    values = {}
    for row in list_fields(template_path):
        name = row["name"]
        short = name.split(".")[-1].replace("[0]", "")  # e.g. f1_01, c1_1[3]
        if row["type"] == "Text":
            max_len = row["max_len"]
            values[name] = short.split("_")[-1][-int(max_len):] if max_len else short
        elif row.get("on_states"):
            values[name] = row["on_states"][0]
    return values


if __name__ == "__main__":
    values = debug_values(TEMPLATE)
    fill_pdf(TEMPLATE, values, OUTPUT)
    for k, v in values.items():
        print(f"{v!s:>8}  {k}")
    print(f"Wrote {OUTPUT}")
