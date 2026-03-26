import uuid
import time
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from app.config import Config
from app.crawler import get_internal_links, load_web_with_images
from app.logger import setup_logger
from app.utils import auto_add_trust_rule

logger = setup_logger(__name__)

class CrawlService:
    _jobs = {}
    _lock = threading.Lock()
    _executor = ThreadPoolExecutor(max_workers=5)
    _history_file = os.path.join(Config.DATA_DIR, "crawl_history.json")
    _results_dir = os.path.join(Config.DATA_DIR, "crawl_results")
    _loaded = False
    _queue_paused = False

    @classmethod
    def _save_history(cls):
        with cls._lock:
            try:
                with open(cls._history_file, "w") as f:
                    json.dump(cls._jobs, f, indent=2, default=str)
            except Exception as e:
                logger.error(f"Failed to save crawl history: {e}")

    @classmethod
    def _load_history(cls, force=False):
        if cls._loaded and not force:
            return
        with cls._lock:
            if os.path.exists(cls._history_file):
                try:
                    if os.path.getsize(cls._history_file) > 0:
                        with open(cls._history_file, "r") as f:
                            data = json.load(f)
                            # Merge instead of overwrite to preserve current session jobs
                            cls._jobs.update(data)
                    cls._loaded = True
                except Exception as e:
                    logger.error(f"Failed to load crawl history: {e}")
                    if not cls._jobs: cls._jobs = {}

    @classmethod
    def create_job(cls, urls, config):
        cls._load_history()
        job_id = str(uuid.uuid4())
        job = {
            "job_id": job_id,
            "status": "pending",
            "urls": urls if isinstance(urls, list) else [urls],
            "config": config,
            "created_at": datetime.now().isoformat(),
            "results": [],
            "stats": {
                "pages_crawled": 0,
                "duration": 0,
                "errors": 0
            }
        }
        with cls._lock:
            cls._jobs[job_id] = job
        cls._save_history()
        
        # Start background task
        cls._executor.submit(cls._run_job, job_id)
        return job_id

    @classmethod
    def _run_job(cls, job_id):
        job = cls._jobs.get(job_id)
        if not job: return

        try:
            # Wait if queue is paused
            while cls._queue_paused:
                if job.get("status") == "cancelled":
                    return
                time.sleep(1)

            with cls._lock:
                job["status"] = "running"
            cls._save_history()

            start_time = time.time()
            logger.info(f"🚀 Starting Crawl Job: {job_id}")

            all_target_urls = set()
            depth = job["config"].get("depth", 0)
            max_pages = job["config"].get("max_pages", 50)
            
            # 1. Discovery phase
            for start_url in job["urls"]:
                if depth > 0:
                    links = get_internal_links(
                        start_url, 
                        max_links=max_pages, 
                        depth=depth,
                        timeout=job["config"].get("timeout", 10),
                        user_agent=job["config"].get("user_agent"),
                        respect_robots_txt=job["config"].get("respect_robots_txt", True),
                        verify_ssl=job["config"].get("verify_ssl", True),
                        rate_limit_delay=job["config"].get("rate_limit_delay", 0),
                        auth_cookies=job["config"].get("auth_cookies")
                    )
                    all_target_urls.update(links)
                else:
                    all_target_urls.add(start_url)
            
            job["stats"]["total_discovered"] = len(all_target_urls)
            
            # 2. Scraping phase
            final_urls = list(all_target_urls)[:max_pages]
            for url in final_urls:
                if job.get("status") == "cancelled":
                    break
                    
                try:
                    docs = load_web_with_images(
                        url,
                        selectors=job["config"].get("selectors"),
                        wait_time=job["config"].get("wait_time", 2),
                        javascript_enabled=job["config"].get("javascript_enabled", True),
                        timeout=job["config"].get("timeout", 10),
                        user_agent=job["config"].get("user_agent"),
                        verify_ssl=job["config"].get("verify_ssl", True),
                        extract_entities=job["config"].get("extract_entities", False),
                        auth_cookies=job["config"].get("auth_cookies")
                    )
                    
                    for doc in docs:
                        job["results"].append({
                            "url": url,
                            "title": doc.metadata.get("title", ""),
                            "content": doc.page_content,
                            "metadata": doc.metadata,
                            "timestamp": datetime.now().isoformat()
                        })
                    
                    job["stats"]["pages_crawled"] += 1
                except Exception as e:
                    logger.error(f"Error scraping {url}: {e}")
                    job["stats"]["errors"] += 1
            
            with cls._lock:
                job["status"] = "completed" if job["status"] != "cancelled" else "cancelled"
            
        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            with cls._lock:
                job["status"] = "failed"
                job["error"] = str(e)
        finally:
            job["stats"]["duration"] = round(time.time() - start_time, 2)
            cls._save_history()
            cls._save_results(job_id)
            # --- Auto-add crawled domains to Trust & Scoring Rules ---
            try:
                from urllib.parse import urlparse
                seed_urls = job.get('urls', []) or []
                for u in seed_urls:
                    try:
                        parsed = urlparse(u)
                        domain = (parsed.netloc or '').lower()
                        if domain.startswith('www.'):
                            domain = domain[4:]
                        if domain:
                            auto_add_trust_rule(domain, score=1.0, rule_type='domain')
                    except Exception as e:
                        logger.debug(f"Failed to parse/add trust rule for url {u}: {e}")
            except Exception as e:
                logger.warning(f"Auto-adding trust rules failed: {e}")
            
            # Fire webhook if provided
            webhook_url = job["config"].get("webhook_url")
            if webhook_url:
                try:
                    import requests
                    payload = {
                        "job_id": job_id,
                        "status": job["status"],
                        "stats": job["stats"]
                    }
                    requests.post(webhook_url, json=payload, timeout=5)
                    logger.info(f"Webhook sent for job {job_id} to {webhook_url}")
                except Exception as we:
                    logger.warning(f"Webhook failed for job {job_id} to {webhook_url}: {we}")

    @classmethod
    def _save_results(cls, job_id):
        os.makedirs(cls._results_dir, exist_ok=True)
        results_file = os.path.join(cls._results_dir, f"{job_id}.json")
        job = cls._jobs.get(job_id)
        if job:
            try:
                with open(results_file, "w") as f:
                    json.dump(job["results"], f, indent=2)
            except Exception as e:
                logger.error(f"Failed to save results for {job_id}: {e}")

    @classmethod
    def get_job_status(cls, job_id):
        cls._load_history()
        job = cls._jobs.get(job_id)
        if not job: return None
        # Return status without full results
        with cls._lock:
            status = job.copy()
            status.pop("results", None)
            return status

    @classmethod
    def cancel_job(cls, job_id):
        job = cls._jobs.get(job_id)
        if job and job["status"] == "running":
            with cls._lock:
                job["status"] = "cancelled"
            cls._save_history()
            return True
        return False

    @classmethod
    def get_history(cls):
        cls._load_history()
        history = []
        with cls._lock:
            for jid, job in cls._jobs.items():
                entry = job.copy()
                entry.pop("results", None)
                history.append(entry)
        return sorted(history, key=lambda x: x["created_at"], reverse=True)

    @classmethod
    def get_queue(cls):
        """Returns jobs that are currently pending."""
        cls._load_history()
        queue = []
        with cls._lock:
            for jid, job in cls._jobs.items():
                if job["status"] == "pending":
                    entry = job.copy()
                    entry.pop("results", None)
                    queue.append(entry)
        return sorted(queue, key=lambda x: x["created_at"], reverse=False)

    @classmethod
    def pause_queue(cls):
        """Pauses processing of new jobs from the queue."""
        with cls._lock:
            cls._queue_paused = True
            return True

    @classmethod
    def resume_queue(cls):
        """Resumes processing of jobs in the queue."""
        with cls._lock:
            cls._queue_paused = False
            return True

    @classmethod
    def get_results(cls, job_id):
        results_file = os.path.join(cls._results_dir, f"{job_id}.json")
        if os.path.exists(results_file):
            try:
                with open(results_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to read results for {job_id}: {e}")
        return None
