# Project Updates Summary

## 1. Code Restructuring
The massive reorganization improved project cleanliness and maintainability.
- **New Structure**:
    - **`app/`**: Contains all Python application code (`api.py`, `ingest_dlt.py`, `crawler.py`, etc.).
    - **`scripts/`**: Contains helper shell scripts (e.g., `setup_colivare.sh`).
    - **`data/`**: Stores runtime data, `urls.txt`, and generated artifacts.
    - **Root**: Cleaned up to contain only config (`source_config.json`, `ingest_status.json`) and standard files (`README.md`, `requirements.txt`).
- **Imports Updated**: `app/config.py` was refactored to look up one directory level (`BASE_DIR = parent of app`) so it correctly finds root configuration files.

## 2. Ingestion Pipeline Fixes (`ingest_dlt.py` & `crawler.py`)
Several critical bugs preventing ingestion were resolved:

### A. Missing Logic & NameErrors
- **`hybrid_rag_source`**: Implemented the missing DLT source function in `ingest_dlt.py`.
- **`update_status`**: 
    - Moved to `app/utils.py` to allow shared use.
    - Updated signature to `(message, percent, status=None)` to match usage calls.
    - Fixed a `TypeError` where percentage string was compared to integer.

### B. Dependencies
- **Removed**: `semantic-router` and `langchain-neo4j` were removed from `requirements.txt` as they were causing install errors and weren't strictly required (code had fallback logic).

### C. Selenium / Chrome Crawler
- **Driver Installation**: Patched `crawler.py` to use `webdriver-manager` instead of a hardcoded `/usr/bin/chromedriver` path.
- **Browser Binary**: Installed Google Chrome Stable (`v144`) using a custom script to resolve "cannot find Chrome binary" errors.
- **Image Extraction Path**: Fixed logic in `crawler.py` to successfully save images to `data/extracted_images/` using absolute paths (`Config.DATA_DIR`), resolving the issue where images were dumped in `data/`.

### D. Permissions
- **Root Ownership Fix**: Reclaimed ownership of `log/` and `data/` directories (which were owned by `root`) using `sudo chown`.

## 3. Configuration & Status Files
- **`ingest_status.json`**:
    - Moved to the **Project Root** (verified by `api.py` and `utils.py`).
    - Used by the frontend to track real-time ingestion progress.
- **`source_config.json`**:
    - Moved to the **Project Root**.
    - Stores trust rules (domains/files) and reliability scores.
- **`auto_add_trust_rule`**: Fixed `TypeError` by updating the function signature in `utils.py` to accept `score` and `rule_type` arguments.

## 4. Summary of Removed Files
- `debug_path.py` (Temporary debug script)
- `install_chrome.sh` (One-time installer)
- `google-chrome-stable...deb` (Installer binary)
- `package-lock.json` (Root level orphan)

---
**Current Status**: The application is fully functional. You can run the ingestion pipeline from the `app/` directory:
```bash
cd app
python3 ingest_dlt.py
```
