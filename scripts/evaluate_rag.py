import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from bert_score import score
import pandas as pd
import numpy as np
import argparse
import sys
import os
import logging

# ---------------------------------------------------------
# Configuration & Setup
# ---------------------------------------------------------
# Configure logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("rag_eval")

NLI_MODEL_NAME = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
SEMANTIC_MODEL_NAME = "microsoft/mdeberta-v3-base"

# Add parent path to find 'run_qa' module if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../app'))) # Try deeper just in case

# Global Models (Lazy Load)
_nli_tokenizer = None
_nli_model = None

def load_nli_model():
    global _nli_tokenizer, _nli_model
    if _nli_model is None:
        logger.info(f"Loading NLI Model: {NLI_MODEL_NAME}...")
        try:
            _nli_tokenizer = AutoTokenizer.from_pretrained(NLI_MODEL_NAME)
            _nli_model = AutoModelForSequenceClassification.from_pretrained(NLI_MODEL_NAME)
            if torch.cuda.is_available():
                _nli_model = _nli_model.cuda()
        except Exception as e:
            logger.error(f"Error loading NLI model: {e}")
            sys.exit(1)

# ---------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------

def get_nli_score(premise, hypothesis):
    """
    Checks Faithfulness: Does the Context support the Answer?
    Returns: 1.0 (Entailment) or 0.0 (Neutral/Contradiction)
    """
    load_nli_model()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    
    # Pre-processing: Strip common RAG citation patterns from hypothesis for better NLI accuracy
    import re
    clean_hypothesis = re.sub(r'\[Source:.*?\]', '', hypothesis)
    clean_hypothesis = re.sub(r'\[Page:?\s?\d+\]', '', clean_hypothesis)
    clean_hypothesis = re.sub(r'\(Image:.*?\)', '', clean_hypothesis)
    clean_hypothesis = clean_hypothesis.strip()

    inputs = _nli_tokenizer(premise, clean_hypothesis, truncation=True, return_tensors="pt").to(device)
    
    with torch.no_grad():
        outputs = _nli_model(**inputs)
        probs = torch.softmax(outputs.logits, dim=1)[0]
    
    entailment_score = probs[0].item()
    neutral_score = probs[1].item()
    contradiction_score = probs[2].item()
    
    # Prediction: 0=Entailment, 1=Neutral, 2=Contradiction
    prediction = torch.argmax(probs).item()
    
    return 1.0 if prediction == 0 else 0.0, {
        "entailment": entailment_score,
        "neutral": neutral_score,
        "contradiction": contradiction_score
    }

def get_semantic_scores(candidate, reference):
    """
    Checks Quality & Completeness: How close is Answer to Ground Truth?
    Returns: Precision, Recall, F1
    """
    # Note: use_fast_tokenizer=False for mDeBERTa compatibility
    try:
        P, R, F1 = score([candidate], [reference], model_type=SEMANTIC_MODEL_NAME, lang="th", verbose=False, use_fast_tokenizer=False)
    except TypeError:
        # Fallback
        P, R, F1 = score([candidate], [reference], model_type=SEMANTIC_MODEL_NAME, lang="th", verbose=False)
        
    return P.mean().item(), R.mean().item(), F1.mean().item()

# ---------------------------------------------------------
# Evaluation Logic
# ---------------------------------------------------------
def clean_for_eval(text):
    """Strips citations and conversational padding for cleaner comparison."""
    import re
    if not isinstance(text, str): return ""
    # Strip common citation patterns
    text = re.sub(r'\[Source:.*?\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\[Page:?\s?\d+\]', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\(Image:.*?\)', '', text, flags=re.IGNORECASE)
    # Strip Thai politeness/particles
    text = re.sub(r'ครับ|ค่ะ|นะ|คะ|คับ', '', text)
    return text.strip()

def evaluate_from_csv(input_csv: str, output_csv: str):
    logger.info(f"Reading input CSV: {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        return

    # Check required columns
    required_cols = ['Question', 'Ground Truth'] 
    for col in required_cols:
        if col not in df.columns:
            logger.error(f"CSV must contain '{col}' column.")
            return

    # Try to import chatbot function
    try:
        from run_qa import answer as get_chatbot_answer
        chatbot_available = True
    except ImportError as e:
        logger.warning(f"Could not import 'run_qa': {e}. Answer generation disabled.")
        if 'Answer' not in df.columns:
            logger.error("No 'Answer' column and cannot load chatbot. Aborting.")
            return
        chatbot_available = False

    results = []
    logger.info(f"Evaluating {len(df)} samples...")

    for i, row in df.iterrows():
        question = str(row['Question'])
        ground_truth = str(row['Ground Truth'])
        
        # 1. Evidence Handling (for NLI Faithfulness)
        context_evidence = str(row['Context']) if 'Context' in df.columns and pd.notna(row['Context']) else \
                          (str(row['source']) if 'source' in df.columns and pd.notna(row['source']) else ground_truth)
        
        # 2. Get Answer
        if 'Answer' in df.columns and pd.notna(row['Answer']):
            answer_text = str(row['Answer'])
        elif chatbot_available:
            logger.info(f"Generating answer for: {question}")
            try:
                resp = get_chatbot_answer(question)
                answer_text = resp['result'] if isinstance(resp, dict) else str(resp)
            except Exception as e:
                logger.error(f"Chatbot failed: {e}")
                answer_text = "ERROR"
        else:
            continue

        # 3. Evaluate Metrics
        clean_answer = clean_for_eval(answer_text)
        clean_gt = clean_for_eval(ground_truth)

        # Faithfulness: Does Evidence support Answer?
        faith_score, nli_details = get_nli_score(context_evidence, answer_text)
        
        # Quality: Does Answer match Ground Truth?
        prec, rec, f1 = get_semantic_scores(clean_answer, clean_gt)
        
        # Citation Check: Does Answer have citations?
        import re
        cite_patterns = [
            r'\[Page:?\s?\d+\]',
            r'\[\d+\]',
            r'\(Image:.*?\)',
            r'\(รูปภาพ:.*?\)',
            r'หน้า\s?\d+'
        ]
        has_cite = any(re.search(p, answer_text, re.IGNORECASE) for p in cite_patterns)
        cite_score = 1.0 if has_cite else 0.0
        
        # 4. Final Verdict
        # FAITHFULNESS is mandatory (1.0)
        # SEMANTIC matches at 0.5+ F1 (Conversational full-sentence vs short GT)
        # CITATION is expected (1.0)
        status = "PASSED" if (faith_score == 1.0 and f1 >= 0.5 and cite_score == 1.0) else "FAILED"
        
        results.append({
            "Question": question,
            "Ground Truth": ground_truth,
            "Chatbot Answer": answer_text,
            "Cleaned Answer": clean_answer,
            "Status": status,
            "Faithfulness (NLI)": faith_score,
            "Semantic F1": f1,
            "Semantic Recall": rec,
            "Citation Score": cite_score,
            "NLI Entailment Prob": nli_details['entailment']
        })
        
        if (i+1) % 5 == 0:
            logger.info(f"Processed {i+1}/{len(df)} cases.")

    # Save Results
    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False)
    logger.info(f"Saved results to: {output_csv}")
    
    # Summary Statistics
    pass_rate = (result_df['Status'] == 'PASSED').mean() * 100
    avg_f1 = result_df['Semantic F1'].mean()
    avg_faith = result_df['Faithfulness (NLI)'].mean()
    avg_cite = result_df['Citation Score'].mean()
    
    print("\n" + "="*40)
    print("       EVALUATION SUMMARY")
    print("="*40)
    print(f"Total Samples:    {len(df)}")
    print(f"Overall Pass Rate: {pass_rate:.1f}%")
    print("-" * 40)
    print(f"Avg Faithfulness: {avg_faith:.4f}")
    print(f"Avg Semantic F1:  {avg_f1:.4f}")
    print(f"Avg Citation:     {avg_cite:.4f}")
    print("="*40 + "\n")
# ---------------------------------------------------------
# Main Test Block (Demo)
# ---------------------------------------------------------
def run_demo_tests():
    context = """EGAT เก็บข้อมูลทางการเงิน8ประเภท ได้แก่ หมายเลขของบัตรเครดิตและบัตรเดบิต ,วิธีการชำระเงิน (เช่น เงินสด หรือ บัตรเครดิต) ,ข้อมูลพร้อมเพย์ ,หมายเลขบัญชีและประเภทของบัญชีธนาคาร ,ประวัติทางบัญชีธนาคาร ,รายการเงินฝากถอนในบัญชี ,รายละเอียดการจ่ายเงิน และ ข้อมูลการสมัครใช้ผลิตภัณฑ์ สินค้าและบริการ (ผ่านแอปพลิเคชัน)"""

    ground_truth = """EGAT เก็บข้อมูลทางการเงินประเภทต่าง ๆ ดังนี้ครับ:
1. หมายเลขของบัตรเครดิตและบัตรเดบิต
2. วิธีการชำระเงิน (เช่น เงินสด หรือ บัตรเครดิต)
3. ข้อมูลพร้อมเพย์
4. หมายเลขบัญชีและประเภทของบัญชีธนาคาร
5. ประวัติทางบัญชีธนาคาร
6. รายการเงินฝากถอนในบัญชี
7. รายละเอียดการจ่ายเงิน
8. ข้อมูลการสมัครใช้ผลิตภัณฑ์ สินค้าและบริการ (ผ่านแอปพลิเคชัน)"""

    # False Positive (Hallucination)
    ans_fp = ground_truth + "\n9. ประวัติทะเบียนบ้านและที่อยู่\n10. คะแนนเครดิตบูโร"
    # False Negative (Incomplete)
    ans_fn = """EGAT เก็บข้อมูลทางการเงินประเภทต่าง ๆ ดังนี้ครับ:
1. หมายเลขของบัตรเครดิตและบัตรเดบิต
2. วิธีการชำระเงิน
3. ข้อมูลพร้อมเพย์"""
    # Contradiction (Lie)
    ans_contra = "EGAT ไม่เก็บข้อมูลบัตรเครดิตเลย"

    cases = [
        {"name": "Correct Answer", "context": context, "source": "EGAT_Doc.pdf", "answer": ground_truth + "\n[Source: EGAT_Doc.pdf]"},
        {"name": "No Citation", "context": context, "source": "EGAT_Doc.pdf", "answer": ground_truth}, 
        {"name": "Hallucination", "context": context, "source": "EGAT_Doc.pdf", "answer": ans_fp},
        {"name": "Incomplete", "context": context, "source": "EGAT_Doc.pdf", "answer": ans_fn},
    ]

    print("\n" + "="*60)
    print("       ALL-IN-ONE RAG EVALUATION REPORT (DEMO)")
    print("="*60)
    
    for i, case in enumerate(cases):
        print(f"\n--- Case {i+1}: {case['name']} ---")
        faith_score, nli_details = get_nli_score(case['context'], case['answer'])
        prec, rec, f1 = get_semantic_scores(case['answer'], ground_truth)
        
        # Citation Check
        clean_source = case['source'].lower().replace('.pdf', '')
        cite_score = 1.0 if clean_source in case['answer'].lower() else 0.0
        
        status = "PASSED" if (faith_score == 1.0 and f1 > 0.7 and rec > 0.8 and cite_score == 1.0) else "FAILED"
        
        print(f"Faithfulness (NLI):     {faith_score}  (Prob: {nli_details['entailment']:.4f})")
        print(f"Semantic Quality (F1):  {f1:.4f}")
        print(f"Completeness (Recall):  {rec:.4f}")
        print(f"Citation Score:         {cite_score}")
        print(f"STATUS:                 {status}")

# ---------------------------------------------------------
# Entry Point
# ---------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate RAG System (NLI + mDeBERTa)")
    parser.add_argument("--input", type=str, help="Path to input CSV (cols: Question, Ground Truth, [Context], [Answer])")
    parser.add_argument("--output", type=str, default="evaluation_results.csv", help="Path to output CSV")
    args = parser.parse_args()

    if args.input:
        evaluate_from_csv(args.input, args.output)
    else:
        run_demo_tests()
