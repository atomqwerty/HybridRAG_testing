
import os
import re
import json
import time
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# Import from run_qa to reuse Graph/Retrieval logic
from app.run_qa import get_graph, get_embeddings, hybrid_context, get_rag_config
from app.config import Config
from app.logger import setup_logger

logger = setup_logger(__name__)


def answer_stream(question, history="", temperature=0.3, selected_sources=None, is_draft=False):
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
        context = hybrid_context(graph, get_embeddings(), standalone_question, llm_model=dynamic_llm, selected_sources=selected_sources, is_draft=is_draft)
        
        # Load config for system prompt
        rag_cfg = get_rag_config(is_draft=is_draft)
        custom_system_prompt = rag_cfg.get("system_prompt")

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
    - Be polite and professional.
    """
        
        final_template = custom_system_prompt if custom_system_prompt else default_template
        # Ensure variables are present
        if "{context}" not in final_template: final_template += "\n\nContext:\n{context}"
        if "{question}" not in final_template: final_template += "\n\nQuestion: {question}"
        if "{history}" not in final_template: final_template += "\n\nHistory: {history}"

        prompt = ChatPromptTemplate.from_template(final_template)
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
