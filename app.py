import streamlit as st
import os
import tempfile
from doc_processor import DocumentProcessor
from converters import DocumentConverter
from advanced_cleaner import AdvancedTextCleaner

# Set page configuration
st.set_page_config(
    page_title="Advanced Document Structuring Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize the processor with OpenAI API key
def init_processor(advanced_cleaning=True):
    openai_api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        openai_api_key = st.sidebar.text_input("Enter your OpenAI API key:", type="password")
    
    if not openai_api_key:
        st.error("Please provide an OpenAI API key to continue.")
        st.stop()
    
    return DocumentProcessor(openai_api_key, advanced_cleaning)

def get_file_type(file_name):
    """Get file type from file name"""
    if file_name.lower().endswith('.pdf'):
        return 'pdf'
    elif file_name.lower().endswith('.docx'):
        return 'docx'
    elif file_name.lower().endswith('.txt'):
        return 'txt'
    else:
        raise ValueError("Unsupported file type")

def main():
    st.title("📄 Advanced Document Structuring Agent")
    st.markdown("Transform messy, redundant documents into clean, well-organized content with AI.")
    
    # Advanced options in sidebar
    st.sidebar.header("Advanced Options")
    advanced_mode = st.sidebar.checkbox("Enable Advanced Cleaning", value=True, 
                                       help="Remove duplicates and redundant information")
    
    show_analysis = st.sidebar.checkbox("Show Duplicate Analysis", value=False,
                                       help="Show detected duplicates before processing")
    
    # Initialize processor
    processor = init_processor(advanced_mode)
    
    # File upload
    uploaded_file = st.file_uploader("Upload a document", type=["pdf", "docx", "txt"])
    
    if uploaded_file is not None:
        # Get file type
        file_type = get_file_type(uploaded_file.name)
        
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        try:
            # Extract text without advanced cleaning first for analysis
            if file_type == "pdf":
                extracted_text = processor.extract_text_from_pdf(tmp_path)
            elif file_type == "docx":
                extracted_text = processor.extract_text_from_docx(tmp_path)
            else:
                extracted_text = processor.extract_text_from_txt(tmp_path)
            
            # Show duplicate analysis if requested
            if show_analysis and advanced_mode:
                cleaner = AdvancedTextCleaner()
                sentences, duplicate_groups = cleaner.find_and_highlight_duplicates(extracted_text)
                
                if duplicate_groups:
                    st.sidebar.subheader("Duplicate Analysis")
                    st.sidebar.write(f"Found {len(duplicate_groups)} groups of similar content")
                    
                    for i, group in enumerate(duplicate_groups):
                        with st.sidebar.expander(f"Duplicate Group {i+1} ({len(group)} instances)"):
                            for j, sentence in enumerate(group):
                                st.write(f"{j+1}. {sentence}")
                else:
                    st.sidebar.info("No significant duplicates found")
            
            # Process document with advanced cleaning if enabled
            with st.spinner(f"Extracting text from {file_type.upper()}..."):
                final_text = processor.extract_text_from_file(tmp_path, file_type)
            
            with st.spinner("Analyzing and restructuring content..."):
                structured_output = processor.structure_document(final_text, advanced_mode)
            
            # Display results
            st.success("Document processed successfully!")
            
            # Create tabs for different views
            tab1, tab2, tab3 = st.tabs(["Structured Output", "Cleaned Text", "Original Text"])
            
            with tab1:
                st.markdown("### Structured Document")
                st.markdown(structured_output)
                
                # Download buttons
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.download_button(
                        label="Download as Markdown",
                        data=structured_output,
                        file_name="structured_document.md",
                        mime="text/markdown"
                    )
                
                with col2:
                    pdf_path = DocumentConverter.create_download_file(structured_output, "pdf")
                    with open(pdf_path, "rb") as f:
                        st.download_button(
                            label="Download as PDF",
                            data=f,
                            file_name="structured_document.pdf",
                            mime="application/pdf"
                        )
                    # Clean up temporary file
                    os.unlink(pdf_path)
                
                with col3:
                    docx_path = DocumentConverter.create_download_file(structured_output, "docx")
                    with open(docx_path, "rb") as f:
                        st.download_button(
                            label="Download as DOCX",
                            data=f,
                            file_name="structured_document.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )
                    # Clean up temporary file
                    os.unlink(docx_path)
            
            with tab2:
                st.markdown("### Cleaned Text (After Advanced Processing)")
                st.text_area("Cleaned text", final_text, height=400)
            
            with tab3:
                st.markdown("### Original Extracted Text")
                st.text_area("Original text", extracted_text, height=400)
        
        except Exception as e:
            st.error(f"Error processing document: {str(e)}")
        
        finally:
            # Clean up temporary file
            os.unlink(tmp_path)

if __name__ == "__main__":
    main()