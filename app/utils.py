import os
import json
from config import Config
from logger import setup_logger

logger = setup_logger(__name__)

def update_status(percent, message):
    """
    Updates the ingestion status to a JSON file.
    """
    try:
        try:
            percent = int(percent)
        except:
            percent = 0
            
        status = "running" if percent < 100 else "completed"
        # Ensure data directory exists
        
        with open(os.path.join(Config.BASE_DIR, "ingest_status.json"), "w") as f:
            json.dump({"percent": percent, "message": message, "status": status}, f)
    except Exception as e:
        logger.warning(f"Failed to update status: {e}")

def auto_add_trust_rule(pattern, score=1.0, rule_type='domain'):
    """
    Automatically adds a trust rule to the config if it doesn't exist.
    """
    try:
        config_path = Config.TRUST_CONFIG_FILE
        data = {}
        if os.path.exists(config_path):
             with open(config_path, 'r') as f: 
                try:
                    data = json.load(f)
                except json.JSONDecodeError:
                    data = {}
        
        rules = data.get('rules', [])
        # Check if pattern already exists
        if any(r['pattern'] == pattern for r in rules): return
            
        rules.append({"pattern": pattern, "score": score, "type": rule_type})
        data['rules'] = rules
        if 'default_score' not in data: data['default_score'] = 0.5
        
        with open(config_path, 'w') as f: 
            json.dump(data, f, indent=4)
        logger.info(f"   🛡️ Auto-added Trust Rule for: {pattern} ({rule_type})")
    except Exception as e:
        logger.warning(f"Failed to auto-add trust rule: {e}")
