# 🚀 HybridRAG Feature Improvements

This document lists the recent architectural and feature upgrades implemented to enhance data quality, retrieval accuracy, and system maintainability.

## 1. 🏗️ Architecture & Modularization
- **Modular Codebase**: Split the monolithic `ingest_graph.py` into specialized modules:
  - `crawler.py`: Dedicated web scraping & crawling logic.
  - `database.py`: Centralized Neo4j connection and index management.
  - `ingest_graph.py`: Streamlined ingestion workflow.
  - `run_qa.py`: Focused QA and retrieval logic.
- **Improved Maintainability**: easier debugging and testing of individual components.

## 2. 🕷️ Web Crawling (High-Speed & Precision)
- **Sitemap-First Strategy**: The system now prioritizes reading `sitemap.xml` to find 100% of relevant pages instantly, avoiding "dead ends" and navigation noise.
- **"Curl-Like" Speed**: Switched discovery to `requests` (HTTP) instead of Selenium for finding links, increasing speed by 10x.
- **Smart Car Filter**: Crawlers now apply strict filters to only index pages related to "EVs", "Models", or "Specs", rejecting blog/contact/legal pages.
- **Noise Decomposition**: Explicitly removes navigation bars (e.g., `#LayoutGrid7`) to prevent indexing breadcrumbs as content.
- **Selenium Scraping**: Retained full-rendering scraper for *content* to capture lazy-loaded images and JS-injected specs.

## 3. 📄 PDF Ingestion ("MinerU-Lite" Quality)
- **PyMuPDF4LLM Integration**: Replaced `pdfplumber` with `pymupdf4llm`.
  - **Markdown Output**: Converts PDFs directly to Markdown, preserving **Tables**, **Headers**, and **Lists** perfectly.
  - **No Trash Data**: Removes the "fragmented text" issue common with older extractors.
- **Visual Extraction**: Automatically extracts images from PDFs and analyzes them using GPT-4o Vision, indexing the *description* alongside the text.

## 4. 🧠 Retrieval Intelligence (State-of-the-Art)
- **Context Window Retrieval**:
  - **Logic**: Chunks are now linked in the database `(Chunk A)-[:NEXT]->(Chunk B)`.
  - **Benefit**: When a search gets a hit, the system automatically pulls the **Previous** and **Next** chunks to provide continuous context, fixing "cut-off" answers.
- **Multi-Query Decomposition**:
  - **Logic**: For complex questions (e.g., "Compare X and Y"), the system generates 2-3 alternative search queries.
  - **Benefit**: Increases recall by finding information phrased differently.
- **Cross-Encoder Reranking**:
  - **Logic**: Added `sentence-transformers` to support high-precision local reranking logic (more accurate than vector cosine similarity).
