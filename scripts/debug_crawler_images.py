
import os
import sys
# Add parent directory to sys.path to allow importing 'app'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../app')))

from app.crawler import load_web_with_images, init_driver
from app.config import Config

# Manually override config if needed for debug
Config.DATA_DIR = "/app/data"

def debug_crawl(url):
    print(f"🔍 DEBUG CRAWL: {url}")
    
    driver = init_driver()
    try:
        driver.get(url)  # Load URL manually first for debug control
        # Wait for potential JS rendering
        print("⏳ Waiting 10 seconds for dynamic content...")
        import time
        time.sleep(10)
        
        # Use existing function logic (it calls get() again internally but that's fine or we pass loaded page)
        # Actually crawler.py load_web_with_images calls driver.get()
        # So wait won't help unless we modify crawler.py OR rely on crawler's internal wait?
        # Crawler has scroll wait.
        
        docs = load_web_with_images(url, driver=driver)
        
        # DEBUG: Save page source to see if image is in DOM
        with open("debug_selenium.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print("✅ Saved Selenium Page Source to debug_selenium.html")
        
        print(f"\n✅ Docs Received: {len(docs)}")
        if docs:
            print(f"Title: {docs[0].metadata.get('title')}")
            print(f"Image Path: {docs[0].metadata.get('image_path')}")
        else:
            print("❌ No docs received.")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        if driver:
            driver.quit()

if __name__ == "__main__":
    target_url = "https://www.ananindustry.com/bmw-ix3.html"
    if len(sys.argv) > 1:
        target_url = sys.argv[1]
    
    debug_crawl(target_url)
