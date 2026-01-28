import os
import fitz # Still needed for fallback or basic info
from logger import setup_logger

logger = setup_logger(__name__)

try:
    from magic_pdf.pipe.UNIPipe import UNIPipe
    from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter
except ImportError:
    logger.warning("MinerU (magic-pdf) not installed. Falling back to basic extraction.")
    UNIPipe = None

def extract_pdf_content_mineru(file_path):
    """
    Extracts content from PDF using MinerU's UNIPipe.
    Returns a list of dictionaries with text and layout info, or None if failed.
    """
    if not UNIPipe:
        # Fallback to PyMuPDF extraction
        logger.warning("MinerU not available. Using standard text extraction.")
        try:
            doc = fitz.open(file_path)
            full_text = ""
            for i, page in enumerate(doc):
                full_text += page.get_text() + "\n"
            return full_text
        except Exception as e:
            logger.error(f"Fallback extraction failed: {e}")
            return None

    logger.info(f"⛏️  MinerU: Processing {os.path.basename(file_path)}...")
    
    try:
        # 1. Prepare Reader
        parent_dir = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        image_writer = DiskReaderWriter(os.path.join(parent_dir, "images"))
        
        # 2. Initialize Pipe
        # Note: magic-pdf usually requires model caching. 
        # If models aren't present, this might try to download them.
        pipe = UNIPipe(file_path)
        
        # 3. Run Classification & Parse
        pipe.pipe_classify()
        pipe.pipe_analyze()
        pipe.pipe_parse()
        
        # 4. Get Results
        # content_list = pipe.get_text_content() # This might vary by version
        md_content = pipe.pipe_mk_markdown()
        
        # Return as a single "Page" concept for now, or split by page if supported
        # UNIPipe effectively converts the whole doc.
        
        return md_content
        
    except Exception as e:
        logger.error(f"MinerU Extraction Failed: {e}")
        return None
