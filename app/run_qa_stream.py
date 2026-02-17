
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
        IMPORTANT: Preserve any specific model numbers or names (e.g. 009, Atto 3, Model Y). DO NOT generalize "Zeekr 009" to just "Zeekr".
        Chat History: {history}
        Follow Up: {question}
        Standalone:"""
        condense_prompt = ChatPromptTemplate.from_template(condense_template)
        # We don't stream the rewrite, just await it
        standalone_question = dynamic_llm.invoke(condense_prompt.format(history=history, question=question)).content
    
    # --- Step 2: Invoke LangGraph ---
    # We use the compiled graph to retrieve, grade, and generate
    try:
        from graph_agent import app_graph
        
        inputs = {
            "question": standalone_question,
            "documents": [],
            "iterations": 0
        }
        
        # Invoke Graph (Blocking for now)
        # Note: Future improvement - use app_graph.stream() for real-time events
        final_state = app_graph.invoke(inputs)
        
        documents = final_state.get("documents", [])
        generation = final_state.get("generation", "")
        graph_ctx = final_state.get("graph_context", "")

        # --- Step 3: Yield Metadata ---
        sources = []
        seen_sources = set()
        images = []
        seen_images = set()

        for doc in documents:
            meta = doc.metadata
            src = meta.get('source', '')
            pg = meta.get('page', '')
            
            # Source
            if src:
                s_key = (src, pg)
                if s_key not in seen_sources:
                    base_name = os.path.basename(src)
                    if not any(base_name.lower().endswith(ext) for ext in ['.jpg', '.png', '.jpeg']):
                        sources.append({"file": base_name, "page": pg})
                        seen_sources.add(s_key)
            
            # Image
            img = meta.get('image_path', '')
            if img:
                img_name = os.path.basename(img)
                if img_name not in seen_images:
                    images.append(img_name)
                    seen_images.add(img_name)
        
        # Parse extra images from graph context if any? 
        # (Our Retrieve node puts them in doc metadata, so strictly speaking we are good)
        
        yield json.dumps({
            "type": "meta", 
            "sources": sources, 
            "images": images,
            "debug_context": graph_ctx 
        }) + "\n"
        
        # --- Step 4: Stream Generation (Simulated) ---
        chunk_size = 20
        for i in range(0, len(generation), chunk_size):
             yield json.dumps({"type": "token", "content": generation[i:i+chunk_size]}) + "\n"
             import time
             time.sleep(0.02) # Slight delay for effect
             
    except Exception as e:
        print(f"[ERROR] Graph Execution Failed: {e}")
        yield json.dumps({"type": "error", "content": str(e)}) + "\n"   4. **Synthesize Answer**: Answer based on the extracted facts. **CRITICAL**: If an image path was extracted, YOU MUST DISPLAY IT at the end.
    
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
       - Extract the FILENAME from the path (e.g. "image.jpg" from "https://example.com/image.jpg").
       - DISPLAY IT using Markdown syntax: ![Image](/images/<filename>)
       - (Example: ![Image](/images/audi-e-tron.jpg))
    - DO NOT SAY "Here is the image". JUST OUTPUT THE MARKDOWN.
    - If you don't know the answer or the context is insufficient, say "ขออภัยครับ ข้อมูลในระบบยังมีไม่เพียงพอ" and ask specific clarifying questions.
    - If the user's intent is unclear, ask for clarification (e.g. "หมายถึงรุ่นไหนครับ?").
    - Be polite and professional.
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
