import requests
import json
import time

API_BASE = "http://localhost:8080/api"

def submit_crawl_job(url, depth=0):
    print(f"🚀 Submitting Crawl Job for: {url} (Depth: {depth})")
    res = requests.post(f"{API_BASE}/crawl", json={"url": [url], "depth": depth})
    if res.status_code == 202:
        job_id = res.json()["job_id"]
        print(f"✅ Job Created: {job_id}")
        return job_id
    else:
        print("❌ Failed:", res.text)
        return None

def poll_status(job_id):
    print(f"\n⏳ Polling status for {job_id}...")
    while True:
        res = requests.get(f"{API_BASE}/crawl/{job_id}")
        data = res.json()
        status = data.get("status")
        
        print(f"Status: {status} | Progress: {data.get('stats', {}).get('pages_crawled', 0)} pages")
        
        if status in ["completed", "failed", "cancelled"]:
            return data
        time.sleep(2)

def demo_queue():
    print("\n--- Queue Management Demo ---")
    print("1. Pausing the queue...")
    requests.post(f"{API_BASE}/crawl/queue/pause")
    
    print("2. Submitting two background jobs...")
    job1 = submit_crawl_job("https://example.com/page1")
    job2 = submit_crawl_job("https://example.com/page2")
    
    print("\n3. Checking queue backlog (jobs should be sitting in 'pending')...")
    queue_res = requests.get(f"{API_BASE}/crawl/queue")
    print(f"Jobs waiting: {len(queue_res.json())}")
    
    print("\n4. Resuming queue (jobs will now start running)...")
    requests.post(f"{API_BASE}/crawl/queue/resume")
    
    print("\n5. Waiting for Job 1 to finish...")
    final_stats = poll_status(job1)
    print("\n🎉 Job 1 Finished Stats:", json.dumps(final_stats["stats"], indent=2))

if __name__ == "__main__":
    demo_queue()
