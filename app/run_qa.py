import os
import re
from PIL import Image
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from database import get_db_connection, create_fulltext_index, create_vector_index

# LCEL Imports
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from config import Config
from config import Config
from logger import setup_logger
from router import get_route

logger = setup_logger(__name__)

# 1. Connect to Neo4j
# 1. Connect to Neo4j
# 1. Lazy Connection Logic
_GRAPH = None

def get_graph():
    """Lazily connects to Neo4j to prevent import-time crashes."""
    global _GRAPH
    if _GRAPH is not None:
        return _GRAPH
    
    try:
        logger.info("Initializing Neo4j Connection...")
        _GRAPH = get_db_connection()
        
        # Create Indices on first connect
        create_vector_index(_GRAPH, dimensions=Config.EMBEDDING_DIMENSION) 
        from database import create_text_vector_index
        create_text_vector_index(_GRAPH, dimensions=3072)
        create_fulltext_index(_GRAPH)
        
        logger.info("✅ Neo4j Connection & Indices Ready.")
        return _GRAPH
    except Exception as e:
        logger.error(f"Neo4j Connection Failed: {e}")
        # Return None or raise? Raising is better to fail gracefully per request
        raise e

# 2. Initialize Models
embeddings = OpenAIEmbeddings(
     model=Config.OPENAI_EMBEDDING_MODEL, 
     openai_api_base=Config.OPENAI_BASE_URL,
     openai_api_key=Config.OPENAI_API_KEY
)

# Global Cache for Cross-Encoder
_CROSS_ENCODER_MODEL = None

def initialize_reranker():
    """Preloads the reranker model."""
    global _CROSS_ENCODER_MODEL
    method = Config.RERANKER_METHOD
    if method == "cross-encoder" and _CROSS_ENCODER_MODEL is None:
        try:
            from sentence_transformers import CrossEncoder
            logger.info("Pre-loading Cross-Encoder model...")
            _CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            logger.info("Cross-Encoder model loaded!")
        except Exception as e:
            logger.error(f"Failed to preload Cross-Encoder: {e}")

def extract_entities(llm, question: str) -> list:
    """Uses LLM to find the most important entities/keywords."""
    prompt = f"""
    Extract the 2-3 most important entities or keywords from this question for a database search.
    Return ONLY a comma-separated list of terms. NO explanation.

    Question: {question}
    """
    logger.info(f"Asking LLM to extract entities from: {question}")
    response = llm.invoke(prompt).content
    terms = [t.strip() for t in response.split(',') if t.strip()]
    logger.info(f"Extracted search terms: {terms}")
    return terms

def retrieve_graph_context(graph, llm, question: str, limit: int = 15) -> str:
    """Smartly gets relevant entities using Fulltext Search + LLM extraction."""
    create_fulltext_index(graph)

    terms = extract_entities(llm, question)
    if not terms:
        return ""

    # Lucene Query Construction
    lucene_query = " OR ".join([f"{term}~" for term in terms])
    
    # Optimized Query: Limits expansion to avoid retrieving too much noise
    cypher_query = """
    CALL db.index.fulltext.queryNodes("entity_id_index", $query, {limit: 5})
    YIELD node, score
    WITH node
    MATCH (node)-[r]-(neighbor)
    WHERE NOT type(r) IN ['MENTIONS']  // Exclude meta-rels if any
    RETURN node.id + ' --[' + type(r) + ']-> ' + neighbor.id AS output
    LIMIT 30
    """
    
    try:
        logger.info(f"Running Cypher Query: {lucene_query}")
        results = graph.query(cypher_query, {"query": lucene_query})
        logger.info(f"Graph Query returned {len(results)} rows.")
        return "\n".join([row['output'] for row in results])
    except Exception as e:
        logger.error(f"Graph search failed: {e}")
        return ""

def vector_retrieve(graph, embeddings, question, k=10, min_score=0.5, route="fast_fact"):
    """Gets relevant text chunks using Vector Similarity. Boosts Vision chunks if Visual intent."""
    q_embedding = embeddings.embed_query(question)
    
    # Boost Visual Chunks if route is visual
    visual_boost = 0.2 if route == "visual_layout" else 0.0
    
    result = graph.query("""
        CALL db.index.vector.queryNodes('text_vector_index', $k, $embedding)
        YIELD node, score
        WHERE score >= $min_score
        
        // --- Context Window Retrieval (Prev + Curr + Next) ---
        OPTIONAL MATCH (prev)-[:NEXT]->(node)
        OPTIONAL MATCH (node)-[:NEXT]->(next)
        
        WITH node, score, prev, next
        WITH node, score, 
             coalesce(prev.text, '') + '\n--[Prev Chunk]--\n' + node.text + '\n--[Next Chunk]--\n' + coalesce(next.text, '') as full_context
        
        // Boost score for sorting if Visual Intent and Node is Vision
        WITH node, score, full_context,
             (score + CASE WHEN node.modality = 'vision' OR node.modality = 'hybrid_vision' THEN $boost ELSE 0 END) as final_score

        RETURN full_context AS text, node.source AS source, node.page AS page, node.image_path AS image_path, final_score as score
        ORDER BY final_score DESC
    """, {"embedding": q_embedding, "k": k, "min_score": min_score, "boost": visual_boost})
    
    return result

def create_chunk_fulltext_index(graph):
    try:
        graph.query("""
            CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS 
            FOR (n:Chunk) ON EACH [n.text]
        """)
    except Exception as e:
        logger.error(f"Could not create chunk fulltext index: {e}")

def keyword_retrieve(graph, question, k=5):
    """Retrieves chunks using Keyword Search."""
    # Saniitize input: remove special characters that break Lucene
    import re
    clean_q = re.sub(r'[^a-zA-Z0-9\s]', '', question)
    terms = clean_q.split()
    # Simple formatting: t~ for fuzzy, joined by AND. 
    # Must have enough terms or it becomes too restrictive/empty.
    if not terms:
        return []
        
    lucene_query = " AND ".join([f"{t}~" for t in terms if len(t) > 2])
    
    if not lucene_query:
        return []
        
    logger.info(f"Keyword Search Query: {lucene_query}")
    
    query = """
    CALL db.index.fulltext.queryNodes("chunk_text_index", $query, {limit: $k})
    YIELD node, score
    RETURN node.text as text, node.source as source, node.page as page, node.image_path as image_path, score
    """
    
    try:
        results = graph.query(query, {"query": lucene_query, "k": k})
        return results
    except Exception as e:
        logger.error(f"Keyword search failed: {e}")
        return []

def reciprocal_rank_fusion(results_lists, k=60):
    fused_scores = {}
    doc_map = {}
    
    for r_list in results_lists:
        for rank, doc in enumerate(r_list):
            doc_text = doc['text']
            doc_map[doc_text] = doc 
            if doc_text not in fused_scores: fused_scores[doc_text] = 0.0
            fused_scores[doc_text] += 1.0 / (k + rank + 1)
            
    reranked_results = []
    for doc_text, score in fused_scores.items():
        doc = doc_map[doc_text]
        doc['rrf_score'] = score
        reranked_results.append(doc)
        
    reranked_results.sort(key=lambda x: x['rrf_score'], reverse=True)
    return reranked_results

def hybrid_context(graph, embeddings, question, llm_model, route="fast_fact"):
    """Combines Graph, Vector, and Keyword context. Adapts to Route."""
    create_fulltext_index(graph)
    create_chunk_fulltext_index(graph)
    
    # 1. GRAPH SEARCH (Boosted if deep_reasoning)
    graph_limit = 30 if route == "deep_reasoning" else 15
    graph_ctx = retrieve_graph_context(graph, llm_model, question, limit=graph_limit)

    # 2. HYBRID SEARCH
    keyword_ctx = keyword_retrieve(graph, question, k=5)
    
    # Vector Search (Multi-Query)
    queries_to_run = [question]
    # Only multi-query if NOT visual (visual needs precise single query usually)
    if route != "visual_layout":
        try:
            if len(question) > 10 and llm_model:
                 alt_prompt = f"Generate 2 alternative search queries for: '{question}'. Return only comma-separated strings."
                 alt_resp = llm_model.invoke(alt_prompt).content
                 alts = [q.strip() for q in alt_resp.split(',') if q.strip()]
                 queries_to_run.extend(alts[:2])
        except Exception as e:
            logger.warning(f"Multi-query generation failed: {e}")

    vector_results_map = {}
    for q in queries_to_run:
        # Pass route to vector_retrieve for boosting
        res = vector_retrieve(graph, embeddings, q, k=10, min_score=0.50, route=route)
        for r in res:
            vector_results_map[r['text']] = r 
            
    vector_ctx = list(vector_results_map.values())
    vector_ctx.sort(key=lambda x: x.get('score', 0), reverse=True)
    
    combined_results = reciprocal_rank_fusion([keyword_ctx, vector_ctx])
    vector_ctx = combined_results

    # Re-rank
    if vector_ctx:
        # Separate images
        is_img_file = lambda r: r.get('source', '').lower().endswith(('.jpg', '.jpeg', '.png'))
        image_file_results = [r for r in vector_ctx if is_img_file(r)]
        text_results = [r for r in vector_ctx if not is_img_file(r)]
        
        # Merge back for reranking
        vector_ctx = text_results + image_file_results
        
        reranked = rerank_results(question, vector_ctx, top_k=5, method=Config.RERANKER_METHOD, llm_model=llm_model)
        vector_ctx = reranked

    context = "### GRAPH KNOWLEDGE BITS:\n"
    context += graph_ctx if graph_ctx else "No direct entity facts found.\n"
    context += "\n### RELEVANT TEXT CHUNKS:\n"
    
    seen_images = set()
    if vector_ctx:
        for row in vector_ctx:
            src = row.get('source', 'Unknown')
            pg = row.get('page', '?')
            if src and os.path.sep in str(src):
                src = str(src).split(os.path.sep)[-1]
            context += f"- {row['text']} [Source: {src}, Page: {pg}]\n"
            
            # Logic to deduplicate images
            img_p = row.get('image_path')
            if img_p and img_p not in seen_images:
                context += f" [IMAGE PATH: {img_p}]\n"
                seen_images.add(img_p)
            elif str(src).lower().endswith(('.jpg', '.jpeg', '.png', '.webp')) and src not in seen_images:
                context += f" [IMAGE PATH: {src}]\n"
                seen_images.add(src)
            if '[IMAGE' in row['text']:
                context += "  (👆 THIS IS CONTENT EXTRACTED FROM AN INFOGRAPHIC/IMAGE. TREAT AS RELIABLE DATA.)\n"
    else:
        context += "SYSTEM NOTE: No direct data matches found.\n"

    return context

# --- TRUST SCORE LOGIC ---
TRUST_CONFIG = {}
def load_trust_config():
    global TRUST_CONFIG
    import json
    try:
        if os.path.exists(Config.TRUST_CONFIG_FILE):
            with open(Config.TRUST_CONFIG_FILE, "r") as f:
                TRUST_CONFIG = json.load(f)
    except Exception as e:
        logger.warning(f"Error loading trust config: {e}")

def get_trust_multiplier(source_name):
    if not TRUST_CONFIG: load_trust_config()
    rules = TRUST_CONFIG.get("rules", [])
    default = TRUST_CONFIG.get("default_score", 0.5)
    source = str(source_name).lower()
    
    best_score = float(default)
    max_len = -1
    
    for rule in rules:
        pattern = rule.get("pattern", "").lower()
        if pattern and pattern in source:
            if len(pattern) > max_len:
                max_len = len(pattern)
                best_score = float(rule.get("score", 1.0))
    return best_score

def rerank_results(question, results, top_k=3, method="llm", llm_model=None):
    if not results: return []
    
    load_trust_config()
    
    if method == "llm": return _rerank_with_llm(question, results, top_k, llm_model)
    elif method == "cohere": return _rerank_with_cohere(question, results, top_k)
    elif method == "cross-encoder": return _rerank_with_cross_encoder(question, results, top_k)
    else: return _rerank_with_llm(question, results, top_k, llm_model)

def _rerank_with_llm(question, results, top_k=3, llm_model=None):
    rerank_prompt = f"""You are a relevance scoring system. Score from 0-10.
    Question: {question}
    Respond with ONLY a number (0-10) for each passage.
    """
    scored_results = []
    for idx, result in enumerate(results):
        passage = result['text'][:500]
        score_prompt = f"{rerank_prompt}\nPassage {idx+1}: {passage}\n\nRelevance score:"
        try:
            response = llm_model.invoke(score_prompt).content.strip()
            relevance_score = float(re.search(r'\d+(\.\d+)?', response).group())
            base_score = (relevance_score / 10.0) * 0.7 + result.get('score', 0.5) * 0.3
            trust = get_trust_multiplier(result.get('source', ''))
            final_score = base_score * trust
            scored_results.append({**result, 'combined_score': final_score})
        except Exception:
            scored_results.append({**result, 'combined_score': result.get('score', 0.5)})
            
    scored_results.sort(key=lambda x: x['combined_score'], reverse=True)
    return scored_results[:top_k]

def _rerank_with_cohere(question, results, top_k=3):
    # Implementation similar to original but logging errors
    return results[:top_k] # Placeholder if no key

def _rerank_with_cross_encoder(question, results, top_k=3):
    try:
        global _CROSS_ENCODER_MODEL
        if _CROSS_ENCODER_MODEL is None:
            initialize_reranker()
            
        model = _CROSS_ENCODER_MODEL
        if not model: return results[:top_k]
        
        pairs = [[question, r['text'][:512]] for r in results]
        scores = model.predict(pairs)
        
        scored_results = []
        for idx, (result, ce_score) in enumerate(zip(results, scores)):
            base_score = ce_score * 0.7 + result.get('score', 0.5) * 0.3
            trust = get_trust_multiplier(result.get('source', ''))
            final_score = base_score * trust
            scored_results.append({**result, 'combined_score': float(final_score)})
            
        scored_results.sort(key=lambda x: x['combined_score'], reverse=True)
        return scored_results[:top_k]
    except Exception as e:
        logger.error(f"Cross-encoder reranking failed: {e}")
        return results[:top_k]

def answer(question, history="", temperature=0.3):
    """Final QA function using LCEL."""
    logger.info(f"Thinking about: {question}")
    
    dynamic_llm = ChatOpenAI(
        api_key=Config.OPENAI_API_KEY,
        base_url=Config.OPENAI_BASE_URL,
        model=Config.OPENAI_MODEL,
        temperature=temperature
    )
    
    standalone_question = question
    if history:
        condense_template = "Given history: {history}. Rephrase follow-up: {question} to standalone."
        condense_prompt = ChatPromptTemplate.from_template(condense_template)
        standalone_question = dynamic_llm.invoke(condense_prompt.format(history=history, question=question)).content
        logger.info(f"Rewritten: {standalone_question}")

    # --- ROUTER STEP ---
    route = get_route(standalone_question)
    logger.info(f"🚀 Query Route: {route}")

    # Lazy Connect
    try:
        graph = get_graph()
    except Exception as e:
        logger.error(f"Cannot connect to DB: {e}")
        return {"result": "⚠️ System Initializing... Please wait 10 seconds and try again.", "context": ""}

    context = hybrid_context(graph, embeddings, standalone_question, llm_model=dynamic_llm, route=route)
    
    template = """You are an intelligent Thai AI assistant (Hybrid RAG).
Answer based ONLY on context: {context}
History: {history}
Question: {question}

Route Detected: {route}

Rules:
- ANSWER IN THAI LANGUAGE ONLY (Respond properly with 'ครับ' or 'ค่ะ').
- If 'Visual' intent, describe the table/chart details clearly.
- If 'Deep Reasoning', explain the 'Why' and 'How'.
- Cite the source page (e.g. [Page 5]).
- Be polite and professional.
"""
    prompt = ChatPromptTemplate.from_template(template)
    final_chain = (prompt | dynamic_llm | StrOutputParser())
    
    response = final_chain.invoke({
        "history": history,
        "context": context,
        "question": standalone_question,
        "route": route
    })
    
    return {"result": response, "context": context}

if __name__ == "__main__":
    print("\n💬 Hybrid RAG Chatbot Initialized. Type 'exit' to quit.\n")
    history_str = ""
    while True:
        q = input("User: ")
        if q.lower() in ['exit', 'quit']: break
        if not q.strip(): continue
        output = answer(q, history=history_str)
        print(f"Bot: {output['result']}\n")
        history_str += f"User: {q}\nBot: {output['result']}\n"
