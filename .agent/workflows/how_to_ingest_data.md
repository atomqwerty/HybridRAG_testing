---
description: How to ingest PDF data into the Hybrid RAG system
---

# Ingesting Data

This workflow describes how to ingest PDF documents into the Neo4j graph database using the `ingest_graph.py` script.

## Prerequisites

1.  **Neo4j Database:** Ensure your local Neo4j database is running.
2.  **Environment Variables:** Verify that your `.env` file contains the correct credentials (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `OpenAi_api`, `OpenAi_api_embbeding`).
3.  **Dependencies:** Ensure all required Python packages are installed (`pip install -r requirements.txt` and `pip install pdfplumber`).
4.  **PDF Files:** Place your PDF documents in the `data/` directory.

## Steps

1.  **Run the Ingestion Script:**
    Open a terminal and navigate to the project root directory. Run the following command:

    ```bash
    python ingest_graph.py
    ```

    This script performs the following actions:
    *   **Connects to Neo4j:** Verifies connection to the database.
    *   **Clears Database:** Removes all existing nodes and relationships (clean slate).
    *   **Loads PDFs:** Uses `PDFPlumberLoader` to extract text from PDFs, preserving table layouts.
    *   **Smart Chunking:** 
        *   Detects tables based on text structure.
        *   Keeps table pages as single chunks.
        *   Splits text pages into smaller chunks for granular search.
    *   **Vector Ingestion:** Creates embeddings for all chunks and stores them in Neo4j.
    *   **Graph Extraction:** Uses an LLM to extract entities and relationships from the text chunks.
    *   **Linking:** Creates `HAS_ENTITY` relationships between Chunks and extracted Entities.
    *   **Post-Processing:**
        *   Merges duplicate entities.
        *   Runs Community Detection (Louvain) to enrich the graph.

2.  **Verify Ingestion:**
    Once the script prints "🎉 Ultimate Ingestion Complete!", you can verify the data in Neo4j Browser or by running `run_qa.py`.

3.  **Run QA:**
    Execute the QA script to test the system:

    ```bash
    python run_qa.py
    ```

    Ask questions like "Who won the 2022 season?" or "How many points did Max Verstappen get?".
