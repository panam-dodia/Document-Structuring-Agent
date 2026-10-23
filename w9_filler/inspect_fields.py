"""List every form field in a PDF: name, type, tooltip, page, position.

The IRS W-9 is a hybrid AcroForm + XFA form (built in Adobe LiveCycle Designer).
Its AcroForm fields have no /TU tooltip; the human-readable descriptions only
exist in the XFA template, so we read both and join them on the field path.

Usage:
    python -m w9_filler.inspect_fields [input.pdf] [output.txt]
"""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

from pypdf import PdfReader

XFA_CONTAINERS = {"subform", "field", "exclGroup"}

FIELD_TYPES = {
    "/Tx": "Text",
    "/Btn": "Button (checkbox/radio)",
    "/Ch": "Choice",
    "/Sig": "Signature",
}


def _inherited(obj, key):
    """Look up a field attribute, walking up /Parent (kids inherit /FT, /TU, etc.)."""
    while obj is not None:
        if key in obj:
            return obj[key]
        obj = obj.get("/Parent")
        obj = obj.get_object() if obj is not None else None
    return None


def _full_name(annot):
    """Build the fully qualified name, e.g. topmostSubform[0].Page1[0].f1_01[0]."""
    parts = []
    obj = annot
    while obj is not None:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        parent = obj.get("/Parent")
        obj = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))


def _local(tag):
    return tag.split("}")[-1]


def _text(el):
    return " ".join("".join(el.itertext()).split())


def xfa_descriptions(reader):
    """Map full field path -> description text from the XFA template.

    XFA names aren't unique (all seven tax-class boxes are "c1_1"), so we
    rebuild the indexed path, e.g. topmostSubform[0].Page1[0].c1_1[3], the
    same way the AcroForm names are built. Unnamed subforms add no segment.
    """
    acro = reader.trailer["/Root"].get("/AcroForm")
    xfa = acro.get_object().get("/XFA") if acro else None
    if xfa is None:
        return {}
    packets = {str(xfa[i]): xfa[i + 1].get_object() for i in range(0, len(xfa), 2)}
    if "template" not in packets:
        return {}
    root = ET.fromstring(packets["template"].get_data())

    found = {}

    def walk(el, path, counts):
        for child in el:
            kind = _local(child.tag)
            if kind not in XFA_CONTAINERS:
                continue
            name = child.get("name")
            if name:
                idx = counts[name]
                counts[name] += 1
                child_path = path + [f"{name}[{idx}]"]
                child_counts = defaultdict(int)
            else:
                child_path, child_counts = path, counts
            if kind == "field":
                desc = None
                for sub in child.iter():
                    if _local(sub.tag) in ("toolTip", "speak") and _text(sub):
                        desc = _text(sub)  # prefer toolTip; speak is the fallback
                        if _local(sub.tag) == "toolTip":
                            break
                if desc is None:
                    cap = next((s for s in child.iter() if _local(s.tag) == "caption"), None)
                    desc = _text(cap) if cap is not None else ""
                found[".".join(child_path)] = desc
            else:
                walk(child, child_path, child_counts)

    walk(root, [], defaultdict(int))
    return found


def list_fields(pdf_path):
    reader = PdfReader(pdf_path)
    xfa_desc = xfa_descriptions(reader)
    rows = []
    # Walk the widget annotations page by page so we know where each field sits.
    for page_num, page in enumerate(reader.pages, start=1):
        for annot_ref in page.get("/Annots", []) or []:
            annot = annot_ref.get_object()
            if annot.get("/Subtype") != "/Widget":
                continue
            field_type = _inherited(annot, "/FT")
            rect = [round(float(v)) for v in annot["/Rect"]]
            name = _full_name(annot)
            row = {
                "page": page_num,
                "name": name,
                "type": FIELD_TYPES.get(field_type, str(field_type)),
                "tooltip": str(_inherited(annot, "/TU") or ""),
                "xfa_desc": xfa_desc.get(name, ""),
                "rect": rect,
                "max_len": _inherited(annot, "/MaxLen"),
            }
            if field_type == "/Btn":
                # A checkbox's "on" value is whatever appearance state isn't /Off.
                states = annot.get("/AP", {}).get("/N", {}).keys()
                row["on_states"] = [s for s in states if s != "/Off"]
            rows.append(row)
    return rows


def format_rows(rows):
    lines = [f"{len(rows)} fields\n"]
    for r in rows:
        lines.append(f"[page {r['page']}] {r['name']}")
        lines.append(f"    type:    {r['type']}")
        lines.append(f"    tooltip: {r['tooltip'] or '(none in AcroForm)'}")
        lines.append(f"    xfa:     {r['xfa_desc'] or '(none)'}")
        lines.append(f"    rect:    {r['rect']}  (x1, y1, x2, y2 in points, origin bottom-left)")
        if r["max_len"] is not None:
            lines.append(f"    max_len: {r['max_len']}")
        if "on_states" in r:
            lines.append(f"    on value: {', '.join(r['on_states'])}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    pdf_path = sys.argv[1] if len(sys.argv) > 1 else "forms/fw9.pdf"
    out_path = sys.argv[2] if len(sys.argv) > 2 else "output/w9_fields.txt"
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    text = format_rows(list_fields(pdf_path))
    Path(out_path).write_text(text, encoding="utf-8")
    print(f"Wrote {out_path}")
