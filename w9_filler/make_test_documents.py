"""Generate synthetic client documents (real text layer, not scans).

Existing files are kept unless --force: the LLM cache is keyed on the PDF's
hash, so rebuilding a document would trigger a new (paid) extraction.

Usage:
    python -m w9_filler.make_test_documents [--force]
"""
import sys
from pathlib import Path

from reportlab import rl_config
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

rl_config.invariant = 1  # no timestamps/random IDs: same content -> same bytes -> same hash

ARTICLES = Path("clients/bluebird_bakery/articles_of_organization.pdf")
BANK_SUMMARY = Path("clients/test_ein_from_document/bank_account_summary.pdf")

BANNER = "SYNTHETIC TEST DOCUMENT - NOT A REAL FILING - ALL DATA IS FICTIONAL"

# Deliberate traps for extraction:
# - the registered office address differs from the CRM's mailing address
#   (a registered agent's address isn't necessarily the W-9 address);
# - "Example State" is the formation state, not the address state "ST";
# - "Company's" has an apostrophe, which advanced_cleaner.py strips;
# - the tax election is on page 2, so page numbers are actually tested.
PAGE_1 = [
    ("h", "ARTICLES OF ORGANIZATION"),
    ("c", "of"),
    ("h", "Bluebird Bakery LLC"),
    ("c", "Filed with the Office of the Secretary of State of Example State"),
    ("a", "Article I - Name"),
    ("p", "The name of the limited liability company is Bluebird Bakery LLC "
          "(the \"Company\")."),
    ("a", "Article II - Entity Type and Formation"),
    ("p", "The Company is a limited liability company organized under the Limited "
          "Liability Company Act of Example State. The Company shall have perpetual "
          "existence unless dissolved in accordance with its operating agreement."),
    ("a", "Article III - Registered Office"),
    ("p", "The street address of the Company's registered office is 456 Sample Avenue, "
          "Anytown, ST 00000, and the name of its registered agent at that address is "
          "Example Registered Agents Inc."),
    ("a", "Article IV - Purpose"),
    ("p", "The purpose of the Company is to operate a retail bakery and cafe, to sell "
          "baked goods at wholesale to restaurants and grocers, and to engage in any "
          "other lawful business for which limited liability companies may be "
          "organized under the laws of Example State."),
    ("a", "Article V - Members"),
    ("p", "The Company has two members, Alex Example and Sam Sample, each holding a "
          "fifty percent membership interest."),
]

PAGE_2 = [
    ("a", "Article VI - Federal Tax Classification"),
    ("p", "Because the Company has more than one member, the members have agreed that "
          "the Company has elected to be taxed as a partnership for federal income tax "
          "purposes, and the Company shall not file an election to be classified as an "
          "association taxable as a corporation."),
    ("a", "Article VII - Management"),
    ("p", "The Company shall be managed by its members. Each member shall have authority "
          "to bind the Company in the ordinary course of its business."),
    ("a", "Article VIII - Organizer"),
    ("p", "The name of the organizer is Alex Example. Executed on January 2, 2024."),
    ("p", "Signature of organizer: ______________________________"),
]


# For the hybrid regex/LLM test: one labelled EIN among look-alike numbers.
# - "Application reference" has the EIN's shape but no EIN label;
# - the 9-digit account number is an EIN without a dash, also unlabelled;
# - the phone number and ZIP are other digit runs.
BANK_PAGE = [
    ("h", "Example Community Bank"),
    ("c", "Business Account Opening Summary"),
    ("p", "Prepared for: Bluebird Bakery LLC"),
    ("p", "Application reference: 99-0000001"),
    ("p", "Account type: Business checking. Account number: 000123456"),
    ("p", "Federal Employer Identification Number (EIN) on file: 00-0000000"),
    ("p", "Mailing address on file: 123 Example Street, Suite 0, Anytown, ST 00000"),
    ("p", "Branch phone: 555-0100. This summary is for your records only."),
]


def _story(blocks, styles):
    out = []
    for kind, text in blocks:
        out.append(Paragraph(text, styles[kind]))
        out.append(Spacer(1, 6 if kind != "a" else 2))
    return out


def _banner(total_pages):
    def draw(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawCentredString(letter[0] / 2, letter[1] - 0.5 * inch, BANNER)
        canvas.setFont("Helvetica", 8)
        canvas.drawCentredString(letter[0] / 2, 0.5 * inch, f"Page {doc.page} of {total_pages}")
        canvas.restoreState()
    return draw


def build(path, pages, title):
    base = getSampleStyleSheet()
    styles = {
        "h": ParagraphStyle("h", parent=base["Title"], fontSize=16, spaceAfter=2),
        "c": ParagraphStyle("c", parent=base["Normal"], alignment=1),
        "a": ParagraphStyle("a", parent=base["Heading3"], spaceBefore=8),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontSize=11, leading=15),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter, title=title,
                            topMargin=inch, bottomMargin=inch)
    story = []
    for i, blocks in enumerate(pages):
        if i:
            story.append(PageBreak())
        story += _story(blocks, styles)
    draw = _banner(len(pages))
    doc.build(story, onFirstPage=draw, onLaterPages=draw)
    return path


DOCUMENTS = [
    (ARTICLES, [PAGE_1, PAGE_2], "Articles of Organization (synthetic)"),
    (BANK_SUMMARY, [BANK_PAGE], "Business Account Opening Summary (synthetic)"),
]

if __name__ == "__main__":
    force = "--force" in sys.argv
    for path, pages, title in DOCUMENTS:
        if path.exists() and not force:
            print(f"Kept  {path} (exists; --force to rebuild)")
        else:
            print(f"Wrote {build(path, pages, title)}")
