"""
Text Agent — Thin wrapper around the existing hybrid RAG pipeline in run_qa.py.

Preserves 100% backward compatibility. All existing retrieval logic
(Hybrid Search, Graph Context, Reranking, Grading) is reused unchanged.
"""
from app.logger import setup_logger
from app.run_qa import answer, get_graph
import os
import re

logger = setup_logger(__name__)


class TextAgent:
    """Delegates to the existing `answer()` function in run_qa.py."""

    def run(self, query: str, history: str = "", temperature: float = 0.0, selected_sources: list = None) -> dict:
        """
        Args:
            query:       The user's question (may be pre-optimized by Supervisor).
            history:     Chat history string.
            temperature: LLM temperature.

        Returns:
            {
                "result": str,
                "context": str,
                "images": list,
                "sources": list,
                "agent": "text"
            }
        """
        try:
            output = answer(query, history=history, temperature=temperature, selected_sources=selected_sources)
            result = output.get("result", "")
            context = output.get("context", "")

            images, sources = self._parse_artifacts(context)

            return {
                "result": result,
                "context": context,
                "images": images,
                "sources": sources,
                "agent": "text"
            }
        except Exception as e:
            logger.error(f"[TextAgent] Failed: {e}")
            return {
                "result": f"Sorry, I encountered an error: {e}",
                "context": "",
                "images": [],
                "sources": [],
                "agent": "text"
            }

    @staticmethod
    def _parse_artifacts(context: str):
        """Extracts image paths and sources from context string."""
        images = []
        sources = []
        try:
            raw_imgs = re.findall(r"\[IMAGE PATH: (.*?)\]", context)
            seen = set()
            for img in raw_imgs:
                img = img.strip()
                if img not in seen:
                    seen.add(img)
                    norm = img.replace("\\", "/")
                    rel = norm.split("data/")[-1] if "data/" in norm else os.path.basename(norm)
                    images.append(rel)
            images = images[:2]

            for src, pg in re.findall(r"\[Source: (.*?), Page: (.*?)\]", context):
                if len(sources) >= 3: break
                sources.append({"file": os.path.basename(src.strip()), "page": pg.strip()})
        except Exception as e:
            logger.warning(f"[TextAgent] Artifact parse error: {e}")
        return images, sources


# Module-level singleton
_text_agent = TextAgent()


def run(query: str, history: str = "", temperature: float = 0.0, selected_sources: list = None) -> dict:
    return _text_agent.run(query, history, temperature, selected_sources=selected_sources)
