"""
Extraction de texte depuis des fichiers PDF pour l'indexation MongoDB Atlas.

Chaque page de PDF devient un document distinct (titre "<fichier> - Page N"),
ce qui permet ensuite de citer précisément la page source dans les
réponses du chat (voir `ChatWorkflow` -> `state.search_results[0].page_number`).
"""

from pathlib import Path
from typing import Dict, List

from PyPDF2 import PdfReader

from app.logger import logger

def load_documents_from_pdf(file_path: str) -> List[Dict[str, str]]:
    """
    Extrait le texte d'un PDF, une page = un document indexable séparément.

    Args:
        file_path: Chemin vers le fichier PDF

    Returns:
        Liste de documents (title, snippet, category, source, page_number,
        total_pages, file_name) ; les pages vides sont ignorées.
    """
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
                "snippet": text[:5000] if len(text) > 5000 else text,  # Limit snippet size
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
    """Variante non utilisée par les routes actuelles : concatène TOUT le PDF en un seul document (pas de découpage par page)."""
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