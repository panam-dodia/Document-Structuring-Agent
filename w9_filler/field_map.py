"""Meaningful names for the cryptic W-9 (Rev. March 2024) field names.

Derived from the XFA <speak> text (see output/w9_fields.txt) and confirmed
visually with debug_fill.py. If the IRS revises the form, re-run
inspect_fields.py; the f1_xx numbering can shift between revisions.
"""

P1 = "topmostSubform[0].Page1[0]."
BOX3 = P1 + "Boxes3a-b_ReadOrder[0]."
ADDR = P1 + "Address_ReadOrder[0]."

TEXT_FIELDS = {
    "legal_name": P1 + "f1_01[0]",                 # Line 1
    "business_name": P1 + "f1_02[0]",              # Line 2
    "llc_tax_class_code": BOX3 + "f1_03[0]",       # Line 3a, LLC code: C / S / P (max 1)
    "other_classification": BOX3 + "f1_04[0]",     # Line 3a, "Other" text
    "exempt_payee_code": P1 + "f1_05[0]",          # Line 4
    "fatca_code": P1 + "f1_06[0]",                 # Line 4
    "address": ADDR + "f1_07[0]",                  # Line 5
    "city_state_zip": ADDR + "f1_08[0]",           # Line 6
    "requester_name_address": P1 + "f1_09[0]",     # Optional, right of 5-6
    "account_numbers": P1 + "f1_10[0]",            # Line 7
    "ssn_part1": P1 + "f1_11[0]",                  # SSN first 3 digits
    "ssn_part2": P1 + "f1_12[0]",                  # SSN middle 2 digits
    "ssn_part3": P1 + "f1_13[0]",                  # SSN last 4 digits
    "ein_part1": P1 + "f1_14[0]",                  # EIN first 2 digits
    "ein_part2": P1 + "f1_15[0]",                  # EIN last 7 digits
}

# Line 3a: seven independent checkboxes, each with its own "on" export value.
# (They behave like a radio group but are not one in the PDF; nothing stops
# two being ticked, so the caller must tick exactly one.)
TAX_CLASSIFICATION = {
    "individual": (BOX3 + "c1_1[0]", "/1"),
    "c_corp": (BOX3 + "c1_1[1]", "/2"),
    "s_corp": (BOX3 + "c1_1[2]", "/3"),
    "partnership": (BOX3 + "c1_1[3]", "/4"),
    "trust_estate": (BOX3 + "c1_1[4]", "/5"),
    "llc": (BOX3 + "c1_1[5]", "/6"),
    "other": (BOX3 + "c1_1[6]", "/7"),
}

# Line 3b: foreign partners/owners/beneficiaries.
FOREIGN_PARTNERS = (BOX3 + "c1_2[0]", "/1")
