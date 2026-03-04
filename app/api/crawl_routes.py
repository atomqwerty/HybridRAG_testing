from flask import Blueprint, request, jsonify
from app.services.crawl_service import CrawlService
from app.crawler import load_web_with_images
import logging

logger = logging.getLogger(__name__)
api = Blueprint('crawl_api', __name__)

@api.route('/crawl', methods=['POST'])
def create_crawl_job():
    data = request.json or {}
    urls = data.get('url')
    if not urls:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    # Extract config parameters
    config = {
        "depth": data.get('depth', 0),
        "max_pages": data.get('max_pages', 50),
        "selectors": data.get('selectors'),
        "wait_time": data.get('wait_time', 2),
        "user_agent": data.get('user_agent'),
        "javascript_enabled": data.get('javascript_enabled', True),
        "timeout": data.get('timeout', 10),
        "respect_robots_txt": data.get('respect_robots_txt', True),
        "webhook_url": data.get('webhook_url'),
        "extract_entities": data.get('extract_entities', False),
        "rate_limit_delay": data.get('rate_limit_delay', 0),
        "auth_cookies": data.get('auth_cookies')
    }
    
    job_id = CrawlService.create_job(urls, config)
    return jsonify({"job_id": job_id, "status": "pending"}), 202

@api.route('/crawl/queue', methods=['GET'])
def get_crawl_queue():
    queue = CrawlService.get_queue()
    return jsonify(queue)

@api.route('/crawl/queue/pause', methods=['POST'])
def pause_crawl_queue():
    CrawlService.pause_queue()
    return jsonify({"message": "Queue paused. Currently running jobs will finish, but new jobs will wait."}), 200

@api.route('/crawl/queue/resume', methods=['POST'])
def resume_crawl_queue():
    CrawlService.resume_queue()
    return jsonify({"message": "Queue resumed. Pending jobs will now start processing."}), 200

@api.route('/crawl/<job_id>', methods=['GET'])
def get_crawl_status(job_id):
    status = CrawlService.get_job_status(job_id)
    if not status:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status)

@api.route('/crawl/<job_id>', methods=['DELETE'])
def cancel_crawl_job(job_id):
    success = CrawlService.cancel_job(job_id)
    if success:
        return jsonify({"message": "Job cancelled"}), 200
    return jsonify({"error": "Job not found or not running"}), 404

@api.route('/crawl/history', methods=['GET'])
def get_crawl_history():
    history = CrawlService.get_history()
    return jsonify(history)

@api.route('/results/<job_id>', methods=['GET'])
def get_crawl_results(job_id):
    results = CrawlService.get_results(job_id)
    if results is None:
        return jsonify({"error": "Results not found"}), 404
    
    # Wrap in the requested format
    status = CrawlService.get_job_status(job_id)
    return jsonify({
        "job_id": job_id,
        "status": status["status"],
        "urls": status["urls"],
        "results": results,
        "stats": status["stats"]
    })

@api.route('/content', methods=['GET'])
def get_single_content():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "Missing 'url' parameter"}), 400
    
    try:
        docs = load_web_with_images(url, javascript_enabled=True)
        if not docs:
            return jsonify({"error": "Failed to fetch content"}), 500
        
        doc = docs[0]
        return jsonify({
            "url": url,
            "title": doc.metadata.get("title", ""),
            "content": doc.page_content,
            "metadata": doc.metadata
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@api.route('/export/<job_id>', methods=['GET'])
def export_crawl_results(job_id):
    format_type = request.args.get('format', 'json').lower()
    results = CrawlService.get_results(job_id)
    if results is None:
        return jsonify({"error": "Results not found"}), 404

    if format_type == 'json':
        from flask import Response
        import json
        return Response(json.dumps(results, ensure_ascii=False, indent=2), mimetype='application/json')
    
    elif format_type == 'csv':
        import io
        import csv
        from flask import Response
        
        output = io.StringIO()
        if not results:
            return Response("url,title,content,timestamp", mimetype='text/csv')
            
        writer = csv.DictWriter(output, fieldnames=["url", "title", "content", "timestamp", "metadata"])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "url": r.get("url"),
                "title": r.get("title"),
                "content": r.get("content", "").replace('\n', ' ')[:500] + '...', # Truncate for CSV
                "timestamp": r.get("timestamp"),
                "metadata": str(r.get("metadata", {}))
            })
            
        return Response(output.getvalue(), mimetype='text/csv', headers={"Content-Disposition": f"attachment;filename=export_{job_id}.csv"})

    elif format_type == 'xml':
        import xml.etree.ElementTree as ET
        from flask import Response
        
        root = ET.Element("CrawlResults", jobId=job_id)
        for r in results:
            item = ET.SubElement(root, "Result")
            ET.SubElement(item, "Url").text = r.get("url", "")
            ET.SubElement(item, "Title").text = r.get("title", "")
            content = ET.SubElement(item, "Content")
            content.text = r.get("content", "")
            ET.SubElement(item, "Timestamp").text = r.get("timestamp", "")
            
        xml_str = ET.tostring(root, encoding='utf8', method='xml').decode('utf8')
        return Response(xml_str, mimetype='application/xml')

    return jsonify({"error": "Invalid format requested. Supported: json, csv, xml"}), 400
