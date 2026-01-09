import glob
from langchain_community.document_loaders import PyPDFLoader

def debug_pdf():
    pdf_files = glob.glob("data/*.pdf")
    if not pdf_files:
        print("No PDFs found.")
        return

    # Just pick the first one
    pdf_file = pdf_files[0]
    print(f"📄 Inspecting: {pdf_file}")
    
    loader = PyPDFLoader(pdf_file)
    pages = loader.load()
    
    print(f"   Found {len(pages)} pages.")
    
    # Print the first 1000 characters of page 1 (or wherever likely data is)
    # The user is asking about points, which usually appears in later pages or summary tables.
    # Let's just print a random sample or loop through to find "Points"
    
    found_table = False
    for i, page in enumerate(pages):
        text = page.page_content
        if "Points" in text or "Pos" in text:
            print(f"\n--- Possible Table on Page {i+1} ---")
            print(text[:2000]) # Print first 2000 chars
            found_table = True
            break
    
    if not found_table:
        print("Could not find obvious table keywords in the first pass.")
        # Fallback print first page
        print("\n--- Page 1 Content ---")
        print(pages[0].page_content[:1000])

if __name__ == "__main__":
    debug_pdf()
