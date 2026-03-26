
import os
import sys
import pandas as pd
import glob
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from pypdf import PdfReader
import logging

# Add app to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))
from config import Config

# Setup Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("qa_generator")

def generate_qa_from_text(text, llm, count=5):
    """Generates Q&A pairs from text using LLM."""
    if len(text) < 500:
        return []

    prompt_text = """
    You are an expert at creating exam questions from documents.
    Generate {count} pairs of Questions and Answers (Ground Truths) based strictly on the text below.
    
    Rules:
    1. Language: THAI only.
    2. Format: Return a CSV-like format: "Question"|"Answer"
    3. Questions should be specific (e.g., "What is the net profit in 2023?").
    4. Answers should be concise but complete.
    5. Do not number the output lines. Just Q|A.

    Text:
    {text}
    """
    
    prompt = ChatPromptTemplate.from_template(prompt_text)
    chain = prompt | llm | StrOutputParser()
    
    try:
        response = chain.invoke({"count": count, "text": text[:4000]}) # Limit text context
        lines = response.strip().split('\n')
        pairs = []
        for line in lines:
            if '|' in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    pairs.append((parts[0].strip(), parts[1].strip()))
        return pairs
    except Exception as e:
        logger.error(f"LLM Generation failed: {e}")
        return []

def main():
    # fix imports
    try:
        from config import Config
    except ImportError:
        # Fallback if app/config.py isn't found directly
        try:
            sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
            from app.config import Config
        except Exception as e:
            logger.error(f"Cannot import Config: {e}")
            return

    target_files = glob.glob("data/*.PDF") + glob.glob("data/*.pdf")
    if not target_files:
        logger.error("No PDF files found in data/")
        return

    llm = ChatOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        model=Config.OPENAI_MODEL,
        temperature=0.7
    )

    all_qa = []
    output_path = "Eva_data/test_qa.csv"
    
    # Load existing if any to append or check count
    # But user asked to MAKE 100 questions, implying overwriting or filling up.
    # We will overwrite to ensure clean slate or append? Let's overwrite for now or check.
    
    target_count = 30
    logger.info(f"Target: Generating {target_count} QA pairs from {len(target_files)} files...")

    for pdf_path in target_files:
        if len(all_qa) >= target_count:
            break
            
        logger.info(f"Processing: {pdf_path}")
        try:
            reader = PdfReader(pdf_path)
            num_pages = len(reader.pages)
            
            # Skip every few pages to get variety if many pages
            step = max(1, num_pages // 20) 
            
            for i in range(0, num_pages, step):
                if len(all_qa) >= target_count:
                    break
                
                page = reader.pages[i]
                text = page.extract_text()
                
                logger.info(f"  Generating from Page {i+1}...")
                pairs = generate_qa_from_text(text, llm, count=5)
                
                for q, a in pairs:
                    # Clean quotes
                    q = q.replace('"', '').replace("'", "")
                    a = a.replace('"', '').replace("'", "")
                    all_qa.append({
                        "Question": q, 
                        "Ground Truth": a, 
                        "Context": text, # Store actual text for NLI evaluation
                        "source": os.path.basename(pdf_path)
                    })
                    logger.info(f"    + Q: {q}")
                
                logger.info(f"  Total collected: {len(all_qa)}")

        except Exception as e:
            logger.error(f"Failed to process {pdf_path}: {e}")

    df = pd.DataFrame(all_qa)
    if len(df) > target_count:
        df = df.head(target_count)
        
    df.to_csv(output_path, index=False)
    logger.info(f"✅ Generated {len(df)} QA pairs saved to {output_path}")

if __name__ == "__main__":
    main()
