"""Load W-9 values from a CRM export (crm.json).

Only CRM-specific knowledge lives here: where each value sits in the JSON
and how the CRM's vocabulary maps to ours ("LLC" -> "llc"). Format checks
belong to the schema, so they apply equally to every source.
"""
import json
from pathlib import Path

from w9_filler.provenance import FieldValue

# schema key -> dotted path inside crm.json
CRM_PATHS = {
    "legal_name": "company.legal_name",
    "business_name": "company.dba_name",
    "tax_classification": "company.entity_type",
    "llc_tax_class_code": "tax.llc_tax_classification",
    "address": "company.address.street",
    "city": "company.address.city",
    "state": "company.address.state",
    "zip": "company.address.postal_code",
    "ein": "tax.ein",
    "ssn": "tax.ssn",
}

# CRM entity types -> schema tax classifications. Unknown values pass through
# unchanged so validation reports them instead of guessing.
ENTITY_TYPES = {
    "individual": "individual",
    "sole proprietor": "individual",
    "c corporation": "c_corp",
    "s corporation": "s_corp",
    "partnership": "partnership",
    "trust": "trust_estate",
    "estate": "trust_estate",
    "llc": "llc",
}


def _lookup(data, path):
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


def load_crm(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    values = []
    for key, json_path in CRM_PATHS.items():
        raw = _lookup(data, json_path)
        if raw is None or str(raw).strip() == "":
            continue  # absent here; validation decides whether that matters
        value = raw
        if key == "tax_classification":
            value = ENTITY_TYPES.get(str(raw).strip().lower(), raw)
        values.append(FieldValue(key, value, source=path.name, locator=json_path, raw=raw,
                                 method="lookup"))
    return values
