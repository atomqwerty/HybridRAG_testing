"""
Supervisor Agent — Classifies user intent and extracts an optimized query.

Output schema:
    {
        "intent": "visual" | "table" | "text",
        "query": "<refined search query>",
        "entity": "<car model name or None>"
    }
"""
import json
import re
from app.config import Config
from app.logger import setup_logger
from langchain_openai import ChatOpenAI

logger = setup_logger(__name__)

# Keyword-based fast prefilter so we avoid an LLM call for obvious cases.
_VISUAL_KEYWORDS = [
    "show", "image", "photo", "picture", "look like", "interior", "exterior",
    "รูป", "รูปภาพ", "หน้าตา", "ดูรูป", "ภาพ"
]
_TABLE_KEYWORDS = [
    "compare", "comparison", "table", "spec", "specs", "battery", "range",
    "capacity", "price", "weight", "dimension", "vs", "versus",
    "เปรียบเทียบ", "ตาราง", "สเปก", "ราคา", "น้ำหนัก"
]
_GREETING_KEYWORDS = [
    "hello", "hi", "hey", "สวัสดี", "ดีครับ", "ดีค่ะ", "หวัดดี",
    "thanks", "thank you", "ขอบคุณ", "เยี่ยม", "โอเค", "ok"
]

# Common car model extraction patterns
_MODEL_PATTERNS = [
    r'\b(byd\s+\w+[\s\w]*)',
    r'\b(mg\s+\w+[\s\w]*)',
    r'\b(xpeng\s+\w+[\s\w]*)',
    r'\b(tesla\s+\w+[\s\w]*)',
    r'\b(zeekr\s+\w+[\s\w]*)',
    r'\b(atto\s*3)\b',
    r'\b(han\s+ev)\b',
    r'\b(seal[\s\w]*)\b',
    r'\b(dolphin[\s\w]*)\b',
    r'\b(p7[\s\w]*)\b',
    r'\b(g9[\s\w]*)\b',
]


def _keyword_classify(question: str) -> str | None:
    """Fast keyword pre-filter. Returns intent string or None if ambiguous."""
    q = question.lower().strip()
    # Short greetings / chit-chat — skip classification entirely
    if any(kw in q for kw in _GREETING_KEYWORDS) and len(q.split()) <= 5:
        return "text"
    if any(kw in q for kw in _VISUAL_KEYWORDS):
        return "visual"
    if any(kw in q for kw in _TABLE_KEYWORDS):
        return "table"
    return None


def _extract_entity(question: str) -> str | None:
    """Extracts the first car model name from the question using regex."""
    q = question.lower()
    for pattern in _MODEL_PATTERNS:
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            return m.group(1).strip().title()
    return None


class Supervisor:
    """
    Routes user intent to the correct specialist agent.
    Uses a fast keyword check first; falls back to LLM classification.
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=Config.OPENAI_API_KEY,
                base_url=Config.OPENAI_BASE_URL,
                model=Config.OPENAI_MODEL,
                temperature=0
            )
        return self._llm

    def classify(self, question: str) -> dict:
        """
        Returns:
            {
                "intent": "visual" | "table" | "text",
                "query": str,       # optimized sub-query
                "entity": str | None  # extracted car model name
            }
        """
        entity = _extract_entity(question)

        # 1. Fast keyword check
        intent = _keyword_classify(question)
        if intent:
            logger.info(f"[Supervisor] Keyword classified → {intent} | entity={entity}")
            return {"intent": intent, "query": question, "entity": entity}

        # 2. LLM classification fallback
        try:
            llm = self._get_llm()
            prompt = f"""Classify the following user question into one of three categories:
- "visual": asks to see an image, photo, or visual of something
- "table": asks to compare, list specs, prices, or numerical data
- "text": general knowledge, how-to, explanation, or other

Also extract the car model name if present (e.g. "BYD Atto 3", "MG ZS EV").
Also rewrite the question as a concise search query (remove pleasantries).

Respond ONLY as valid JSON with keys: intent, query, entity (null if no model).

Question: {question}
"""
            response = llm.invoke(prompt).content.strip()
            # Strip markdown code fences if any
            response = re.sub(r"^```json\s*|```$", "", response, flags=re.MULTILINE).strip()
            parsed = json.loads(response)
            intent = parsed.get("intent", "text")
            query = parsed.get("query", question)
            entity = parsed.get("entity") or entity
            logger.info(f"[Supervisor] LLM classified → {intent} | entity={entity} | query={query}")
            return {"intent": intent, "query": query, "entity": entity}
        except Exception as e:
            logger.warning(f"[Supervisor] LLM classification failed: {e}. Defaulting to 'text'.")
            return {"intent": "text", "query": question, "entity": entity}


# Global singleton
_supervisor = Supervisor()


def classify(question: str) -> dict:
    """Module-level helper for easy import."""
    return _supervisor.classify(question)
