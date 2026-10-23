"""Low-level AcroForm fill/read helpers built on pypdf."""
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
)

COMB = 1 << 24       # /Ff bit 25: one character per evenly spaced cell
MULTILINE = 1 << 12  # /Ff bit 13


def fill_pdf(template_path, values, output_path, remove_xfa=True):
    """Fill AcroForm fields and write a new PDF.

    values: {fully qualified field name: value}. Text fields take a str;
    checkboxes take their "on" export value (e.g. "/6") or "/Off".
    """
    writer = PdfWriter(clone_from=template_path)
    acro = writer._root_object["/AcroForm"]

    if remove_xfa and "/XFA" in acro:
        # Hybrid forms carry a second copy of the form as XFA. Adobe Reader
        # renders the XFA copy and ignores what we write to the AcroForm
        # fields, so the filled values would look blank there. Dropping
        # /XFA makes every viewer use the AcroForm data.
        del acro["/XFA"]

    root = writer._root_object
    if "/Perms" in root:
        # IRS forms are "Reader-extended": /Perms /UR3 is an Adobe signature
        # over the original bytes. Filling breaks it, and Adobe-engine viewers
        # (Acrobat, Edge) then warn "signatures are invalid". Drop it.
        del root["/Perms"]
        acro[NameObject("/SigFlags")] = NumberObject(0)

    for page in writer.pages:
        if "/Annots" not in page:
            continue  # pages 2-6 of the W-9 are instructions with no fields
        # auto_regenerate=True (default) also sets /NeedAppearances so viewers
        # rebuild appearances; pypdf generates text appearance streams itself.
        writer.update_page_form_field_values(page, values, auto_regenerate=True)
        _fix_text_appearances(page, acro)

    # Deleting /XFA only unlinks the XFA packets; pypdf still writes them as
    # unreferenced objects. With those leftovers, Edge's Adobe engine showed
    # the form blank (NOTES.md, problem 8). Re-cloning copies only objects
    # reachable from the root, which drops them. (compress_identical_objects
    # with remove_orphans=True missed the unlinked /Perms signature.)
    buffer = BytesIO()
    writer.write(buffer)
    clean = PdfWriter(clone_from=PdfReader(buffer))
    clean.pdf_header = b"%PDF-1.7"  # pypdf defaults to 1.3; the source is 1.7

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        clean.write(f)


def _fix_text_appearances(page, acro):
    """Redraw appearances pypdf gets wrong: comb fields and centered/right text.

    pypdf's generated stream always left-aligns and ignores the Comb flag, so
    the SSN/EIN digits pile into the first box in any viewer that shows the
    stored appearance instead of regenerating it (see NOTES.md, problem 4).
    """
    for ref in page.get("/Annots", []) or []:
        annot = ref.get_object()
        if _inherited(annot, "/FT") != "/Tx" or "/V" not in annot:
            continue
        flags = int(_inherited(annot, "/Ff") or 0)
        align = int(_inherited(annot, "/Q") or 0)
        comb = bool(flags & COMB) and _inherited(annot, "/MaxLen")
        if flags & MULTILINE or not (comb or align):
            continue  # pypdf's own appearance is fine for these

        old_ap = annot["/AP"]["/N"].get_object()
        font_name, size = _parse_da(_inherited(annot, "/DA") or acro.get("/DA"))
        widths = _font_widths(acro, font_name)
        text = str(annot["/V"])

        x1, y1, x2, y2 = (float(v) for v in annot["/Rect"])
        w, h = x2 - x1, y2 - y1
        y = (h - size * 0.7) / 2  # cap height ~0.7 em, centered vertically

        def text_width(s):
            return sum(widths.get(c, 556) for c in s) * size / 1000

        if comb:
            cell = w / int(_inherited(annot, "/MaxLen"))
            runs = [(i * cell + (cell - text_width(c)) / 2, c) for i, c in enumerate(text)]
        else:
            free = w - 4 - text_width(text)
            runs = [(2 + (free / 2 if align == 1 else free), text)]

        ops = [f"q /Tx BMC q 1 1 {w - 2:.2f} {h - 2:.2f} re W n BT /{font_name} {size:g} Tf 0 g"]
        ops += [f"1 0 0 1 {x:.2f} {y:.2f} Tm ({_escape(s)}) Tj" for x, s in runs]
        ops.append("ET Q EMC Q")

        stream = DecodedStreamObject()
        stream.set_data("\n".join(ops).encode("cp1252"))
        for key in ("/Type", "/Subtype", "/BBox", "/Resources"):
            if key in old_ap:
                stream[NameObject(key)] = old_ap[key]
        annot["/AP"][NameObject("/N")] = stream


def _parse_da(da):
    """'/HelveticaLTStd-Bold 9.00 Tf 0 g' -> ('HelveticaLTStd-Bold', 9.0)."""
    tokens = str(da).split()
    i = tokens.index("Tf")
    size = float(tokens[i - 1]) or 9.0  # 0 means auto-size; fall back to 9pt
    return tokens[i - 2].lstrip("/"), size


def _font_widths(acro, font_name):
    """Glyph widths (1/1000 em) from the font in the form's /DR resources."""
    try:
        font = acro["/DR"]["/Font"][f"/{font_name}"].get_object()
        first = int(font["/FirstChar"])
        return {chr(first + i): float(w) for i, w in enumerate(font["/Widths"])}
    except KeyError:
        return {}


def _escape(s):
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _inherited(obj, key):
    while obj is not None:
        if key in obj:
            return obj[key]
        parent = obj.get("/Parent")
        obj = parent.get_object() if parent is not None else None
    return None


def read_values(pdf_path):
    """Return {fully qualified field name: stored /V value} for every field."""
    fields = PdfReader(pdf_path).get_fields() or {}
    return {name: f.get("/V") for name, f in fields.items() if "/FT" in f}


def widget_states(pdf_path):
    """Return {fully qualified field name: /AS} for every checkbox widget.

    /V is the field's logical value; /AS picks which appearance is drawn.
    Both must say "on" for a checkbox to be ticked everywhere.
    """
    states = {}
    for page in PdfReader(pdf_path).pages:
        for ref in page.get("/Annots", []) or []:
            annot = ref.get_object()
            if "/AS" in annot:
                states[_qualified(annot)] = annot["/AS"]
    return states


def unreferenced_objects(pdf_path):
    """Return ids of objects in the file that nothing points to."""
    reader = PdfReader(pdf_path)
    all_ids = {i for gen in reader.xref.values() for i in gen if i != 0}
    seen, stack = set(), [reader.trailer]
    while stack:
        obj = stack.pop()
        if isinstance(obj, IndirectObject):
            if obj.idnum in seen:
                continue
            seen.add(obj.idnum)
            obj = obj.get_object()
        if isinstance(obj, DictionaryObject):
            stack.extend(obj.values())
        elif isinstance(obj, ArrayObject):
            stack.extend(obj)
    return sorted(all_ids - seen)


def _qualified(annot):
    parts, obj = [], annot
    while obj is not None:
        if "/T" in obj:
            parts.append(str(obj["/T"]))
        parent = obj.get("/Parent")
        obj = parent.get_object() if parent is not None else None
    return ".".join(reversed(parts))
