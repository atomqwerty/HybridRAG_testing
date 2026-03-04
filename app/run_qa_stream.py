
import os
import re
import json
import time
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import from run_qa to reuse Graph/Retrieval logic
from app.run_qa import get_graph, get_embeddings, hybrid_context
from app.config import Config
from app.logger import setup_logger

logger = setup_logger(__name__)


def answer_stream(question, history="", temperature=0.3, selected_sources=None):
    """
    Generator function that yields streaming responses as NDJSON.
    Protocol:
    1. Yields metadata (sources/images) first as {"type": "meta", ...}
    2. Yields text tokens as {"type": "token", "content": "..."}
    3. Yields {"type": "done"} at end
    4. Yields {"type": "error", "content": "..."} on failure
    """
    try:
        # Create dynamic LLM using Config (same as run_qa.py)
        dynamic_llm = ChatOpenAI(
            api_key=Config.OPENAI_API_KEY,
            base_url=Config.OPENAI_BASE_URL,
            model=Config.OPENAI_MODEL,
            temperature=temperature
        )

        # --- Step 1: Condense Question ---
        standalone_question = question
        if history:
            yield json.dumps({"type": "thought", "content": "Refining your follow-up question..."}) + "\n"
            condense_template = """Given chat history and follow-up, rephrase to standalone question.
            IMPORTANT: Preserve any specific model numbers or names (e.g. 009, Atto 3, Model Y). DO NOT generalize "Zeekr 009" to just "Zeekr".
            Chat History: {history}
            Follow Up: {question}
            Standalone:"""
            condense_prompt = ChatPromptTemplate.from_template(condense_template)
            standalone_question = dynamic_llm.invoke(
                condense_prompt.format(history=history, question=question)
            ).content

        # --- Step 2: Connect to Graph ---
        graph = None
        for attempt in range(3):
            try:
                graph = get_graph()
                if graph:
                    logger.info(f"Stream connection OK (attempt {attempt+1})")
                    break
            except Exception as e:
                logger.warning(f"Stream connection failed (attempt {attempt+1}): {e}")
                time.sleep(2)

        if not graph:
            yield json.dumps({"type": "error", "content": "⚠️ System initializing… please try again in 5 seconds."}) + "\n"
            return

        # --- Step 3: Retrieve Context ---
        yield json.dumps({"type": "thought", "content": "Searching knowledge base and retrieving context..."}) + "\n"
        context = hybrid_context(graph, get_embeddings(), standalone_question, llm_model=dynamic_llm, selected_sources=selected_sources)

        # --- Parse metadata ---
        sources = []
        seen_sources = set()
        for src, pg in re.findall(r"\[Source: (.*?), Page: (.*?)\]", context):
            if (src, pg) not in seen_sources:
                sources.append({"file": os.path.basename(src), "page": pg})
                seen_sources.add((src, pg))

        images = []
        for p in re.findall(r"\[IMAGE PATH: (.*?)\]", context):
            images.append(os.path.basename(p))

        yield json.dumps({"type": "meta", "sources": sources[:3], "images": images[:2]}) + "\n"
        yield json.dumps({"type": "thought", "content": "Thinking and generating answer..."}) + "\n"

        # --- Step 4: Stream LLM Response ---
        template = """You are an intelligent Thai AI assistant (Hybrid RAG).

    # 1. AMBIGUITY CHECK (Execute in Order):

    - RULE 1 [BRAND ONLY]: IF the user mentions ONLY a brand (e.g., "Audi", "Tesla") with NO specific model variant:
      STOP.
      Check the {context} for available models of that brand.
      Reply ONLY: "ขอทราบรุ่น [Brand Name] ที่ท่านสนใจครับ? (ในระบบมีข้อมูล: [List models found in context])"

    - RULE 2 [MODEL FOUND / MULTIPLE VERSIONS]: IF the user provides a model but there are multiple versions:
      PROCEED to Context Refinement.

    - RULE 3 [MODEL NOT FOUND]: IF the model name does not appear in context:
      STOP. Reply: "ขออภัยครับ ไม่พบข้อมูลสำหรับรุ่น '[User Model]' ในระบบ"

    # 2. CONTEXT REFINEMENT:
    1. Analyze the request and identify the specific car model.
    2. Filter context — ignore chunks not matching the model.
    3. Extract facts, specs, and any [IMAGE PATH: ...].
    4. Synthesize answer. If image path found, display: ![Image](/api/images/<filename>)

    Context:
    {context}

    History: {history}
    Question: {question}

    Rules:
    - ANSWER IN THAI LANGUAGE ONLY (use 'ครับ' or 'ค่ะ').
    - Cite source page (e.g. [Page 5]).
    - Do NOT say "Here is the image" — just output the Markdown.
    - If context is insufficient, say "ขออภัยครับ ข้อมูลในระบบยังมีไม่เพียงพอ".
    - Be polite and professional.
    """
        prompt = ChatPromptTemplate.from_template(template)
        chain = (prompt | dynamic_llm | StrOutputParser())

        for chunk in chain.stream({
            "history": history,
            "context": context,
            "question": standalone_question
        }):
            yield json.dumps({"type": "token", "content": chunk}) + "\n"

        yield json.dumps({"type": "done"}) + "\n"

    except Exception as e:
        logger.error(f"[answer_stream] Fatal error: {e}")
        yield json.dumps({"type": "error", "content": f"⚠️ ขออภัย เกิดข้อผิดพลาด: {str(e)}"}) + "\n"
