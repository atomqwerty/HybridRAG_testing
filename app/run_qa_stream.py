
import os
import re
import json
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv

# Import from run_qa to reuse Graph/Retrieval logic
# Import from run_qa (graph global removed, use get_graph)
from app.run_qa import get_graph, embeddings, hybrid_context

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
    
    # --- Step 2: Retrieve ---
    # This is the blocking part (2-3s)
    graph = None
    import time
    for attempt in range(3):
        try:
            graph = get_graph()
            if graph:
                print(f"[INFO] Connection Successful (Attempt {attempt+1})")
                break
        except Exception as e:
            print(f"[WARN] Connection Failed (Attempt {attempt+1}): {e}")
            time.sleep(2)
    
    if not graph:
        yield json.dumps({"type": "token", "content": "System Initializing... Please wait 5 seconds and try again."}) + "\n"
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
