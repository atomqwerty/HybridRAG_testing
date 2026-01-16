import os
import re
from PIL import Image
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# LCEL Imports
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 1. Setup Environment
load_dotenv()

# 2. Connect to Neo4j
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
)

# 3. Initialize Models
# llm is now created dynamically in answer()

embeddings = OpenAIEmbeddings(
     model="text-embedding-3-large", 
     openai_api_base="https://aigateway.ntictsolution.com/v1",
     openai_api_key=os.getenv("OpenAi_api_key")
)

# Reranker configuration
RERANKER_METHOD = os.getenv("RERANKER_METHOD", "llm").lower()  # Options: "llm", "cohere", "cross-encoder"
print(f"🔧 Using reranker: {RERANKER_METHOD.upper()}")

# Global Cache for Cross-Encoder
_CROSS_ENCODER_MODEL = None

def initialize_reranker():
    """Preloads the reranker model to avoid cold start latency."""
    global _CROSS_ENCODER_MODEL
    if RERANKER_METHOD == "cross-encoder" and _CROSS_ENCODER_MODEL is None:
        try:
            from sentence_transformers import CrossEncoder
            print("   ⏳ Pre-loading Cross-Encoder model...")
            _CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            print("   ✅ Cross-Encoder model loaded!")
        except Exception as e:
            print(f"   ⚠️ Failed to preload Cross-Encoder: {e}")

# 4. Define Retrieval Function


def create_fulltext_index(graph):
    """Creates a fulltext index on Entity nodes for better keyword search."""
    try:
        # Check if index exists usually requires listing indexes, but we can try creating directly with IF NOT EXISTS logic handled by Neo4j or just try/except
        graph.query("""
            CREATE FULLTEXT INDEX entity_id_index IF NOT EXISTS 
            FOR (n:Entity) ON EACH [n.id]
        """)
        print("✅ Fulltext Index 'entity_id_index' checks out.")
    except Exception as e:
        print(f"⚠️ Could not create fulltext index (might already exist): {e}")

def extract_entities(llm, question: str) -> list:
    """Uses LLM to find the most important entities/keywords in the question."""
    prompt = f"""
    Extract the 2-3 most important entities or keywords from this question for a database search.
    Return ONLY a comma-separated list of terms. NO explanation.

    Question: {question}
    """
    response = llm.invoke(prompt).content
    terms = [t.strip() for t in response.split(',') if t.strip()]
    print(f"🧩 Extracted search terms: {terms}")
    return terms

def retrieve_graph_context(graph, llm, question: str, limit: int = 15) -> str:
    """Smartly gets relevant entities using Fulltext Search + LLM extraction."""
    
    # 1. Ensure Index Exists
    create_fulltext_index(graph)

    # 2. Extract Search Terms (e.g. "Max", "Red Bull")
    search_terms = extract_entities(llm, question)
    if not search_terms:
        return ""

    # 3. Lucene Query Construction (Term1 OR Term2~)
    # The ~ implies fuzzy matching
    # 3. Lucene Query Construction
    lucene_query = " OR ".join([f"{term}~" for term in search_terms])
    
    # improved structured retrieval query
    # improved structured retrieval query
    # Check for specific labels if generic 'Entity' is not used (common in Diffbot/LLM transformers)
    cypher_query = """
    CALL db.index.fulltext.queryNodes("entity_id_index", $query, {limit: 5})
    YIELD node, score
    WITH node
    MATCH (node)-[r]-(neighbor)
    RETURN node.id + ' --[' + type(r) + ']-> ' + neighbor.id AS output
    LIMIT 50
    """
    
    try:
        results = graph.query(cypher_query, {"query": lucene_query})
        return "\n".join([row['output'] for row in results])
    except Exception as e:
        print(f"⚠️ Graph search failed: {e}")
        return ""



def vector_retrieve(graph, embeddings, question, k=10, min_score=0.5):
    """Gets relevant text chunks using Vector Similarity."""
    q_embedding = embeddings.embed_query(question)
    
    # Using the index 'doc_embedding' we created
    result = graph.query("""
        CALL db.index.vector.queryNodes('doc_embedding', $k, $embedding)
        YIELD node, score
        WHERE score >= $min_score
        RETURN node.text AS text, node.source AS source, node.page AS page, score
        ORDER BY score DESC
    """, {"embedding": q_embedding, "k": k, "min_score": min_score})
    
    return result


def create_chunk_fulltext_index(graph):
    """Creates a fulltext index on Chunk.text for keyword/hybrid search."""
    try:
        graph.query("""
            CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS 
            FOR (n:Chunk) ON EACH [n.text]
        """)
        print("✅ Fulltext Index 'chunk_text_index' checks out.")
    except Exception as e:
        print(f"⚠️ Could not create chunk fulltext index: {e}")

def keyword_retrieve(graph, question, k=5):
    """Retrieves chunks using Keyword (Fulltext) Search."""
    # 1. Extract keywords (remove stop words simple approach)
    # Simple split for now, or use the existing extract_entities
    terms = question.split()
    lucene_query = " AND ".join([f"{t}~" for t in terms if len(t) > 3])
    
    if not lucene_query:
        return []
        
    print(f"🔑 Keyword Search Query: {lucene_query}")
    
    query = """
    CALL db.index.fulltext.queryNodes("chunk_text_index", $query, {limit: $k})
    YIELD node, score
    RETURN node.text as text, node.source as source, node.page as page, score
    """
    
    try:
        results = graph.query(query, {"query": lucene_query, "k": k})
        return results
    except Exception as e:
        print(f"⚠️ Keyword search failed: {e}")
        return []

def hybrid_context(graph, embeddings, question):
    """Combines Graph, Vector, and Keyword context."""
    
    # 0. Ensure Indexes
    create_fulltext_index(graph) # For Entities
    create_chunk_fulltext_index(graph) # For Chunks (Hybrid)
    
    # 1. GRAPH SEARCH (Knowledge Graph)
    graph_ctx = retrieve_graph_context(graph, llm, question)
    if graph_ctx:
        print(f"\n🕸️ DEBUG: Graph Search Found:\n{graph_ctx[:300]}...")
    else:
        print("\n🕸️ DEBUG: No direct graph connections found.") 

    # 2. HYBRID SEARCH (Vector + Keyword)
    
    # A. Keyword Search (Good for exact matches like "Money", "F1")
    keyword_ctx = keyword_retrieve(graph, question, k=5)
    if keyword_ctx:
        print(f"\n🔑 DEBUG: Keyword Search Found {len(keyword_ctx)} results")
    
    # B. Vector Search (Good for concepts)
    # Reduced k=15 for speed. Increased min_score=0.50 to reduce unrelated images.
    vector_ctx = vector_retrieve(graph, embeddings, question, k=15, min_score=0.50)
    
    # TRACE Retrieval
    if vector_ctx:
        print(f"\n🔍 TRACE: Vector Retrieved {len(vector_ctx)} candidates.")
        found_imgs = [r.get('source', '') for r in vector_ctx if '[IMAGE' in r['text'] or '.jpg' in r.get('source', '')]
        print(f"   📸 Vector Images: {found_imgs}")
    
    # Combine Vector + Keyword candidates (Deduplicate)
    combined_results = []
    seen_texts = set()
    
    # Add Keyword results first (usually high precision)
    for r in keyword_ctx:
        if r['text'] not in seen_texts:
            combined_results.append({**r, 'score': 1.0}) # Give high default score to exact matches
            seen_texts.add(r['text'])
            
    # 🔍 TRACE 1: Retrieval
    if vector_ctx:
        print(f"\n🔍 TRACE: Retrieved {len(vector_ctx)} candidates.")
        # Only count ACTUAL image files as images for this trace
        found_imgs = [r.get('source', '') for r in vector_ctx if r.get('source', '').lower().endswith(('.jpg', '.jpeg', '.png'))]
        print(f"   📸 Vector Images (Files): {found_imgs}")
    else:
        print("\n🔍 TRACE: No candidates retrieved.")
    
    # Add Vector results
    for r in vector_ctx:
        if r['text'] not in seen_texts:
            combined_results.append(r)
            seen_texts.add(r['text'])
            
    vector_ctx = combined_results # Use the combined list
    
    # Re-rank vector results for better relevance
    if vector_ctx:
        # Separate actual image files and text/pdf
        is_img_file = lambda r: r.get('source', '').lower().endswith(('.jpg', '.jpeg', '.png'))
        image_file_results = [r for r in vector_ctx if is_img_file(r)]
        
        # Rerank everything
        reranked = rerank_results(question, vector_ctx, top_k=5, method=RERANKER_METHOD)
        
        # 🔍 TRACE 2: After Rerank
        reranked_img_files = [r.get('source', '') for r in reranked if is_img_file(r)]
        print(f"   📸 Image Files surviving re-rank: {reranked_img_files}")
        
        # FORCE INCLUDE: If no ACTUAL IMAGE FILES in top 5, but we had them in retrieval, add the best matching one
        has_img_file_in_top = len(reranked_img_files) > 0
        
        if not has_img_file_in_top and image_file_results:
            print("   👉 No standalone images in top results, forcing inclusion of best image file.")
            # Add the highest scored image file from original retrieval
            best_image = image_file_results[0]
            reranked.append(best_image)
            print(f"   📸 Added back: {best_image.get('source', 'unknown')}")
            
        vector_ctx = reranked
        print(f"   ✅ Final context count: {len(vector_ctx)}")
        print(f"   ✅ After re-ranking: {len(vector_ctx)} results kept")


    context = "### GRAPH KNOWLEDGE BITS:\n"
    context += graph_ctx if graph_ctx else "No direct entity facts found.\n"

    context += "\n### RELEVANT TEXT CHUNKS:\n"
    if vector_ctx:
        for row in vector_ctx:
            src = row.get('source', 'Unknown')
            pg = row.get('page', '?')
            # Clean up source path if full path
            if src and os.path.sep in str(src):
                src = str(src).split(os.path.sep)[-1]
                
            context += f"- {row['text']} [Source: {src}, Page: {pg}]\n"
            
            # Additional hint for LLM about this source
            if '[IMAGE' in row['text']:
                context += "  (👆 THIS IS CONTENT EXTRACTED FROM AN INFOGRAPHIC/IMAGE. TREAT AS RELIABLE DATA.)\n"
    else:
        context += "SYSTEM NOTE: No direct data matches found. The user's question might be vague, misspelled, or about a year/topic not in the database. YOU MUST ASK A CLARIFYING QUESTION.\n"

    return context


def rerank_results(question, results, top_k=3, method="llm"):
    """
    Re-rank retrieved results using various methods.
    
    Args:
        question: User's question
        results: List of retrieved results
        top_k: Number of top results to return
        method: Reranking method - "llm", "cohere", or "cross-encoder"
    
    Returns:
        Re-ranked and filtered results
    """
    if not results or len(results) == 0:
        return results
    
    print(f"🔄 Re-ranking {len(results)} results using {method.upper()}...")
    
    if method == "llm":
        return _rerank_with_llm(question, results, top_k)
    elif method == "cohere":
        return _rerank_with_cohere(question, results, top_k)
    elif method == "cross-encoder":
        return _rerank_with_cross_encoder(question, results, top_k)
    else:
        print(f"   ⚠️ Unknown reranking method: {method}, using LLM")
        return _rerank_with_llm(question, results, top_k)


def _rerank_with_llm(question, results, top_k=3):
    """Original LLM-based reranking."""
    # Create prompt for LLM to score relevance
    rerank_prompt = f"""You are a relevance scoring system. Given a user question and a text passage, score how relevant the passage is to answering the question.

Score from 0-10 where:
- 10: Directly answers the question with specific information
- 7-9: Highly relevant, contains useful context
- 4-6: Somewhat relevant, tangentially related
- 1-3: Barely relevant, mentions similar topics
- 0: Completely irrelevant

Question: {question}

For each passage below, respond with ONLY a number (0-10):

"""
    
    # Score each result
    scored_results = []
    for idx, result in enumerate(results):
        passage = result['text'][:500]  # Limit to first 500 chars for efficiency
        
        # Ask LLM to score this passage
        score_prompt = f"{rerank_prompt}\nPassage {idx+1}: {passage}\n\nRelevance score:"
        
        try:
            response = llm.invoke(score_prompt).content.strip()
            # Extract numeric score
            relevance_score = float(response.split()[0])  # Get first number
            
            # Combine with original vector score (weighted average)
            combined_score = (relevance_score / 10.0) * 0.7 + result.get('score', 0.5) * 0.3
            
            scored_results.append({
                **result,
                'relevance_score': relevance_score,
                'combined_score': combined_score
            })
        except Exception as e:
            print(f"   ⚠️ Re-ranking failed for result {idx+1}: {e}")
            # Keep original if re-ranking fails
            scored_results.append({
                **result,
                'relevance_score': 5.0,
                'combined_score': result.get('score', 0.5)
            })
    
    # Sort by combined score and return top_k
    scored_results.sort(key=lambda x: x['combined_score'], reverse=True)
    top_results = scored_results[:top_k]
    
    print(f"   ✅ Kept top {len(top_results)} most relevant results")
    
    return top_results


def _rerank_with_cohere(question, results, top_k=3):
    """Rerank using Cohere Rerank API (requires cohere library)."""
    try:
        import cohere
        
        # Get API key from environment
        cohere_api_key = os.getenv('COHERE_API_KEY')
        if not cohere_api_key:
            print("   ⚠️ COHERE_API_KEY not found, falling back to LLM")
            return _rerank_with_llm(question, results, top_k)
        
        co = cohere.Client(cohere_api_key)
        
        # Prepare documents for Cohere
        documents = [r['text'] for r in results]
        
        # Call Cohere Rerank API
        rerank_response = co.rerank(
            model="rerank-english-v3.0",  # or "rerank-multilingual-v3.0"
            query=question,
            documents=documents,
            top_n=top_k
        )
        
        # Map back to original results with scores
        reranked = []
        for result in rerank_response.results:
            original_result = results[result.index]
            reranked.append({
                **original_result,
                'relevance_score': result.relevance_score,
                'combined_score': result.relevance_score
            })
        
        print(f"   ✅ Kept top {len(reranked)} most relevant results")
        return reranked
        
    except ImportError:
        print("   ⚠️ Cohere library not installed. Run: pip install cohere")
        return _rerank_with_llm(question, results, top_k)
    except Exception as e:
        print(f"   ⚠️ Cohere reranking failed: {e}, falling back to LLM")
        return _rerank_with_llm(question, results, top_k)


def _rerank_with_cross_encoder(question, results, top_k=3):
    """Rerank using local cross-encoder model (requires sentence-transformers)."""
    try:
        from sentence_transformers import CrossEncoder
        global _CROSS_ENCODER_MODEL
        
        # Load cross-encoder model (cached after first load)
        if _CROSS_ENCODER_MODEL is None:
            print("   ⏳ Loading Cross-Encoder model (one-time cost)...")
            _CROSS_ENCODER_MODEL = CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')
            
        model = _CROSS_ENCODER_MODEL
        
        # Prepare pairs for scoring
        pairs = [[question, r['text'][:512]] for r in results]  # Limit text length
        
        # Get scores
        scores = model.predict(pairs)
        
        # Combine with original scores
        scored_results = []
        for idx, (result, ce_score) in enumerate(zip(results, scores)):
            combined_score = ce_score * 0.7 + result.get('score', 0.5) * 0.3
            scored_results.append({
                **result,
                'relevance_score': float(ce_score),
                'combined_score': float(combined_score)
            })
        
        # Sort and return top_k
        scored_results.sort(key=lambda x: x['combined_score'], reverse=True)
        top_results = scored_results[:top_k]
        
        print(f"   ✅ Kept top {len(top_results)} most relevant results")
        return top_results
        
    except ImportError:
        print("   ⚠️ sentence-transformers not installed. Run: pip install sentence-transformers")
        return _rerank_with_llm(question, results, top_k)
    except Exception as e:
        print(f"   ⚠️ Cross-encoder reranking failed: {e}, falling back to LLM")
        return _rerank_with_llm(question, results, top_k)







def answer(question, history="", temperature=0.3):
    """Final QA function using LCEL."""
    print(f"🤔 Thinking about: {question} (Temp: {temperature})")
    
    # Create dynamic LLM with requested temp
    dynamic_llm = ChatOpenAI(
        api_key=os.getenv("OpenAi_api"),
        base_url="https://aigateway.ntictsolution.com/v1",
        model="gpt-4o-mini",
        temperature=temperature
    )
    
    # --- Step 1: Condense Question (if history exists) ---
    standalone_question = question
    if history:
        print("🤔 Rewriting question based on history...")
        condense_template = """Given the chat history and a follow-up question, rephrase the follow-up question to be a standalone question.
Chat History:
{history}
Follow Up Input: {question}
Standalone question:"""
        condense_prompt = ChatPromptTemplate.from_template(condense_template)
        # We need a synchronous LLM call for the condensation
        standalone_question = llm.invoke(condense_prompt.format(history=history, question=question)).content
        print(f"   👉 Rewritten: {standalone_question}")

    print(f"🤔 Thinking about: {standalone_question}")
    
    # --- Step 2: Retrieve Context using Standalone Question ---
    # We pass the string directly to the retriever now
    context = hybrid_context(graph, embeddings, standalone_question)
    
    # --- Step 2.5: Display Cited Images & Sources ---
    def display_images_from_context(text):
        paths = re.findall(r"\[IMAGE PATH: (.*?)\]", text)
        seen_paths = set()
        count = 0
        MAX_IMAGES = 2 # Limit to avoid overwhelming user
        
        for p in paths:
            try:
                p = p.strip()
                if p in seen_paths: continue
                seen_paths.add(p)
                
                if count >= MAX_IMAGES: break # Stop after max
                
                if os.path.exists(p):
                    print(f"🖼️ Opening relevant image: {p}")
                    # Image.open(p).show()
                    count += 1
            except Exception as e:
                print(f"⚠️ Could not display image {p}: {e}")

    def display_sources_from_context(text):
        # Find all sources
        matches = re.findall(r"\[Source: (.*?), Page: (.*?)\]", text)
        if matches:
            unique_sources = set()
            print("\n📚 Sources Used:")
            for src, pg in matches:
                # Create a composite key to avoid duplicate page refs if desired, or just list files
                entry = f"   - {src} (Page {pg})"
                if entry not in unique_sources:
                    print(entry)
                    unique_sources.add(entry)
            print("")

    display_images_from_context(context)
    display_sources_from_context(context)
    
    # --- Step 3: Generate Answer ---
    template = """You are an intelligent AI assistant acting as an **Expert Technical Support Agent for EV Chargers**.
    
<instruction>
Please answer the user's question based **ONLY** on the provided context.

STRATEGY (Chain of Thought):
1. **Analyze** if the question is about EV Chargers, Specifications, or Installation.
2. **Scan** the <context> for technical details (Voltage, KW, Amps, Connector Types).
3. **Verify** matches between the user's vehicle/request and the charger specs in the context.
4. **Draft** your response in the requested language (Thai/English).

CRITICAL RULES:
- **Language:** Answer in the SAME language as the <question> (English -> English, Thai -> Thai).
- **No Hallucination:** If the answer is not in <context>, politely say you don't have that specific information.
- **Tables:** If providing technical comparisons (e.g., AC vs DC, 7kW vs 22kW), **YOU MUST** use a Markdown Table.
- **Images:** If you see [IMAGE PATH: ...] in the context, mention that you have found a relevant image/diagram.

SOURCE ATTRIBUTION:
- Rely heavily on the provided text chunks.
- If data comes from an image description (labeled as 'DETECTED IMAGES'), trust it as visual evidence.

</instruction>

<history>
{history}
</history>

<context>
{context}
</context>

<question>
{question}
</question>

<response_guidelines>
- Be helpful, technical, but easy to understand.
- Use bullet points for features.
- If the user asks about a specific model (e.g., "AION"), look for its specific specs.
</response_guidelines>
"""

    prompt = ChatPromptTemplate.from_template(template)
    
    # We construct the final chain manually for clarity
    final_chain = (
        prompt 
        | dynamic_llm 
        | StrOutputParser()
    )
    
    response = final_chain.invoke({
        "history": history,
        "context": context,
        "question": standalone_question # Use the rewritten question here too
    })
    
    # For debugging:
    # print(f"🤖 Context Used:\n{context}\n")
    
    # Return structured data including context to avoid double-fetching
    return {
        "result": response,
        "context": context
    }

# 5. Run it (Interactive Mode)
if __name__ == "__main__":
    print("\n💬 Hybrid RAG Chatbot Initialized (with Memory). Type 'exit' to quit.\n")
    
    chat_history_str = ""
    
    while True:
        q = input("User: ")
        if q.lower() in ['exit', 'quit', 'q']:
            print("Bye! 👋")
            break
                
        if not q.strip(): continue # Skip empty
            
        output = answer(q, history=chat_history_str)
        print(f"Bot: {output['result']}\n")
        print("-" * 50)
            
        # Update History (Keep last 3 turns to fit context)
        chat_history_str += f"User: {q}\nBot: {output['result']}\n"
            
#llm rerank = slow af Cohere vs CROSS-ENCODER need to test
