import os
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph
from langchain_openai import ChatOpenAI, OpenAIEmbeddings

# 1. Setup Environment
load_dotenv()

# 2. Connect to Neo4j
graph = Neo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
)

# 3. Initialize Models
llm = ChatOpenAI(
    api_key=os.getenv("OpenAi_api"),
    base_url="https://aigateway.ntictsolution.com/v1",
    model="gpt-4o",
    temperature=0
)

embeddings = OpenAIEmbeddings(
     model="text-embedding-3-large", 
     openai_api_base="https://aigateway.ntictsolution.com/v1",
     openai_api_key=os.getenv("OpenAi_api_embbeding")
)

# 4. Define Retrieval Functions

# 4. Define Retrieval Functions

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
    lucene_query = " OR ".join([f"{term}~" for term in search_terms])
    
    cypher_query = """
    CALL db.index.fulltext.queryNodes("entity_id_index", $query, {limit: 5})
    YIELD node, score
    MATCH (node)-[r]-(connected)
    RETURN node, type(r) as relation, connected, score
    LIMIT $limit
    """
    
    joined_context = []
    
    try:
        results = graph.query(cypher_query, {"query": lucene_query, "limit": limit})
    except Exception as e:
        print(f"⚠️ Fulltext search failed, falling back to basic CONTAINS: {e}")
        # Fallback to old method if index fails
        fallback_results = []
        for term in search_terms:
            q_res = graph.query("""
                MATCH (n:Entity)-[r]-(m:Entity)
                WHERE toLower(n.id) CONTAINS toLower($term)
                RETURN n as node, type(r) as relation, m as connected
                LIMIT 5
            """, {'term': term})
            fallback_results.extend(q_res)
        results = fallback_results

    if not results:
        return ""

    for row in results:
        s = row['node']
        t = row['connected']
        s_id = s.get('id', 'Unknown')
        t_id = t.get('id', t.get('text', '')[:50] + "...")
        joined_context.append(f"{s_id} --[{row['relation']}]--> {t_id}")

    return "\n".join(set(joined_context)) # Remove duplicates



def vector_retrieve(graph, embeddings, question, k=10):
    """Gets relevant text chunks using Vector Similarity."""
    q_embedding = embeddings.embed_query(question)
    
    # Using the index 'doc_embedding' we created
    result = graph.query("""
        CALL db.index.vector.queryNodes('doc_embedding', $k, $embedding)
        YIELD node, score
        RETURN node.text AS text, score
    """, {"embedding": q_embedding, "k": k})
    
    return result


def hybrid_context(graph, embeddings, question):
    """Combines Graph and Vector context."""
    graph_ctx = retrieve_graph_context(graph, llm, question) 
    vector_ctx = vector_retrieve(graph, embeddings, question)

    context = "### GRAPH KNOWLEDGE BITS:\n"
    context += graph_ctx if graph_ctx else "No direct entity facts found.\n"

    context += "\n### RELEVANT TEXT CHUNKS:\n"
    if vector_ctx:
        for row in vector_ctx:
            context += f"- {row['text']}\n"
    else:
        context += "No relevant text chunks found.\n"

    return context


def answer(question):
    """Final QA function."""
    print(f"🤔 Thinking about: {question}")
    
    context = hybrid_context(graph, embeddings, question)
    
    # Optional: Print context to see what's retrieved
    # print(f"\n[Context Retrieved]\n{context}\n")
    
    prompt = f"""
    You are an AI assistant answering questions based on a combined Knowledge Graph and Vector search.
    Use ONLY the context provided below. If the answer is not in the context, say "I don't know".

    CONTEXT:
    {context}

    QUESTION:
    {question}

    ANSWER:
    """
    print(f"🤖 context: {context}")
    response = llm.invoke(prompt)
    return response.content

# 5. Run it
if __name__ == "__main__":
    q = "what team is max drive for?"
    result = answer(q)
    print("\n-----------------")
    print(f"🤖 Answer: {result}")
    print("-----------------")
    
