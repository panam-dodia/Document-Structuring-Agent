# Document Structuring Agent & Form Auto-Fill

An AI-powered toolkit for working with business documents:

1. **Document Structuring:** transforms unstructured documents (PDF, DOCX, TXT) into clean, organized Markdown, exportable to PDF and DOCX.
2. **Form Auto-Fill:** fills official government and tax PDF forms from a client's CRM data and documents. Every value is verified and traceable to its source. The **IRS Form W-9** is the first supported form, and the architecture is built to add more.

## 🚀 Quick Start

### Prerequisites

- Python 3.8 or higher (3.11 recommended)
- OpenAI API key
- Git

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/panam-dodia/Document-Structuring-Agent.git
   cd Document-Structuring-Agent
   ```

2. **Create and activate virtual environment**
   ```bash
   # On Windows
   python -m venv venv
   venv\Scripts\activate

   # On macOS/Linux
   python -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up OpenAI API key**
   ```bash
   # Create secrets directory
   mkdir .streamlit

   # Create secrets file (replace with your actual API key)
   echo "OPENAI_API_KEY = 'your-openai-api-key-here'" > .streamlit/secrets.toml
   ```

5. **Run the document structuring app**
   ```bash
   streamlit run app.py
   ```

6. **Open your browser** and navigate to `http://localhost:8501`

## 📝 Form Auto-Fill

Fills official PDF forms automatically, combining structured client data with information extracted from the client's documents.

### How it works

```
CRM record (JSON)  ───────────────────────────────►  values
Client documents ─► text extraction & cleanup (per page)
                    ├─ regex: fixed-format IDs (EIN/SSN) ─►  values
                    └─ GPT-4-turbo structured output ─────►  values + quote + page + confidence
                                                            └─ quote & number verification
        ▼
  merge by source priority  ─►  schema validation  ─►  fill PDF  ─►  verify  ─►  audit report
```

- **Source priority:** structured CRM data comes first; documents only fill the gaps.
- **Hybrid extraction:** regex reads fixed-format numbers exactly, and only when they're labelled (e.g. "EIN"). The LLM handles fields that need understanding, such as entity type and tax classification.
- **Grounded LLM output:** every extracted value must come with a verbatim quote from the document. Quotes are checked against the text (exact, then whitespace/Unicode-normalized; deliberately not fuzzy), and numbers are checked digit by digit.
- **Human in the loop:** missing, malformed, unverified or ambiguous values are never written to the form. They're listed for review, and the run exits with code 1.
- **Provenance:** every filled value records its source file, location (JSON path, or page + quote), original raw value and extraction method, saved as `w9_provenance.json`.
- **Reliable PDF output:** handles Adobe hybrid AcroForm/XFA forms, comb (one-character-per-box) fields and custom checkbox values, and renders correctly in Chrome, Edge and Acrobat.
- **Reproducible:** LLM responses are cached by document hash, model and prompt version, so reruns are free and give the same result.

### Usage

```bash
# Fill the form for a client folder (crm.json + any PDFs in it)
python -m w9_filler.fill_w9 clients/bluebird_bakery

# Read the filled PDF back and check it
python -m w9_filler.verify clients/bluebird_bakery

# Force a fresh LLM extraction instead of the cached answer
python -m w9_filler.fill_w9 clients/bluebird_bakery --refresh
```

Output goes to `output/<client>/`: the filled PDF, a provenance report, and an extraction log per document.

Example summary:
```
Filled (9):
  legal_name          Bluebird Bakery LLC   crm.json : company.legal_name
  llc_tax_class_code  P                     articles_of_organization.pdf [llm] : page 2: "...elected to be taxed as a partnership"
  ein                 00-0000000            crm.json : tax.ein
  ...
Needs attention (0):
  nothing
```

### Supported forms

| Form | Status |
|---|---|
| IRS W-9 (Rev. March 2024) | ✅ Supported |
| Other IRS and government forms | 🔜 Planned |

**Adding a form** takes three form-specific pieces; the extraction, verification, provenance and PDF engine are shared:
1. **Field inspection:** run `inspect_fields.py` on the blank PDF to list its fields, and `debug_fill.py` to see where each one lands.
2. **Field map:** map the PDF's internal field names to meaningful names.
3. **Schema:** define each field's type, whether it's required, and its format rules.

### Sample data

`clients/` contains **synthetic** test clients only: a fictional "Bluebird Bakery LLC", with placeholder IDs such as EIN `00-0000000`, and generated documents marked "SYNTHETIC TEST DOCUMENT". No real taxpayer data is included.

## 📁 Project Structure

```
Document-Structuring-Agent/
├── app.py                    # Streamlit app for document structuring
├── doc_processor.py          # Document ingestion and LLM structuring
├── converters.py             # Markdown to PDF/DOCX export
├── advanced_cleaner.py       # Text cleaning and deduplication
├── forms/
│   └── fw9.pdf               # Blank IRS W-9 from irs.gov
├── clients/                  # Synthetic test clients (crm.json + documents)
├── w9_filler/                # Form auto-fill
│   ├── fill_w9.py            # Runs the pipeline
│   ├── schema.py             # Form data model and validation rules
│   ├── field_map.py          # Meaningful names -> PDF field names
│   ├── provenance.py         # Source tracking and source priority
│   ├── pdf_form.py           # PDF filling and cross-viewer fixes
│   ├── verify.py             # Read-back verification of the filled PDF
│   ├── inspect_fields.py     # Lists a PDF's form fields
│   ├── debug_fill.py         # Fills each field with its own name
│   ├── make_test_documents.py# Generates the synthetic test PDFs
│   └── sources/
│       ├── crm.py            # Structured CRM data
│       ├── document.py       # LLM extraction with quote verification
│       └── patterns.py       # Regex extraction for fixed-format IDs
├── NOTES.md                  # Engineering notes: decisions, problems, fixes
├── requirements.txt
└── README.md
```

## 🎯 Document Structuring Usage

1. **Upload a Document**: click "Upload a document" and select your PDF, DOCX, or TXT file
2. **Process**: the AI analyzes and structures your document automatically
3. **Review**: view the structured output in clean Markdown format
4. **Download**: export the result as Markdown, PDF, or DOCX

### Supported Document Types

- **PDF Documents**: text extraction with layout preservation
- **Word Documents**: full DOCX support with formatting awareness
- **Text Files**: plain text processing with encoding detection

## 🛠️ Technology Stack

- **Frontend**: Streamlit
- **AI Processing**: OpenAI GPT-4-turbo via LangChain, with strict structured outputs for extraction
- **Document Processing**:
  - `pdfplumber` for PDF text extraction
  - `python-docx` for Word documents
  - `xhtml2pdf` for PDF generation
- **PDF Forms**:
  - `pypdf` for reading and filling form fields
  - `pypdfium2` for rendering checks
  - `reportlab` for generating synthetic test documents
- **Text Analysis**:
  - TF-IDF vectorization (scikit-learn) for duplicate detection
  - Cosine similarity for content matching
  - Regular expressions for fixed-format identifiers
- **Validation**: Pydantic models generated from the form schema

## 🌟 Key Features Explained

### Intelligent Document Analysis
Advanced prompt engineering identifies document structure and key sections, and builds logical hierarchies.

### Duplicate Detection
TF-IDF vectorization and cosine similarity identify and remove redundant content while preserving information.

### Long Documents
A map-reduce strategy splits long documents into chunks, structures them in parallel, and combines the results.

### Multi-format Export
- **Markdown**: for easy editing and version control
- **PDF**: for sharing and printing
- **DOCX**: for Microsoft Word compatibility

### Verified Form Filling
See [Form Auto-Fill](#-form-auto-fill) above, and [NOTES.md](NOTES.md) for the engineering decisions and every problem found and fixed along the way.

## 🙏 Acknowledgments

- OpenAI for the GPT-4 API
- Streamlit for the web framework
- The open-source community for the supporting libraries

⭐ **If you find this project useful, please give it a star on GitHub!**
