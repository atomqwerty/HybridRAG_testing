
import requests

url = "https://www.ananindustry.com/images/zeerk%2dx%2dflagship%2dawd%2d2024.jpg"
try:
    resp = requests.head(url)
    print(f"URL: {url}")
    print(f"Status: {resp.status_code}")
    print(f"Content-Length: {resp.headers.get('Content-Length')}")
    
    # improved check
    resp = requests.get(url)
    print(f"Actual Size: {len(resp.content)} bytes")
except Exception as e:
    print(e)
