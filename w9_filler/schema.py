"""The W-9 data model: which fields we need, their types, and format rules.

Keys describe the *data* (city, state, zip), not the PDF layout (one
"City, state, and ZIP code" line). fill_w9.py maps data onto the form, so
sources never need to know how the form is drawn, and every rule here
applies no matter where a value came from.
"""
import re
from dataclasses import dataclass, replace
from typing import Optional

TAX_CLASSIFICATIONS = (
    "individual", "c_corp", "s_corp", "partnership", "trust_estate", "llc", "other",
)


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    type: str = "text"                      # text | choice | ein | ssn | state | zip
    required: bool = False
    required_if: Optional[tuple] = None     # (other_key, value): required when other_key == value
    choices: tuple = ()
    pattern: Optional[str] = None           # overrides the type's default rule
    rule: str = ""                          # the rule in words, for reports
    from_documents: bool = True             # False: never extract from client documents


def _digits(value):
    return re.sub(r"\D", "", value)


def _dashed(value, groups):
    """'000000000' -> '00-0000000' when the digit count is right; else unchanged."""
    d = _digits(value)
    if len(d) != sum(groups):
        return value
    parts, i = [], 0
    for n in groups:
        parts.append(d[i:i + n])
        i += n
    return "-".join(parts)


# Per type: (normalizer, default pattern, rule in words). Normalizing first
# means "000000000", "00 0000000" and "00-0000000" are all accepted as the
# same EIN, while "12-345" still fails.
TYPES = {
    "text": (lambda v: " ".join(v.split()), r".+", "non-empty text"),
    "choice": (lambda v: v.strip(), None, "one of the allowed values"),
    "ein": (lambda v: _dashed(v, (2, 7)), r"\d{2}-\d{7}", "9 digits (XX-XXXXXXX)"),
    "ssn": (lambda v: _dashed(v, (3, 2, 4)), r"\d{3}-\d{2}-\d{4}", "9 digits (XXX-XX-XXXX)"),
    "state": (lambda v: v.strip().upper(), r"[A-Z]{2}", "2-letter state code"),
    "zip": (lambda v: v.strip(), r"\d{5}(-\d{4})?", "5 digits, or ZIP+4"),
}

W9_SCHEMA = [
    FieldSpec("legal_name", "Line 1: Name of entity/individual", required=True),
    FieldSpec("business_name", "Line 2: Business/disregarded entity name"),
    FieldSpec("tax_classification", "Line 3a: Federal tax classification", "choice",
              required=True, choices=TAX_CLASSIFICATIONS),
    FieldSpec("llc_tax_class_code", "Line 3a: LLC tax classification (C/S/P)", "choice",
              required_if=("tax_classification", "llc"), choices=("C", "S", "P")),
    FieldSpec("other_classification", "Line 3a: Other classification",
              required_if=("tax_classification", "other")),
    FieldSpec("exempt_payee_code", "Line 4: Exempt payee code",
              pattern=r"[1-9]|1[0-3]", rule="a code from 1 to 13"),
    FieldSpec("fatca_code", "Line 4: FATCA exemption code",
              pattern=r"[A-M]", rule="a letter from A to M"),
    FieldSpec("address", "Line 5: Address", required=True),
    FieldSpec("city", "Line 6: City", required=True),
    FieldSpec("state", "Line 6: State", "state", required=True),
    FieldSpec("zip", "Line 6: ZIP code", "zip", required=True),
    # These describe the requester's side of the relationship. A client's
    # documents can't supply them: the LLM once put the client's *bank*
    # account number on line 7 (NOTES.md, problem 17).
    FieldSpec("requester_name_address", "Requester's name and address", from_documents=False),
    FieldSpec("account_numbers", "Line 7: Account numbers", from_documents=False),
    FieldSpec("ein", "Part I: Employer identification number", "ein"),
    FieldSpec("ssn", "Part I: Social security number", "ssn"),
]

SCHEMA = {spec.key: spec for spec in W9_SCHEMA}


@dataclass(frozen=True)
class Issue:
    key: str
    kind: str          # missing | format | rule
    message: str
    found: object = None
    source: str = ""


def normalize(spec, value):
    normalizer = TYPES[spec.type][0]
    return normalizer(str(value))


def check_format(spec, value):
    """Return None if value passes the field's rule, else the rule in words."""
    if spec.choices:
        return None if value in spec.choices else f"one of {', '.join(spec.choices)}"
    _, pattern, rule = TYPES[spec.type]
    pattern = spec.pattern or pattern
    if pattern and not re.fullmatch(pattern, value):
        return spec.rule or rule
    return None


def validate(resolved, known_issues=()):
    """Check resolved values against the schema.

    resolved: {key: FieldValue}. known_issues: problems already reported
    upstream (e.g. an unverified document value), so the same field isn't
    also reported as "missing". Returns (accepted, issues): accepted holds
    the normalized FieldValues that passed; anything missing or malformed
    becomes an Issue instead of being silently dropped.
    """
    accepted, issues = {}, []
    known = {i.key for i in known_issues}

    for spec in W9_SCHEMA:
        fv = resolved.get(spec.key)
        if fv is None or str(fv.value).strip() == "":
            continue
        value = normalize(spec, fv.value)
        failed_rule = check_format(spec, value)
        if failed_rule:
            issues.append(Issue(spec.key, "format", f"{spec.label}: must be {failed_rule}",
                                found=fv.value, source=fv.source))
        else:
            accepted[spec.key] = replace(fv, value=value)

    for spec in W9_SCHEMA:
        if not spec.required_if:
            continue
        other, when = spec.required_if
        applies = other in accepted and accepted[other].value == when
        if spec.key in accepted and not applies:
            # e.g. an LLC code when the box ticked isn't LLC: writing it
            # would put "P" next to an unticked box. Drop it and say why.
            fv = accepted.pop(spec.key)
            issues.append(Issue(spec.key, "rule",
                                f"{spec.label}: only applies when {other} is '{when}'; not filled",
                                found=fv.value, source=fv.source))

    for spec in W9_SCHEMA:
        if spec.key in accepted or spec.key in known or any(i.key == spec.key for i in issues):
            continue
        if spec.required:
            issues.append(Issue(spec.key, "missing", f"{spec.label}: required"))
        elif spec.required_if:
            other, when = spec.required_if
            if other in accepted and accepted[other].value == when:
                issues.append(Issue(spec.key, "missing",
                                    f"{spec.label}: required because {other} is '{when}'"))

    # Cross-field rule: the W-9 needs exactly one taxpayer ID.
    has_ein, has_ssn = "ein" in accepted, "ssn" in accepted
    tin_flagged = any(i.key in ("ein", "ssn") for i in issues)
    if has_ein and has_ssn:
        # We can't know which is right, so fill neither rather than both.
        found = f"EIN {accepted.pop('ein').value}, SSN {accepted.pop('ssn').value}"
        issues.append(Issue("ein/ssn", "rule",
                            "Part I: give an EIN or an SSN, not both; neither filled", found=found))
    elif not (has_ein or has_ssn) and not tin_flagged:
        issues.append(Issue("ein/ssn", "missing", "Part I: an EIN or SSN is required"))

    return accepted, issues
