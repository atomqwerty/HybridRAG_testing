import os
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
    cypher_query = """
    CALL db.index.fulltext.queryNodes("entity_id_index", $query, {limit: 5})
    YIELD node, score
    CALL (node) {
      MATCH (node)-[r:!HAS_ENTITY]->(neighbor)
      RETURN node.id + ' --[' + type(r) + ']-> ' + neighbor.id AS output
      UNION
      MATCH (node)<-[r:!HAS_ENTITY]-(neighbor)
      RETURN neighbor.id + ' --[' + type(r) + ']-> ' + node.id AS output
    }
    RETURN output LIMIT 50
    """
    
    try:
        results = graph.query(cypher_query, {"query": lucene_query})
        return "\n".join([row['output'] for row in results])
    except Exception as e:
        print(f"⚠️ Graph search failed: {e}")
        return ""



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


def answer(question, history=""):
    """Final QA function using LCEL."""
    print(f"🤔 Thinking about: {question}")
    
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
        condense_chain = condense_prompt | llm | StrOutputParser()
        standalone_question = condense_chain.invoke({"history": history, "question": question})
        print(f"   ↳ Rewritten: {standalone_question}")

    print(f"🤔 Thinking about: {standalone_question}")
    
    # --- Step 2: Retrieve Context using Standalone Question ---
    # We pass the string directly to the retriever now
    context = hybrid_context(graph, embeddings, standalone_question)
    
    # --- Step 3: Generate Answer ---
    template = """You are an AI assistant answering questions based on a combined Knowledge Graph and Vector search.
Answer in the same language as the user's question.
Use ONLY the context provided below. Do NOT use outside knowledge.
If the answer is not in the context, or if the context is ambiguous, state what is missing.
If the question is completely unrelated to the provided context (e.g., general world knowledge), politely decline to answer.

SPECIAL INSTRUCTION FOR TABLES:
If the context contains tabular data (rows of text/numbers):
1. Identify potential column headers (e.g., 'Points', 'Total', 'Revenue', 'Score').
2. Align the values in each row to these headers.
3. Be careful of footnote markers (e.g., a '2' or '[1]' appearing right after a number). '581 2' likely means '581' with footnote '2', not '5812'.
4. Extract the value that mathematically or semantically matches the question.

HISTORY:
{history}

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:"""

    prompt = ChatPromptTemplate.from_template(template)
    
    # We construct the final chain manually for clarity
    final_chain = (
        prompt 
        | llm 
        | StrOutputParser()
    )
    
    response = final_chain.invoke({
        "history": history,
        "context": context,
        "question": standalone_question # Use the rewritten question here too
    })
    
    # For debugging:
    # print(f"🤖 Context Used:\n{context}\n")
    
    return response

# 5. Run it (Interactive Mode)
if __name__ == "__main__":
    print("\n💬 Hybrid RAG Chatbot Initialized (with Memory). Type 'exit' to quit.\n")
    
    chat_history_str = ""
    
    while True:
        try:
            q = input("User: ")
            if q.lower() in ['exit', 'quit', 'q']:
                print("Bye! 👋")
                break
                
            if not q.strip(): continue # Skip empty
            
            result = answer(q, history=chat_history_str)
            print(f"Bot: {result}\n")
            print("-" * 50)
            
            # Update History (Keep last 3 turns to fit context)
            chat_history_str += f"User: {q}\nBot: {result}\n"
            
        except KeyboardInterrupt:
            print("\nBye! 👋")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
