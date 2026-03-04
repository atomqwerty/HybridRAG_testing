"""
Image Agent — Finds the correct image using a 2-step pipeline:
    1. Graph Filter: Find the exact Car/Entity node by model name.
    2. Filtered Vector Search: Semantic search restricted to that node's source IDs.

This eliminates cross-model image contamination (e.g., returning an MG image
when asking about the BYD Atto 3).
"""
from app.config import Config
from app.logger import setup_logger
from app.run_qa import get_graph, get_embeddings

logger = setup_logger(__name__)


class ImageAgent:
    """
    Two-step image retrieval:
      Step 1 - graph_filter: identify source IDs linked to the requested entity.
      Step 2 - vector_search: semantic search restricted to those source IDs.
    """

    def run(self, query: str, entity: str | None = None, k: int = 6) -> dict:
        """
        Args:
            query:  The full user query (e.g. "show me the red interior of Atto 3")
            entity: Extracted model name (e.g. "BYD Atto 3") or None
            k:      Number of image results to return

        Returns:
            {
                "images": ["/api/images/file.jpg", ...],
                "context": "...text context...",
                "sources": [...]
            }
        """
        graph = get_graph()

        # --- Step 1: Graph Filter ---
        source_ids = self._graph_filter(graph, entity) if entity else []

        if source_ids:
            logger.info(f"[ImageAgent] Graph filter found {len(source_ids)} source IDs for '{entity}'")
        else:
            logger.info(f"[ImageAgent] No graph filter match for '{entity}' — falling back to unfiltered search")

        # --- Step 2: Vector Search (filtered or open) ---
        results = self._vector_search(graph, query, source_ids, k=k)

        # --- Format output ---
        images = []
        context_parts = []
        sources = []
        seen_imgs = set()

        for row in results:
            img = row.get("image_path")
            if img:
                # Normalise to API path
                fname = img.split("/")[-1] if "/" in img else img
                api_path = f"/api/images/{fname}"
                if api_path not in seen_imgs:
                    images.append(api_path)
                    seen_imgs.add(api_path)

            text = row.get("text", "")
            src = row.get("source", "")
            pg = row.get("page", "?")
            if text:
                context_parts.append(f"- {text} [Source: {src}, Page: {pg}]\n [IMAGE PATH: /api/images/{row.get('image_path', '').split('/')[-1]}]")
            if src:
                sources.append({"file": src.split("/")[-1], "page": str(pg)})

        context = "\n".join(context_parts) if context_parts else "No matching images found."

        return {
            "images": images[:3],          # cap at 3 images
            "context": context,
            "sources": sources[:3],
            "agent": "image",
            "entity_used": entity
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _graph_filter(self, graph, entity: str) -> list[str]:
        """
        Runs a fuzzy fulltext search on Car/Entity nodes to get their source IDs.
        Returns a list of source strings that belong to this model.
        """
        try:
            # Fuzzy match on Car nodes first (they have model-level metadata)
            results = graph.query(
                """
                CALL db.index.fulltext.queryNodes("entity_id_index", $query, {limit: 5})
                YIELD node, score
                RETURN node.id AS id, node.source AS source, node.source_url AS url, labels(node) AS labels
                """,
                {"query": f"{entity}~"}
            )
            # Collect any source references from matching nodes
            sources = set()
            for row in results:
                if row.get("source"): sources.add(row["source"])
                if row.get("url"):    sources.add(row["url"])
                if row.get("id"):     sources.add(row["id"])

            # Also search Chunk nodes directly for this model name
            chunk_results = graph.query(
                """
                CALL db.index.fulltext.queryNodes("chunk_text_index", $query, {limit: 10})
                YIELD node, score
                RETURN node.source AS source
                """,
                {"query": f"{entity}~"}
            )
            for row in chunk_results:
                if row.get("source"): sources.add(row["source"])

            return list(sources)
        except Exception as e:
            logger.warning(f"[ImageAgent] Graph filter failed: {e}")
            return []

    def _vector_search(self, graph, query: str, source_ids: list, k: int = 6) -> list:
        """
        Semantic vector search on the text_vector_index.
        If source_ids is provided, restricts search to those sources.
        Returns chunks that have an image_path.
        """
        try:
            q_embedding = get_embeddings().embed_query(query)

            if source_ids:
                # Filtered search — only chunks belonging to the matched entity
                results = graph.query(
                    """
                    CALL db.index.vector.queryNodes('text_vector_index', $k, $embedding)
                    YIELD node, score
                    WHERE score >= 0.4
                      AND node.source IN $sources
                      AND node.image_path IS NOT NULL
                      AND node.image_path <> ''
                    RETURN node.text AS text,
                           node.source AS source,
                           node.page AS page,
                           node.image_path AS image_path,
                           score
                    ORDER BY score DESC
                    LIMIT $k
                    """,
                    {"embedding": q_embedding, "k": k * 2, "sources": source_ids}
                )
            else:
                # Unfiltered fallback — boost vision-modality chunks
                results = graph.query(
                    """
                    CALL db.index.vector.queryNodes('text_vector_index', $k, $embedding)
                    YIELD node, score
                    WHERE score >= 0.4
                      AND node.image_path IS NOT NULL
                      AND node.image_path <> ''
                    RETURN node.text AS text,
                           node.source AS source,
                           node.page AS page,
                           node.image_path AS image_path,
                           score
                    ORDER BY score DESC
                    LIMIT $k
                    """,
                    {"embedding": q_embedding, "k": k * 2}
                )
            return results or []
        except Exception as e:
            logger.error(f"[ImageAgent] Vector search failed: {e}")
            return []


# Module-level singleton
_image_agent = ImageAgent()


def run(query: str, entity: str | None = None) -> dict:
    return _image_agent.run(query, entity)
