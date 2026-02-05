
import logging
from typing import List, Dict, Union
import torch

# Configure logger
logger = logging.getLogger("bertscore_eval")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def evaluate_from_csv(input_csv: str, output_csv: str, model_type: str = "xlm-roberta-base"):
    """Reads Q&A from CSV, gets chatbot answers, and calculates scores."""
    import pandas as pd
    import sys
    import os
    
    # Add parent dir and app dir to path
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))
    
    try:
        from run_qa import answer
    except ImportError as e:
        logger.error(f"Could not import run_qa: {e}")
        return


    logger.info(f"Reading input CSV: {input_csv}")
    try:
        df = pd.read_csv(input_csv)
    except Exception as e:
        logger.error(f"Failed to read CSV: {e}")
        return

    if 'Question' not in df.columns or 'Ground Truth' not in df.columns:
        logger.error("CSV must contain 'Question' and 'Ground Truth' columns.")
        return

    results = []
    logger.info(f"Evaluating {len(df)} samples using model: {model_type}...")

    for i, (_, row) in enumerate(df.iterrows()):
        question = str(row['Question'])
        reference = str(row['Ground Truth'])
        
        logger.info(f"Processing ({i+1}/{len(df)}): {question}")
        
        # Get Chatbot Response
        try:
            resp = answer(question)
            prediction = resp['result']
        except Exception as e:
            logger.error(f"Chatbot failed on q='{question}': {e}")
            prediction = "ERROR"

        # Evaluate Single Pair
        scores = evaluate_thai_bertscore([prediction], [reference], model_type=model_type, verbose=False)
        
        results.append({
            "Question": question,
            "Ground Truth": reference,
            "Chatbot Answer": prediction,
            "Precision": scores['precision'],
            "Recall": scores['recall'],
            "F1 Score": scores['f1']
        })

    # Save Results
    result_df = pd.DataFrame(results)
    result_df.to_csv(output_csv, index=False)
    logger.info(f"Saved evaluation results to: {output_csv}")
    
    # Summary
    avg_f1 = result_df['F1 Score'].mean()
    logger.info(f"Average F1 Score: {avg_f1:.4f}")

def evaluate_thai_bertscore(
    predictions: List[str], 
    references: List[str], 
    model_type: str = "xlm-roberta-base",
    device: str = None,
    batch_size: int = 64,
    verbose: bool = True
) -> Dict[str, float]:
    """
    Evaluate similarity between Thai predictions and references using BERTScore.
    """
    try:
        from bert_score import score
    except ImportError:
        logger.error("bert-score is not installed. Please run: pip install bert-score")
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    if not device:
        if torch.cuda.is_available():
            device = "cuda"
        else:
            if verbose: logger.warning("CUDA is not available! Using CPU.")
            device = "cpu"
    
    if verbose and device == "cuda":
        logger.info(f"CUDA Device: {torch.cuda.get_device_name(0)}")
    
    if verbose:
        logger.info(f"Using device: {device}")
        logger.info(f"Computing BERTScore...")
    
    P, R, F1 = score(
        predictions, 
        references, 
        model_type=model_type, 
        lang="th", 
        verbose=verbose,
        device=device,
        batch_size=batch_size
    )
    
    avg_p = P.mean().item()
    avg_r = R.mean().item()
    avg_f1 = F1.mean().item()
    
    if verbose:
        logger.info(f"Results: Precision={avg_p:.4f}, Recall={avg_r:.4f}, F1={avg_f1:.4f}")
    
    return {
        "precision": avg_p,
        "recall": avg_r,
        "f1": avg_f1
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Evaluate RAG Chatbot using BERTScore")
    parser.add_argument("--input", type=str, help="Path to input CSV (cols: Question, Ground Truth)")
    parser.add_argument("--output", type=str, default="Eva_data/evaluation_results.csv", help="Path to output CSV")
    parser.add_argument("--model", type=str, default="xlm-roberta-base", help="Validation model (e.g. bert-base-multilingual-cased)")
    args = parser.parse_args()

    if args.input:
        evaluate_from_csv(args.input, args.output, args.model)
    else:
        # Test cases
        print("--- Testing Thai BERTScore (Dummy Data) ---")
        preds = ["บริษัทมีกรรมการทั้งหมด 15 คน"]
        refs = ["คณะกรรมการของบริษัทมีจำนวนรวมทั้งสิ้น 15 ท่าน"]
        results = evaluate_thai_bertscore(preds, refs, model_type=args.model)
        print(f"F1 Score:  {results['f1']:.4f}")
