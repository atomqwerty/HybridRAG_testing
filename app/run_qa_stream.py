
import os
import re
import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

# Import from run_qa to reuse Graph/Retrieval logic
# Import from run_qa (graph global removed, use get_graph)
from run_qa import get_graph, embeddings, hybrid_context

load_dotenv()

def answer_stream(question, history="", temperature=0.3):
    """
    Generator function that yields streaming responses.
    Protocol:
    1. Yields metadata (sources/context) first.
    2. Yields chunks of text.
    """
    print(f"[INFO] Streaming Answer for: {question}")
    
    # Create dynamic LLM
    dynamic_llm = ChatOpenAI(
        api_key=os.getenv("OpenAi_api_key"),
        base_url="https://aigateway.ntictsolution.com/v1",
        model="gpt-4o-mini",
        temperature=temperature
    )
    
    # --- Step 1: Condense Question ---
    standalone_question = question
    if history:
        condense_template = """Given chat history and follow-up, rephrase to standalone question.
Chat History: {history}
Follow Up: {question}
Standalone:"""
        condense_prompt = ChatPromptTemplate.from_template(condense_template)
        # We don't stream the rewrite, just await it
        standalone_question = dynamic_llm.invoke(condense_prompt.format(history=history, question=question)).content
    
    # --- Step 2: Retrieve ---
    # This is the blocking part (2-3s)
    try:
        graph = get_graph()
    except:
        yield json.dumps({"type": "token", "content": "System Initializing..."}) + "\n"
        return

    context = hybrid_context(graph, embeddings, standalone_question, llm_model=dynamic_llm)
    
    # Parse sources for frontend
    sources = []
    seen_sources = set()
    matches = re.findall(r"\[Source: (.*?), Page: (.*?)\]", context)
    for src, pg in matches:
        if (src, pg) not in seen_sources:
            sources.append({"file": src, "page": pg})
            seen_sources.add((src, pg))
        
    # Find images
    images = []
    img_matches = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
    for p in img_matches:
        img_name = os.path.basename(p)
        images.append(img_name)
    
    # YIELD METADATA
    yield json.dumps({
        "type": "meta", 
        "sources": sources, 
        "images": images,
        "debug_context": context 
    }) + "\n"
    
    # --- Step 3: Generate Stream ---
    template = """You are an intelligent AI assistant acting as an **Expert Technical Support Agent for EV Chargers**.
    
<instruction>
Answer based ONLY on based context.
STRATEGY:
1. Analyze question.
2. Scan context for specs.
3. Verify matches.
4. Draft response in SAME language as question.

CRITICAL RULES:
- Language: Match Question Language.
- No Hallucination.
- Tables: Use Markdown Tables for specs.
- Images: Mention [IMAGE PATH: ...] if found.
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
- Be helpful and technical.
- Use Markdown Tables for data.
- **CRITICAL**: When asked for names or lists (e.g., "who are...", "list of..."), you MUST provide EVERY SINGLE item from the context. Never summarize, truncate, or provide partial lists. If the context mentions a total count (e.g., "15 directors"), ensure you list exactly that many items. Providing incomplete lists is unacceptable.
- For long lists (>5 items), use concise formats like tables or bulleted lists with minimal detail per item to ensure completeness.
</response_guidelines>
"""
    prompt = ChatPromptTemplate.from_template(template)
    final_chain = (prompt | dynamic_llm | StrOutputParser())
    
    # Stream the chunks
    for chunk in final_chain.stream({
        "history": history,
        "context": context,
        "question": standalone_question
    }):
        yield json.dumps({"type": "token", "content": chunk}) + "\n"
    
    yield json.dumps({"type": "done"}) + "\n"
