
import os
import re
from PIL import Image
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from app.database import get_db_connection, create_fulltext_index, create_vector_index

# LCEL Imports
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from app.config import Config
from app.logger import setup_logger
from app.router import get_route

logger = setup_logger(__name__)

def preprocess_thai_query(query: str) -> str:
    """Tokenizes Thai text for better Lucene search."""
    try:
        # Detect if query contains Thai characters (Unicode range \u0E00-\u0E7F)
        if any('\u0E00' <= char <= '\u0E7F' for char in query):
            from pythainlp import word_tokenize
            tokens = word_tokenize(query, engine="newmm")
            return " ".join(tokens)
        return query
    except Exception as e:
        logger.warning(f"Thai tokenization failed: {e}")
        return query

# Lazy Neo4j Connection
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
        from app.database import create_text_vector_index
        create_text_vector_index(_GRAPH, dimensions=Config.EMBEDDING_DIMENSION)
        create_fulltext_index(_GRAPH)
        
        logger.info("✅ Neo4j Connection & Indices Ready.")
        return _GRAPH
    except Exception as e:
        logger.error(f"Neo4j Connection Failed: {e}")
        # Return None or raise? Raising is better to fail gracefully per request
        raise e

# 2. Lazy-load Embeddings (reads Config at call-time, not import-time)
_EMBEDDINGS = None

def get_embeddings():
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        logger.info(f"Loading embeddings model: {Config.OPENAI_EMBEDDING_MODEL} via {Config.OPENAI_EMBEDDING_BASE_URL}")
        _EMBEDDINGS = OpenAIEmbeddings(
            model=Config.OPENAI_EMBEDDING_MODEL,
            openai_api_base=Config.OPENAI_EMBEDDING_BASE_URL,
            openai_api_key=Config.OPENAI_EMBEDDING_API_KEY
        )
    return _EMBEDDINGS



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

def vector_retrieve(graph, embeddings, question, k=10, min_score=0.5, route="fast_fact", selected_sources=None):
    """Gets relevant text chunks using Vector Similarity. Boosts Vision chunks if Visual intent."""
    q_embedding = embeddings.embed_query(question)
    
    selected_sources = selected_sources or []
    
    # Visual boost: read from Config or default to 0.25
    try:
        visual_boost = float(getattr(__import__('app.config', fromlist=['Config']).Config, 'VISUAL_BOOST', 0.25))
    except Exception:
        visual_boost = 0.25

    result = graph.query("""
        CALL db.index.vector.queryNodes('text_vector_index', $k, $embedding)
        YIELD node, score
        WHERE score >= $min_score
        // Support source-level selection: allow passing filenames (endsWith) instead of exact match
        AND (size($selected_sources) = 0 OR any(s IN $selected_sources WHERE toString(node.source) ENDS WITH s))
        
        // --- Context Window Retrieval (Extended to +/- 2) ---
        // 1. Prev Chunks
        OPTIONAL MATCH (prev)-[:NEXT]->(node)
        OPTIONAL MATCH (prev2)-[:NEXT]->(prev)
        
        // 2. Next Chunks
        OPTIONAL MATCH (node)-[:NEXT]->(next)
        OPTIONAL MATCH (next)-[:NEXT]->(next2)
        
        WITH node, score, 
             coalesce(prev2.text + '\n', '') + coalesce(prev.text + '\n', '') + 
             node.text + 
             coalesce('\n' + next.text, '') + coalesce('\n' + next2.text, '') AS full_context,
             head([n_path IN [node.image_path, prev.image_path, next.image_path, prev2.image_path, next2.image_path] WHERE n_path IS NOT NULL AND n_path <> '' | n_path]) as best_image_path
        
        // Boost score for sorting if Visual Intent and Node is Vision
        WITH node, score, full_context, best_image_path,
             (score + CASE WHEN node.modality = 'vision' OR node.modality = 'hybrid_vision' THEN $boost ELSE 0 END) AS final_score

        RETURN full_context AS text, node.source AS source, node.page AS page, best_image_path AS image_path, final_score AS score
        ORDER BY final_score DESC
    """, {"embedding": q_embedding, "k": k, "min_score": min_score, "boost": visual_boost, "selected_sources": selected_sources})
    
    return result

def create_chunk_fulltext_index(graph):
    try:
        graph.query("""
            CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS 
            FOR (n:Chunk) ON EACH [n.text]
        """)
    except Exception as e:
        logger.error(f"Could not create chunk fulltext index: {e}")

def keyword_retrieve(graph, question, k=5, selected_sources=None):
    """Retrieves chunks using Keyword Search."""
    # Thai Text Preprocessing
    question = preprocess_thai_query(question)
    
    # Saniitize input: remove special characters that break Lucene
    import re
    # Sanitize input: remove Lucene special characters but KEEP Unicode/Thai
    clean_q = re.sub(r'[+\-&|!(){}\[\]^"~*?:\\/]', ' ', question)
    terms = clean_q.split()
    # Simple formatting: t~ for fuzzy, joined by AND. 
    # Must have enough terms or it becomes too restrictive/empty.
    if not terms:
        return []
        
    # Stricter Logic: Use AND for precision. If specific keywords are typed, we want ALL of them.
    # Vector Search handles semantic/fuzzy recall.
    boosted_terms = []
    # Identify car brands to boost during retrieval
    brands = ['xpeng', 'byd', 'tesla', 'audi', 'zeekr', 'deepal', 'bmw', 'mercedes', 'ora', 'geely', 'mg', 'hyundai']
    for t in terms:
        if len(t) <= 1: continue
        # Heavily boost brands to ensure they override generic terms like "battery" or "charging"
        if t.lower() in brands:
            boosted_terms.append(f"{t}^5")
        else:
            boosted_terms.append(f"{t}~")
    
    lucene_query = " OR ".join(boosted_terms)
    
    if not lucene_query:
        return []
        
    logger.info(f"Keyword Search Query (Strict): {lucene_query}")
    
    query = """
        CALL db.index.fulltext.queryNodes("chunk_text_index", $query, {limit: $k})
        YIELD node, score
        WHERE (size($selected_sources) = 0 OR any(s IN $selected_sources WHERE toString(node.source) ENDS WITH s))
        
        // --- Page-Level Retrieval: Get ALL chunks from the same page ---
        MATCH (page_chunk:Chunk)
        WHERE page_chunk.source = node.source 
          AND page_chunk.page = node.page
        WITH node, score, collect(page_chunk) as page_chunks
        
        // Sort by sequence
        UNWIND page_chunks as chunk
        WITH node, score, chunk
        ORDER BY chunk.seq
        
        // Concatenate
        WITH node, score, collect(chunk.text) as all_texts, 
             head([c IN collect(chunk) WHERE c.image_path IS NOT NULL AND c.image_path <> '' | c.image_path]) as found_image
        WITH node, score, reduce(s = '', text IN all_texts | s + '\\n' + text) as full_page_context, found_image
        
        RETURN full_page_context as text, node.source as source, node.page as page, found_image as image_path, score
        """
    
    try:
        selected_sources = selected_sources or []
        results = graph.query(query, {"query": lucene_query, "k": k, "selected_sources": selected_sources})
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

def hybrid_context(graph, embeddings, question: str, llm_model, route="fast_fact", selected_sources=None):
    """Combines Graph, Vector, and Keyword context. Adapts to Route."""
    selected_sources = selected_sources or []
    create_fulltext_index(graph)
    create_chunk_fulltext_index(graph)
    
    # Detect Brand-Only or short queries (Higher Recall needed)
    is_broad_query = len(question.strip().split()) <= 2 or any(b.lower() in question.lower() for b in ['xpeng', 'byd', 'tesla', 'audi', 'zeekr'])
    
    # 1. GRAPH SEARCH (Boosted if deep_reasoning or broad query)
    graph_limit = 40 if (route == "deep_reasoning" or is_broad_query) else 15
    graph_ctx = retrieve_graph_context(graph, llm_model, question, limit=graph_limit)

    # 2. HYBRID SEARCH
    k_res = 20 if is_broad_query else 15
    keyword_ctx = keyword_retrieve(graph, question, k=k_res, selected_sources=selected_sources)
    logger.info(f"📊 Keyword Retrieval: {len(keyword_ctx)} results")
    
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
        k_vec = 15 if is_broad_query else 10
        res = vector_retrieve(graph, embeddings, q, k=k_vec, min_score=0.50, route=route, selected_sources=selected_sources)
        for r in res:
            vector_results_map[r['text']] = r 
            
    vector_ctx = list(vector_results_map.values())
    vector_ctx.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info(f"📊 Vector Retrieval: {len(vector_ctx)} results")
    
    combined_results = reciprocal_rank_fusion([keyword_ctx, vector_ctx])
    vector_ctx = combined_results
    logger.info(f"📊 After RRF Fusion: {len(vector_ctx)} results")

    # Re-rank
    if vector_ctx:
        # Separate images
        is_img_file = lambda r: r.get('source', '').lower().endswith(('.jpg', '.jpeg', '.png'))
        image_file_results = [r for r in vector_ctx if is_img_file(r)]
        text_results = [r for r in vector_ctx if not is_img_file(r)]
        
        # Merge back for reranking
        vector_ctx = text_results + image_file_results
        
        reranked = rerank_results(question, vector_ctx, top_k=10, method=Config.RERANKER_METHOD, llm_model=llm_model)
        vector_ctx = reranked
        logger.info(f"📊 After Reranking (top_k=10): {len(vector_ctx)} results")
        if vector_ctx:
            logger.info(f"📄 First result preview: {vector_ctx[0]['text'][:300]}...")

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
            text = str(row['text'])
            # Clean HTML tags more aggressively (including encoded)
            text = str(text).replace('&lt;', '<').replace('&gt;', '>')
            text = re.sub(r'<[^>]+>', ' ', text)
            
            # --- FIX: Sanitize absolute paths in text content ---
            # If text contains [IMAGE PATH: /app/data/...] or similar, replace with /api/images/filename
            def replace_abs_path(match):
                full_path = match.group(1)
                filename = os.path.basename(full_path)
                return f"[IMAGE PATH: /api/images/{filename}]"
            
            text = re.sub(r'\[IMAGE PATH: (.*?)\]', replace_abs_path, text)
            # ----------------------------------------------------

            context += f"- {text} [Source: {src}, Page: {pg}]\n"
            
            # Logic to deduplicate images
            img_p = row.get('image_path')
            if img_p:
                if not img_p.startswith('/api/images/') and not img_p.startswith('http'):
                     # Ensure we don't double prepend if path includes subdir
                     # Assuming basic file serving pattern
                     filename = os.path.basename(img_p)
                     img_p = f"/api/images/{filename}"
                
                if img_p not in seen_images:
                    context += f" [IMAGE PATH: {img_p}]\n"
                    seen_images.add(img_p)
                    logger.info(f"Adding Image Path to Context: {img_p}")
            elif str(src).lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                # Fallback for image-only chunks if path is missing
                img_src = src
                if not img_src.startswith('/images/') and not img_src.startswith('http'):
                    img_src = f"/images/{img_src.lstrip('/')}"
                
                if img_src not in seen_images:
                    context += f" [IMAGE PATH: {img_src}]\n"
                    seen_images.add(img_src)
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
    """Rerank using Cohere API. Requires COHERE_API_KEY in env."""
    try:
        import cohere
        if not Config.COHERE_API_KEY:
            logger.warning("[Reranker] RERANKER_METHOD=cohere but COHERE_API_KEY is not set. Falling back to top-k slice.")
            return results[:top_k]
        co = cohere.Client(Config.COHERE_API_KEY)
        docs = [r['text'][:512] for r in results]
        response = co.rerank(query=question, documents=docs, top_n=top_k, model='rerank-multilingual-v3.0')
        reranked = []
        for hit in response.results:
            r = results[hit.index].copy()
            r['combined_score'] = hit.relevance_score
            reranked.append(r)
        return reranked
    except ImportError:
        logger.warning("[Reranker] cohere package not installed. pip install cohere")
        return results[:top_k]
    except Exception as e:
        logger.error(f"[Reranker] Cohere reranking failed: {e}")
        return results[:top_k]

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

def answer(question, history="", temperature=0.3, selected_sources=None):
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
        condense_template = """Given chat history and follow-up, rephrase to standalone question.
        IMPORTANT: Preserve any specific model numbers or names (e.g. 009, Atto 3, Model Y). DO NOT generalize "Zeekr 009" to just "Zeekr".
        Chat History: {history}
        Follow Up: {question}
        Standalone:"""
        condense_prompt = ChatPromptTemplate.from_template(condense_template)
        standalone_question = dynamic_llm.invoke(condense_prompt.format(history=history, question=question)).content
        logger.info(f"Rewritten: {standalone_question}")

    # --- ROUTER STEP ---
    route = get_route(standalone_question)
    logger.info(f"🚀 Query Route: {route}")

    # Lazy Connect with Retry Loop
    graph = None
    import time
    for attempt in range(3):
        try:
            graph = get_graph()
            if graph:
                logger.info(f"Connection Successful (Attempt {attempt+1})")
                break
        except Exception as e:
            logger.warning(f"Connection Failed (Attempt {attempt+1}): {e}")
            time.sleep(2)
    
    if not graph:
        return {"result": "⚠️ System Initializing... Please wait 5 seconds and try again.", "context": ""}

    context = hybrid_context(graph, get_embeddings(), standalone_question, llm_model=dynamic_llm, route=route, selected_sources=selected_sources)
    
    logger.debug(f"Retrieved context length: {len(context)} chars")
    
    
    # CRITICAL INSTRUCTION AT THE TOP:
    template = """You are an intelligent Thai AI assistant (Hybrid RAG).
    
    # 1. AMBIGUITY CHECK (Execute in Order):
    
    - RULE 1 [BRAND ONLY]: IF the user mentions ONLY a brand (e.g., "Audi", "Tesla") with NO specific model variant:
      STOP. 
      Check the {context} for available models of that brand.
      Reply ONLY: "ขอทราบรุ่น [Brand Name] ที่ท่านสนใจครับ? (ในระบบมีข้อมูล: [List models found in context])"
      
    - RULE 2 [MODEL FOUND / MULTIPLE VERSIONS]: IF the user provides a model (e.g. "Audi e-tron sportback 55") but there are multiple versions (different years/specs):
      DO NOT STOP.
      PROCEED to Context Refinement.
      Instruct the AI to answer using the most relevant data available and mention that there are multiple versions (e.g. "ข้อมูลสำหรับ Audi e-tron sportback 55 รุ่นปี 2019-2020 คือ...").
      
    - RULE 3 [MODEL NOT FOUND]: IF the model name provided does not appear in the context at all:
      STOP.
      Reply: "ขออภัยครับ ไม่พบข้อมูลสำหรับรุ่น '[User Model]' ในระบบ (รุ่นที่มีข้อมูลคือ: [List valid models from context])"

    # 2. CONTEXT REFINEMENT (Step-by-Step Thinking):
    1. **Analyze the Request**: Identify the specific car model or topic.
    2. **Filter Context**: Scan the retrieved chunks below. IGNORE chunks that do not match the specific model (e.g. if asking for "Zeekr 009", ignore "Zeekr X" or "SCB Report").
    3. **Extract Facts**: Extract specs, prices, charging info, AND any **[IMAGE PATH: ...]** associated with the filtered chunks.
    4. **Synthesize Answer**: Answer based on the extracted facts. **CRITICAL**: If an image path was extracted, YOU MUST DISPLAY IT at the end.
    
    Context:
    {context}
    
    History: {history}
    Question: {question}
    
    Rules:
     - ANSWER IN THAI LANGUAGE ONLY (Respond properly with 'ครับ' or 'ค่ะ').
     - If 'Visual' intent, describe the table/chart details clearly.
     - If 'Deep Reasoning', explain the 'Why' and 'How'.
     - Cite the source page (e.g. [Page 5]).
     - If an [IMAGE PATH: ...] is provided:
        - Extract the FILENAME from the path (e.g. "image.jpg" from "/api/images/image.jpg").
        - DISPLAY IT using Markdown syntax: ![Image](/api/images/<filename>)
        - (Example: ![Image](/api/images/audi-e-tron.jpg))
     - DO NOT SAY "Here is the image". JUST OUTPUT THE MARKDOWN.
    - If you don't know the answer or the context is insufficient, say "ขออภัยครับ ข้อมูลในระบบยังมีไม่เพียงพอ" and ask specific clarifying questions.
    - If the user's intent is unclear, ask for clarification (e.g. "หมายถึงรุ่นไหนครับ?").
    - Be polite and professional.
    """
    prompt = ChatPromptTemplate.from_template(template)
    final_chain = (prompt | dynamic_llm | StrOutputParser())
    
    response = final_chain.invoke({
        "history": history,
        "context": context,
        "question": standalone_question,
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
