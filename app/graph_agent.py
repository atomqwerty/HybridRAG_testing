import os
from typing import TypedDict, List, Annotated
from langgraph.graph import StateGraph, END
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser

# Import from our existing codebase
from run_qa import retrieve_documents, format_context, get_graph, embeddings
from config import Config

# --- 1. STATE DEFINITION ---
class GraphState(TypedDict):
    """
    Represents the state of our graph.
    """
    question: str
    generation: str
    documents: List[Document]
    graph_context: str
    web_search: bool
    iterations: int
    intent: str # Added intent
    reasoning: str # Added reasoning

# --- 2. NODES ---

def retrieve(state):
    """
    Retrieve documents (Vector + Graph) using existing hybrid logic.
    """
    print("---RETRIEVE---")
    question = state["question"]
    graph = get_graph()
    
    # Use existing hybrid retrieval
    # We pass None for llm_model in retrieval/grading to save tokens, or use a cheaper one?
    # run_qa uses dynamic_llm for reranking. Let's initialize one.
    llm = ChatOpenAI(model=Config.OPENAI_API_MODEL, temperature=0)
    
    vector_data, graph_ctx = retrieve_documents(graph, embeddings, question, llm_model=llm)
    
    # Convert list[dict] to list[Document]
    documents = []
    for item in vector_data:
        doc = Document(
            page_content=item.get('text', ''),
            metadata={
                'source': item.get('source', ''),
                'page': item.get('page', ''),
                'score': item.get('score', 0),
                'image_path': item.get('image_path', '')
            }
        )
        documents.append(doc)
        
    return {
        "documents": documents, 
        "graph_context": graph_ctx,
        "question": question
    }

def grade_documents(state):
    """
    Determines whether the retrieved documents are relevant to the question.
    """
    print("---CHECK RELEVANCE---")
    question = state["question"]
    documents = state["documents"]
    
    # LLM with function call or JSON output
    llm = ChatOpenAI(model=Config.OPENAI_API_MODEL, temperature=0, format="json")
    
    prompt = ChatPromptTemplate.from_template(
        """You are a grader assessing relevance of a retrieved document to a user question. \n 
        Here is the retrieved document: \n\n {context} \n\n
        Here is the user question: {question} \n
        If the document contains keyword(s) or semantic meaning related to the user question, grade it as relevant. \n
        Give a binary score 'yes' or 'no' score to indicate whether the document is relevant to the question.
        Provide the binary score as a JSON with a single key 'score' and no premable or explaination."""
    )
    
    chain = prompt | llm | JsonOutputParser()
    
    # Grade each document
    filtered_docs = []
    has_relevant = False
    
    # Optimization: concatenated check might be cheaper but per-doc is more precise
    # For speed, let's just check the top 3-5 combined or check the top 1?
    # RRF already ranked them. Let's check the top ones.
    
    # Actually, let's check if ANY document is relevant.
    # We can concatenate the top 3 texts and ask "Is this relevant?"
    top_docs = documents[:3] if documents else []
    if not top_docs:
        print("---NO DOCUMENTS RETRIEVED---")
        return {"documents": [], "web_search": True}
        
    context_text = "\n".join([d.page_content for d in top_docs])
    
    try:
        score = chain.invoke({"question": question, "context": context_text})
        grade = score.get("score", "no")
    except:
        grade = "yes" # Default to yes if JSON fails
        
    if grade == "yes":
        print("---DECISION: DOCS RELEVANT---")
        return {"documents": documents, "web_search": False}
    else:
        print("---DECISION: DOCS NOT RELEVANT---")
        # If not relevant, we might want to try web search or rewrite
        return {"documents": [], "web_search": True}

def transform_query(state):
    """
    Transform the query to produce a better question.
    """
    print("---TRANSFORM QUERY---")
    question = state["question"]
    documents = state["documents"]
    
    llm = ChatOpenAI(model=Config.OPENAI_API_MODEL, temperature=0)
    
    # Create a prompt that rewrites the question
    msg = [
        ("system", "You are an intelligent assistant. The user's question retrieved no relevant documents. Rephrase the question to be broader or use different keywords to find better results."),
        ("human", f"Original Question: {question}")
    ]
    response = llm.invoke(msg)
    better_question = response.content
    
    return {"question": better_question, "documents": documents, "iterations": state.get("iterations", 0) + 1}

def web_search(state):
    """
    Simulated Web Search (Placeholder for now, or use Tavily if available).
    For now, we just pass through but mark as 'web_search' for the generator to know.
    """
    print("---WEB SEARCH---")
    # In a real impl, we would use Tavily/SerpAPI here.
    return {"documents": state["documents"]}

def generate(state):
    """
    Generate answer from context.
    """
    print("---GENERATE---")
    question = state["question"]
    documents = state["documents"]
    graph_ctx = state["graph_context"]
    
    # Convert docs back to list[dict] for format_context
    vector_ctx = []
    for d in documents:
        item = {'text': d.page_content}
        item.update(d.metadata)
        vector_ctx.append(item)
        
    # Format context string
    context_str = format_context(vector_ctx, graph_ctx)
    
    llm = ChatOpenAI(model=Config.OPENAI_API_MODEL, temperature=0.3)
    
    # Reuse prompt logic from run_qa (simplified)
    # Ideally import prompt from run_qa but it is embedded in code
    
    system_prompt = """You are an intelligent Thai AI assistant (Hybrid RAG).
    Answer the question based strictly on the provided context.
    If the context lacks info, say "I don't know".
    
    Context:
    {context}
    """
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{question}")
    ])
    
    chain = prompt | llm | StrOutputParser()
    generation = chain.invoke({"context": context_str, "question": question})
    
    return {"generation": generation}

# --- 3. AGENTS & NODES ---

from agents.supervisor import supervisor
from agents.table_agent import table_agent

def supervisor_node(state):
    """
    Router node that classifies intent.
    """
    print("---SUPERVISOR ROUTING---")
    question = state["question"]
    route = supervisor.route(question)
    
    return {
        "intent": route.intent,
        "reasoning": route.reasoning
    }

def table_agent_node(state):
    """
    Node for Table Agent.
    """
    print("---TABLE AGENT---")
    question = state["question"]
    
    # Invoke pandas agent
    answer = table_agent.invoke(question)
    
    return {
        "generation": f"[Table Agent]: {answer}", # Prefix for clarity
        "documents": [], # No docs retrieves in traditional sense
        "intent": "table"
    }

def text_agent_node(state):
    """
    Wrapper for existing Text Agent (Retrieve -> Grade -> Generate).
    For now, we just route to the START of the text subgraph.
    But in a flat graph, we just route to 'retrieve'.
    """
    print("---ROUTING TO TEXT AGENT---")
    return {"intent": "text"}

# --- 4. CONDITIONAL EDGES ---

def route_intent(state):
    """
    Determines next node based on supervisor intent.
    """
    intent = state.get("intent", "text")
    print(f"---ROUTING TO: {intent.upper()}---")
    
    if intent == "table":
        return "table_agent"
    elif intent == "image":
        return "text_agent" # Fallback to text for now until Image Agent is ready
    else:
        return "text_agent"

# --- 5. BUILD GRAPH ---

workflow = StateGraph(GraphState)

# Nodes
workflow.add_node("supervisor", supervisor_node)
workflow.add_node("table_agent", table_agent_node)

# Text Agent Nodes (Existing)
workflow.add_node("retrieve", retrieve)
workflow.add_node("grade_documents", grade_documents)
workflow.add_node("generate", generate)
workflow.add_node("transform_query", transform_query)

# Edges
# Start at Supervisor
workflow.set_entry_point("supervisor")

# Supervisor to Agents
workflow.add_conditional_edges(
    "supervisor",
    route_intent,
    {
        "table_agent": "table_agent",
        "text_agent": "retrieve" # Text agent starts at Retrieve
    }
)

# Table Agent End
workflow.add_edge("table_agent", END)

# Text Agent Flow (Existing)
workflow.add_edge("retrieve", "grade_documents")
workflow.add_conditional_edges(
    "grade_documents",
    decide_to_generate,
    {
        "transform_query": "transform_query",
        "generate": "generate"
    }
)
workflow.add_edge("transform_query", "retrieve")
workflow.add_edge("generate", END)

# Compile
app_graph = workflow.compile()
