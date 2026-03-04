import os
import re
import json
import logging
import threading
from typing import List, Dict, Generator
from app.config import Config
from app.run_qa import answer
from app.run_qa_stream import answer_stream

logger = logging.getLogger(__name__)


class ChatService:
    """Service to handle chat interactions, history, and multi-agent orchestration."""

    _sessions = {}
    _lock = threading.Lock()  # protect concurrent session saves

    @classmethod
    def load_sessions(cls):
        if os.path.exists(Config.SESSION_FILE):
            try:
                with open(Config.SESSION_FILE, 'r') as f:
                    cls._sessions = json.load(f)
                logger.info(f"Loaded {len(cls._sessions)} sessions.")
            except Exception as e:
                logger.error(f"Failed to load sessions: {e}")
                cls._sessions = {}

    @classmethod
    def save_sessions(cls):
        with cls._lock:
            try:
                with open(Config.SESSION_FILE, 'w') as f:
                    json.dump(cls._sessions, f, indent=4)
            except Exception as e:
                logger.error(f"Failed to save sessions: {e}")

    @classmethod
    def get_history(cls, session_id: str) -> str:
        return cls._sessions.get(session_id, "")

    @classmethod
    def update_history(cls, session_id: str, user_msg: str, bot_msg: str):
        if session_id not in cls._sessions:
            cls._sessions[session_id] = ""
        cls._sessions[session_id] += f"User: {user_msg}\nBot: {bot_msg}\n"
        cls.save_sessions()

    @classmethod
    def process_message(cls, message: str, session_id: str = "default", temperature: float = 0.0, selected_sources: List[str] = None) -> Dict:
        """
        Multi-Agent orchestration:
          1. Supervisor classifies intent → visual | table | text
          2. Dispatch to ImageAgent, TableAgent, or TextAgent
          3. Build unified response dict
        """
        history = cls.get_history(session_id)
        output = None

        # --- Supervisor routing ---
        try:
            from app.agents.supervisor import classify
            route = classify(message)
            intent = route.get("intent", "text")
            sub_query = route.get("query", message)
            entity = route.get("entity")
            logger.info(f"[ChatService] Supervisor → intent={intent}, entity={entity}")

            if intent == "visual":
                from app.agents.image_agent import run as image_run
                output = image_run(sub_query, entity)
                if not output.get("result"):
                    output["result"] = (
                        f"Here are the images I found for **{entity or sub_query}**."
                        if output.get("images")
                        else "I couldn't find any matching images. Try rephrasing your query."
                    )

            elif intent == "table":
                from app.agents.table_agent import run as table_run
                output = table_run(sub_query)

            else:
                from app.agents.text_agent import run as text_run
                output = text_run(sub_query, history=history, temperature=temperature, selected_sources=selected_sources)

        except Exception as e:
            logger.error(f"[ChatService] Multi-agent dispatch failed: {e}. Falling back to legacy answer().")
            output = None

        # --- Legacy fallback ---
        if output is None:
            raw = answer(message, history=history, temperature=temperature, selected_sources=selected_sources)
            images, sources = cls._parse_artifacts(raw.get("context", ""))
            output = {
                "result": raw.get("result", ""),
                "context": raw.get("context", ""),
                "images": images,
                "sources": sources,
                "agent": "legacy"
            }

        bot_response = output.get("result", "")
        cls.update_history(session_id, message, bot_response)

        return {
            "result": bot_response,
            "context": output.get("context", ""),
            "images": output.get("images", []),
            "sources": output.get("sources", []),
            "agent": output.get("agent", "unknown")
        }

    @classmethod
    def process_stream(cls, message: str, session_id: str = "default", temperature: float = 0.0, selected_sources: List[str] = None) -> Generator[str, None, None]:
        """
        Streaming response with full Supervisor routing and "thought" updates.

        Protocol:
          {type: thought, content}                ← reasoning/status updates
          {type: meta, agent, sources, images}    ← emitted before content
          {type: token, content}                  ← streamed tokens
          {type: done}                            ← end sentinel
          {type: error, content}                  ← on fatal failure
        """
        import json as _json

        history = cls.get_history(session_id)
        full_answer = ""

        # --- 1. Classify intent ---
        yield _json.dumps({"type": "thought", "content": "Analyzing your question..."}) + "\n"
        try:
            from app.agents.supervisor import classify
            route = classify(message)
            intent   = route.get("intent", "text")
            sub_query = route.get("query", message)
            entity    = route.get("entity")
            logger.info(f"[ChatService.stream] Supervisor → intent={intent}, entity={entity}")
            
            if intent == "visual":
                yield _json.dumps({"type": "thought", "content": f"Searching for images of {entity or 'the car'}..."}) + "\n"
            elif intent == "table":
                yield _json.dumps({"type": "thought", "content": "Comparing specifications and data..."}) + "\n"
            else:
                yield _json.dumps({"type": "thought", "content": "Searching relevant documents..."}) + "\n"

        except Exception as e:
            logger.warning(f"[ChatService.stream] Supervisor failed: {e}. Falling back to text.")
            intent, sub_query, entity = "text", message, None

        # --- 2a. Visual / Table: run sync agent, then fake-stream ---
        if intent in ("visual", "table"):
            try:
                if intent == "visual":
                    from app.agents.image_agent import run as img_run
                    output = img_run(sub_query, entity)
                    if not output.get("result"):
                        output["result"] = (
                            f"Here are the images I found for **{entity or sub_query}**."
                            if output.get("images")
                            else "I couldn't find any matching images. Try a different query."
                        )
                else:
                    from app.agents.table_agent import run as tbl_run
                    output = tbl_run(sub_query)

                # Emit meta (sources + images)
                yield _json.dumps({
                    "type":    "meta",
                    "agent":   output.get("agent", intent),
                    "sources": output.get("sources", []),
                    "images":  output.get("images", []),
                }) + "\n"

                # Fake-stream the result text in ~60-char chunks
                result_text = output.get("result", "")
                chunk_size = 60
                for i in range(0, len(result_text), chunk_size):
                    yield _json.dumps({"type": "token", "content": result_text[i:i+chunk_size]}) + "\n"
                full_answer = result_text

                yield _json.dumps({"type": "done"}) + "\n"

            except Exception as e:
                logger.error(f"[ChatService.stream] {intent} agent failed: {e}")
                yield _json.dumps({"type": "error", "content": f"⚠️ Agent error: {e}"}) + "\n"

        # --- 2b. Text: true LLM streaming ---
        else:
            for chunk_str in answer_stream(sub_query, history, temperature=temperature, selected_sources=selected_sources):
                try:
                    c = _json.loads(chunk_str)
                    if c.get("type") == "meta":
                        c["agent"] = "text"
                        yield _json.dumps(c) + "\n"
                    else:
                        yield chunk_str
                        if c.get("type") == "token":
                            full_answer += c.get("content", "")
                except Exception:
                    yield chunk_str

        cls.update_history(session_id, message, full_answer)

    @staticmethod
    def _parse_artifacts(context: str):
        """Extracts image paths and source citations from context string."""
        final_images = []
        valid_sources = []
        try:
            raw_image_paths = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
            seen_imgs = set()
            for img_p in raw_image_paths:
                img_p = img_p.strip()
                if img_p not in seen_imgs:
                    seen_imgs.add(img_p)
                    norm_path = img_p.replace('\\', '/')
                    if 'data/' in norm_path:
                        rel_path = norm_path.split('data/')[-1]
                        if rel_path.startswith('/'): rel_path = rel_path[1:]
                    else:
                        rel_path = os.path.basename(norm_path)
                        if ('web_' in rel_path or 'extracted_' in rel_path) and 'extracted_images' not in rel_path:
                            rel_path = f"extracted_images/{rel_path}"
                    final_images.append(rel_path)
            final_images = final_images[:2]

            for src, pg in re.findall(r"\[Source: (.*?), Page: (.*?)\]", context):
                if len(valid_sources) >= 3: break
                valid_sources.append({"file": os.path.basename(src.strip()), "page": pg.strip()})
        except Exception as e:
            logger.warning(f"Error parsing artifacts: {e}")
        return final_images, valid_sources


# Load sessions on module import
ChatService.load_sessions()
