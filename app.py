import streamlit as st
import os
import tempfile
from doc_processor import DocumentProcessor
from converters import DocumentConverter

# Set page configuration
st.set_page_config(
    page_title="Document Structuring Agent",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize the processor with OpenAI API key - WITH CUSTOM MESSAGE
@st.cache_resource(show_spinner="Initializing AI processor...")
def init_processor(advanced_cleaning=True):
    openai_api_key = st.secrets.get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") 
    if not openai_api_key:
        openai_api_key = st.sidebar.text_input("Enter your OpenAI API key:", type="password")
    
    if not openai_api_key:
        st.error("Please provide an OpenAI API key to continue.")
        st.stop()
    
    return DocumentProcessor(openai_api_key, advanced_cleaning)

# Cache the document processing function - WITH CUSTOM MESSAGE
@st.cache_data(show_spinner="Analyzing document structure...")
def process_document_data(_processor, file_path, file_type, advanced_mode):
    """
    This function is cached. If the same file is uploaded again, it will use the cached result
    instead of reprocessing, making the rerun after download very fast.
    """
    extracted_text = _processor.extract_text_from_file(file_path, file_type)
    structured_output = _processor.structure_document(extracted_text, advanced_mode)
    return extracted_text, structured_output

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
    st.title("📄 Document Structuring Agent")
    st.markdown("Transform unstructured documents into well-organized, structured content with AI.")
    
    # Advanced options in sidebar
    st.sidebar.header("Advanced Options")
    advanced_mode = st.sidebar.checkbox("Enable Advanced Cleaning", value=True, 
                                       help="Remove duplicates and redundant information")
    
    # Initialize processor (cached)
    processor = init_processor(advanced_mode)
    
    # File upload
    uploaded_file = st.file_uploader("Upload a document", type=["pdf", "docx", "txt"])
    
    # Use session state to store processed data
    if 'processed_data' not in st.session_state:
        st.session_state.processed_data = None
    if 'uploaded_file_id' not in st.session_state:
        st.session_state.uploaded_file_id = None

    if uploaded_file is not None:
        # Check if we have a new file
        current_file_id = f"{uploaded_file.name}_{uploaded_file.size}"
        if current_file_id != st.session_state.uploaded_file_id:
            # It's a new file, reset processed data
            st.session_state.processed_data = None
            st.session_state.uploaded_file_id = current_file_id
        
        # Get file type
        file_type = get_file_type(uploaded_file.name)
        
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}") as tmp_file:
            tmp_file.write(uploaded_file.getvalue())
            tmp_path = tmp_file.name
        
        try:
            # Process document only if we haven't done it yet or if it's a new file
            if st.session_state.processed_data is None:
                # Create a status container for progress updates
                status_text = st.empty()
                status_text.text("Extracting text from document...")
                
                # Process the document
                extracted_text, structured_output = process_document_data(processor, tmp_path, file_type, advanced_mode)
                
                # Update status
                status_text.text("Finalizing structured document...")
                
                # Store results in session state
                st.session_state.processed_data = (extracted_text, structured_output)
                
                # Clear status
                status_text.empty()
            else:
                # Use cached data from session state
                extracted_text, structured_output = st.session_state.processed_data
            
            # Display results
            st.success("✅ Document processed successfully!")
            
            # Create tabs for different views
            tab1, tab2 = st.tabs(["Structured Output", "Original Text"])
            
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
                    if os.path.exists(pdf_path):
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
                    if os.path.exists(docx_path):
                        os.unlink(docx_path)
            
            with tab2:
                st.markdown("### Original Extracted Text")
                st.text_area("Original text", extracted_text, height=400, key="original_text")
        
        except Exception as e:
            st.error(f"Error processing document: {str(e)}")
        
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

if __name__ == "__main__":
    main()