import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from config import Config

def setup_logger(name=__name__):
    """
    Sets up a logger with a consistent format, logging to both console and file.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    
    # Check if handlers already exist to avoid duplicate logs
    if logger.handlers:
        return logger

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File Handler
    log_dir = Config.LOG_DIR
    log_file = os.path.join(log_dir, 'app.log')

    try:
        if not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)
            
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except PermissionError:
        print(f"⚠️ Warning: Could not write to log file {log_file} (Permission Denied). Logging to Console only.")
    except Exception as e:
        print(f"⚠️ Warning: Could not setup log file: {e}")

    return logger
