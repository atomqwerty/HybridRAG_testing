
import os
import logging
from dotenv import load_dotenv
from langchain_community.graphs import Neo4jGraph

load_dotenv()

logger = logging.getLogger(__name__)


def get_db_connection():
    """Establishes and returns a connection to the Neo4j database."""
    neo4j_uri = os.getenv('NEO4J_URI')
    neo4j_user = os.getenv('NEO4J_USERNAME')
    neo4j_password = os.getenv('NEO4J_PASSWORD')

    if not neo4j_uri:
        raise ValueError("NEO4J_URI not found in environment variables")

    return Neo4jGraph(
        url=neo4j_uri,
        username=neo4j_user,
        password=neo4j_password
    )


def _get_index_dimension(graph, index_name: str):
    """Returns the current vector dimension of a named index, or None if not found.
    Note: Neo4j 5.x SHOW commands don't support $params in WHERE, so we filter in Python.
    """
    try:
        rows = graph.query("SHOW VECTOR INDEXES YIELD name, options RETURN name, options")
        for row in rows:
            if row.get("name") == index_name:
                cfg = row.get("options", {}).get("indexConfig", {})
                return cfg.get("vector.dimensions")
    except Exception as e:
        logger.warning(f"Could not query vector indexes: {e}")
    return None


def _ensure_vector_index(graph, index_name: str, node_label: str, property_name: str, dimensions: int):
    """
    Creates a vector index. If it already exists with different dimensions,
    drops it and recreates it with the correct dimensions.
    """
    existing_dim = _get_index_dimension(graph, index_name)

    if existing_dim is not None and existing_dim != dimensions:
        logger.warning(
            f"Vector index '{index_name}' has {existing_dim}D but need {dimensions}D — "
            f"dropping and recreating."
        )
        try:
            graph.query(f"DROP INDEX `{index_name}` IF EXISTS")
        except Exception as e:
            logger.error(f"Failed to drop index '{index_name}': {e}")

    try:
        graph.query(f"""
        CREATE VECTOR INDEX {index_name} IF NOT EXISTS
        FOR (n:{node_label}) ON (n.{property_name})
        OPTIONS {{indexConfig: {{
            `vector.dimensions`: {dimensions},
            `vector.similarity_function`: 'cosine'
        }}}}
        """)
        logger.info(f"✅ Vector index '{index_name}' ready at {dimensions}D.")
    except Exception as e:
        logger.error(f"Could not create vector index '{index_name}': {e}")


def create_vector_index(graph, dimensions=2560):
    """Creates (or recreates on dimension change) the main chunk vector index."""
    _ensure_vector_index(graph, "chunk_vector_index", "Chunk", "embedding", dimensions)


def create_text_vector_index(graph, dimensions=2560):
    """Creates (or recreates on dimension change) the secondary text vector index."""
    _ensure_vector_index(graph, "text_vector_index", "Chunk", "text_embedding", dimensions)


def create_fulltext_index(graph):
    """Creates fulltext indexes for Entity nodes for keyword search."""
    try:
        graph.query("""
            CREATE FULLTEXT INDEX entity_id_index IF NOT EXISTS
            FOR (n:Entity) ON EACH [n.id]
        """)
        logger.info("✅ Fulltext Index 'entity_id_index' ensured.")
    except Exception as e:
        logger.error(f"Could not create fulltext index: {e}")


def create_constraints(graph):
    """Creates uniqueness constraints to prevent duplicates."""
    try:
        graph.query("CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE")
        logger.info("✅ Constraint 'chunk_id_unique' ensured.")
    except Exception as e:
        logger.error(f"Could not create constraints: {e}")


def get_existing_sources(graph):
    """Returns the set of already-ingested file/URL sources."""
    try:
        data = graph.query("MATCH (c:Chunk) RETURN DISTINCT c.source as source")
        return set(record['source'] for record in data)
    except Exception as e:
        logger.error(f"Could not fetch existing sources: {e}")
        return set()


def clear_database(graph):
    """DANGER: Wipes all data AND drops vector indexes so they rebuild with new dimensions."""
    logger.warning("🧹 Clearing ALL data and vector indexes from Neo4j...")
    graph.query("MATCH (n) DETACH DELETE n")
    # Drop vector indexes so they get recreated with correct dimensions on next startup
    for index_name in ("chunk_vector_index", "text_vector_index"):
        try:
            graph.query(f"DROP INDEX `{index_name}` IF EXISTS")
            logger.info(f"Dropped index '{index_name}'")
        except Exception as e:
            logger.warning(f"Could not drop index '{index_name}': {e}")
    logger.info("✅ Database cleared.")
