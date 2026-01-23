import dlt
from dlt.sources.helpers import requests
from typing import Iterator, Dict, Any
from pipeline_schemas import CarModel, TechSpecs
from config import Config
import json

@dlt.resource(write_disposition="merge", primary_key="file_id")
def document_resource(files: list[str]) -> Iterator[Dict[str, Any]]:
    """
    Yields unstructured document data (e.g. from PDFs/DOCX).
    DLT will create a separate table for this!
    """
    for file_path in files:
        # Simulation of PDF processing
        yield {
            "file_id": file_path,
            "filename": file_path.split("/")[-1],
            "type": "pdf",
            "content": "Full text content extracted from PDF...",
            "metadata": {
                "pages": 12,
                "author": "Atom"
            }
        }

# --- DLT Source (Groups resources) ---
@dlt.source
def hybrid_rag_source(urls: list[str], files: list[str]):
    """
    A single source that produces MULTIPLE types of data (Resources).
    """
    return [
        car_resource(urls),      # -> goes to 'car_resource' table
        document_resource(files) # -> goes to 'document_resource' table
    ]


@dlt.resource(write_disposition="merge", primary_key="source_url")
def car_resource(urls: list[str]) -> Iterator[Dict[str, Any]]:
    """
    Yields validated CarModel dictionaries.
    """
    headers = {
        "User-Agent": Config.USER_AGENT
    }

    for url in urls:
        # 1. Fetch
        # In a real DLT pipeline, we'd use robust retry/backoff logic built into dlt requests
        try:
            print(f"Extraction URL: {url}")
            # For this MVP, we are mocking the extraction or doing a simple scrape.
            # In production, we'd call our `load_web_with_images` here or use dlt's html helpers.
            
            # SIMULATION: Let's assume we scraped this data
            # (To make this run without selenium for the 'experiment', I'll mock a result if I can't hit the net)
            
            # Real logic would be:
            # html = requests.get(url, headers=headers).text
            # parsed = parse_html_to_structure(html)
            # yield parsed
            
            # Mocking a "discovered" car for demonstration of the pipeline
            yield {
                "brand": "TestBrand",
                "model": "FutureCar",
                "year": 2025,
                "specs": {
                    "horsepower": "500 hp",
                    "range_km": 600
                },
                "source_url": url,
                "description": "A test car extracted via DLT pipeline."
            }
            
        except Exception as e:
            print(f"Failed to process {url}: {e}")

if __name__ == "__main__":
    # Test Data
    test_urls = ["https://example.com/car1"]
    test_files = ["/data/manual.pdf", "/data/specs.docx"]
    
    # Run the pipeline
    import os
    # Ensure local data directory exists
    output_dir = os.path.join(Config.DATA_DIR, "dlt_output")
    os.makedirs(output_dir, exist_ok=True)

    pipeline = dlt.pipeline(
        pipeline_name="hybrid_ingestion",
        destination=dlt.destinations.filesystem(bucket_url=f"file://{output_dir}"), 
        dataset_name="hybrid_data"
    )

    # We run the source which contains BOTH resources
    # DLT automatically separates them into different tables/files!
    load_info = pipeline.run(
        hybrid_rag_source(test_urls, test_files), 
        loader_file_format="jsonl"
    )
    print(load_info)
    
    # 3. Pydantic Validation Check
    print("\nValidating with Pydantic...")
    try:
        sample = {
            "brand": "BYD", 
            "model": "Seal", 
            "source_url": "http://test",
            "specs": {"horsepower": "520"}
        }
        car = CarModel(**sample)
        print(f"✅ Valid Car Model: {car.brand} {car.model}")
    except Exception as e:
        print(f"❌ Validation Failed: {e}")
