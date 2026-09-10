"""Extract PDF text for MongoDB indexing. Each nonempty page becomes a source record with title, file name and page number so answers can cite its location; shared ingestion preprocessing may split it into chunks."""

from pathlib import Path
from typing import Dict, List

from PyPDF2 import PdfReader

from app.logger import logger

def load_documents_from_pdf(file_path: str) -> List[Dict[str, str]]:
    """Extract nonempty PDF pages as indexable records containing title, snippet, category, source, page_number, total_pages and file_name. file_path identifies the source PDF."""
    documents: List[Dict[str, str]] = []
    
    try:
        pdf_reader = PdfReader(file_path)
        file_name = Path(file_path).stem
        total_pages = len(pdf_reader.pages)
        
        logger.info(f"Processing PDF: {file_name} with {total_pages} pages")
        
        for page_num, page in enumerate(pdf_reader.pages, start=1):
            text = page.extract_text()
            
            if not text or not text.strip():
                logger.warning(f"Skipping empty page {page_num} in {file_name}")
                continue
            
            text = text.strip()
            
            documents.append({
                "title": f"{file_name} - Page {page_num}",
                "snippet": text,  # Shared chunking preserves the end of every page.
                "category": "pdf-document",
                "source": f"pdf-ingest:{file_name}",
                "page_number": str(page_num),
                "total_pages": str(total_pages),
                "file_name": file_name,
            })
        
        logger.info(f"Successfully extracted {len(documents)} pages from {file_name}")
        
    except Exception as e:
        logger.error(f"Error processing PDF {file_path}: {str(e)}")
        raise
    
    return documents

def load_documents_from_pdf_full_content(file_path: str) -> List[Dict[str, str]]:
    """Unused alternative: concatenate the entire PDF into one record without per-page splitting."""
    documents: List[Dict[str, str]] = []
    
    try:
        pdf_reader = PdfReader(file_path)
        file_name = Path(file_path).stem
        total_pages = len(pdf_reader.pages)
        
        logger.info(f"Processing PDF as single document: {file_name} with {total_pages} pages")
        
        full_text = ""
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text and text.strip():
                full_text += text + "\n\n"
        
        if full_text.strip():
            documents.append({
                "title": file_name,
                "snippet": full_text.strip(),
                "category": "pdf-document",
                "source": f"pdf-ingest:{file_name}",
                "total_pages": str(total_pages),
                "file_name": file_name,
            })
            
            logger.info(f"Successfully extracted full content from {file_name}")
        else:
            logger.warning(f"No text content found in {file_name}")
        
    except Exception as e:
        logger.error(f"Error processing PDF {file_path}: {str(e)}")
        raise
    
    return documents