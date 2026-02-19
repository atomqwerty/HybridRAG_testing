import os
import re
import json
import logging
from typing import List, Dict, Generator
from app.config import Config
from app.run_qa import answer
from app.run_qa_stream import answer_stream

logger = logging.getLogger(__name__)

class ChatService:
    """Service to handle chat interactions, history, and agent orchestration."""
    
    _sessions = {}
    
    @classmethod
    def load_sessions(cls):
        """Loads sessions from disk."""
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
        """Persists sessions to disk."""
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
    def process_message(cls, message: str, session_id: str = "default", temperature: float = 0.0) -> Dict:
        """
        Process a single message (blocking).
        Returns: {result: str, context: str, images: list, sources: list}
        """
        history = cls.get_history(session_id)
        
        # Invoke Legacy RAG Logic (which calls graph/agents internally if configured)
        # Ideally we refactor run_qa.answer to call graph directly, but for now we reuse it.
        output = answer(message, history=history, temperature=temperature)
        
        bot_response = output['result']
        context = output['context']
        
        # Update History
        cls.update_history(session_id, message, bot_response)
        
        # Parse Sources & Images (Logic moved from api.py)
        images, sources = cls._parse_artifacts(context)
        
        return {
            "result": bot_response,
            "context": context,
            "images": images,
            "sources": sources
        }

    @classmethod
    def process_stream(cls, message: str, session_id: str = "default") -> Generator[str, None, None]:
        """Generator for streaming response."""
        history = cls.get_history(session_id)
        full_answer = ""
        
        for chunk_str in answer_stream(message, history):
            yield chunk_str
            # Accumulate
            try:
                c = json.loads(chunk_str)
                if c['type'] == 'token':
                    full_answer += c['content']
            except: pass
            
        cls.update_history(session_id, message, full_answer)

    @staticmethod
    def _parse_artifacts(context: str):
        """Extracts [Image Path: ...] and [Source: ...] from context."""
        final_images = []
        valid_sources = []
        
        try:
            sources_list = re.findall(r"\[Source: (.*?), Page: (.*?)\]", context)
            raw_image_paths = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
            
            # Processing Images
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

            # Processing Sources
            for src, pg in sources_list:
                if len(valid_sources) >= 3: break
                src_clean = src.strip()
                source_name = os.path.basename(src_clean)
                valid_sources.append({"file": source_name, "page": pg.strip()})
                
        except Exception as e:
            logger.warning(f"Error parsing artifacts: {e}")
            
        return final_images, valid_sources

# Load sessions on module import
ChatService.load_sessions()
