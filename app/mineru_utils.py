import os
import subprocess
import fitz  # PyMuPDF
import glob
import shutil
import uuid
from app.logger import setup_logger

logger = setup_logger(__name__)

def extract_pdf_content_mineru(file_path):
    """
    Extracts content from PDF using MinerU's CLI ('magic-pdf').
    This avoids internal API instability by using the public CLI.
    Returns markdown content or None if failed.
    """
    
    # 1. Check if magic-pdf is available in PATH
    try:
        subprocess.run(["magic-pdf", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    except FileNotFoundError:
        logger.warning("MinerU (magic-pdf) CLI not found. Falling back to basic extraction.")
        return extract_fallback(file_path)

    # 2. Prepare Temp Directory
    # magic-pdf creates a folder named after the pdf filename inside the output dir
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    # Sanitize basename for directory matching if needed, but magic-pdf handles it.
    
    unique_id = uuid.uuid4().hex
    temp_output_dir = os.path.join("/tmp", f"mineru_{unique_id}")
    os.makedirs(temp_output_dir, exist_ok=True)

    try:
        logger.info(f"MinerU: Processing {file_path} via CLI...")
        # 3. Run CLI Command
        # magic-pdf -p {file} -o {dir} -m auto
        cmd = [
            "magic-pdf", 
            "-p", file_path, 
            "-o", temp_output_dir,
            "-m", "auto"
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode != 0:
            logger.error(f"MinerU CLI Failed: {result.stderr}")
            return extract_fallback(file_path)

        # 4. Find Output File
        # Structure: output_dir / base_name / base_name.md
        # We need to account for potential name sanitization by magic-pdf, so we glob.
        expected_subdir = os.path.join(temp_output_dir, "auto") # magic-pdf 1.x might put it in 'auto' or direct.
        # Let's search recursively for .md files
        md_files = glob.glob(os.path.join(temp_output_dir, "**", "*.md"), recursive=True)
        
        if not md_files:
            logger.warning(f"MinerU finished but no .md file found in {temp_output_dir}. Fallback.")
            return extract_fallback(file_path)
            
        # Pick the largest MD file (likely the content) or the one matching name
        main_md_file = max(md_files, key=os.path.getsize)
        
        with open(main_md_file, "r", encoding="utf-8") as f:
            content = f.read()
            
        logger.info(f"MinerU: Successfully extracted {len(content)} chars.")
        return content

    except Exception as e:
        logger.error(f"MinerU Extraction Error: {e}")
        return extract_fallback(file_path)
    finally:
        # Cleanup
        if os.path.exists(temp_output_dir):
            shutil.rmtree(temp_output_dir, ignore_errors=True)

def extract_fallback(file_path):
    """Basic extraction using PyMuPDF (fitz)"""
    try:
        doc = fitz.open(file_path)
        text_content = ""
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text_content += page.get_text()
        doc.close()
        return text_content
    except Exception as e:
        logger.error(f"PyMuPDF Fallback Failed: {e}")
        return None
