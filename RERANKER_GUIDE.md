# 🔄 Re-Ranking Configuration Guide

The system supports **3 different re-ranking methods** to improve retrieval quality. Choose based on your needs:

## **Available Methods:**

### **1. LLM-based (Default)** ✅
- **Method**: `llm`
- **Pros**: 
  - No extra setup needed
  - Best semantic understanding
  - Works with existing OpenAI API
- **Cons**: 
  - Slower (makes LLM calls for each result)
  - More expensive (uses GPT-4o tokens)
- **Best for**: High-quality answers, complex questions

### **2. Cohere Rerank** 🚀
- **Method**: `cohere`
- **Pros**:
  - Very fast (dedicated reranking model)
  - Excellent multilingual support
  - Cost-effective
- **Cons**:
  - Requires Cohere API key
  - External API dependency
- **Best for**: Production systems, high-volume queries

**Setup:**
```bash
pip install cohere
```

Add to `.env`:
```env
COHERE_API_KEY=your_cohere_api_key_here
RERANKER_METHOD=cohere
```

### **3. Cross-Encoder (Local)** 💻
- **Method**: `cross-encoder`
- **Pros**:
  - Runs locally (no API calls)
  - Fast after model loads
  - Free (no API costs)
- **Cons**:
  - Requires model download (~100MB)
  - Uses CPU/GPU resources
  - Slightly less accurate than LLM
- **Best for**: Privacy-sensitive applications, offline use

**Setup:**
```bash
pip install sentence-transformers
```

Add to `.env`:
```env
RERANKER_METHOD=cross-encoder
```

## **How to Configure:**

### **Option 1: Environment Variable**
Add to your `.env` file:
```env
RERANKER_METHOD=llm          # or "cohere" or "cross-encoder"
```

### **Option 2: Default (No Config)**
If not specified, defaults to `llm`.

## **Performance Comparison:**

| Method | Speed | Accuracy | Cost | Setup |
|--------|-------|----------|------|-------|
| LLM | ⭐⭐ | ⭐⭐⭐⭐⭐ | $$$ | Easy |
| Cohere | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | $ | Medium |
| Cross-Encoder | ⭐⭐⭐⭐ | ⭐⭐⭐ | Free | Medium |

## **Tuning Parameters:**

In `run_qa.py`, you can adjust:

```python
# Number of results to keep after re-ranking
vector_ctx = rerank_results(question, vector_ctx, top_k=3)  # Change 3 to 2 or 5
```

## **Troubleshooting:**

**Cohere not working?**
- Check API key is valid
- Ensure `cohere` library is installed
- System will fall back to LLM automatically

**Cross-encoder slow on first run?**
- Model downloads on first use (~100MB)
- Subsequent runs are fast (model cached)

**Want to switch methods?**
- Just change `RERANKER_METHOD` in `.env`
- Restart the API server (`python api.py`)

## **Recommendation:**

- **Development**: Use `llm` (default, no setup)
- **Production**: Use `cohere` (fast, reliable)
- **Privacy/Offline**: Use `cross-encoder` (local, free)
