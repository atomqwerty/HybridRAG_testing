from flask import Flask
from flask_cors import CORS
from app.config import Config
from app.api.chat_routes import api as chat_bp
from app.api.file_routes import api as file_bp
from app.api.crawl_routes import api as crawl_bp
from app.api.agent_routes import api as agent_bp
from app.api.auth_routes import api as auth_bp
from app.api.config_routes import api as config_bp
import logging
import os

# Setup Logger
from app.logger import setup_logger
logger = setup_logger(__name__)

def create_app():
    """Factory function to create Flask app."""
    app = Flask(__name__, static_folder=os.path.join(Config.BASE_DIR, 'frontend/build'), static_url_path='/')
    CORS(app)

    # Register Blueprints
    app.secret_key = Config.SECRET_KEY
    app.register_blueprint(auth_bp, url_prefix='/api')
    app.register_blueprint(chat_bp, url_prefix='/api')
    app.register_blueprint(file_bp, url_prefix='/api')
    app.register_blueprint(crawl_bp, url_prefix='/api')
    app.register_blueprint(agent_bp, url_prefix='/api')
    app.register_blueprint(config_bp, url_prefix='/api')

    # Seed default admin on startup
    from app.services.user_service import UserService
    UserService._ensure_seed()

    # Register Static/Frontend Routes (Legacy support)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def serve_frontend(path):
        if path != "" and os.path.exists(app.static_folder + '/' + path):
            return app.send_static_file(path)
        return app.send_static_file('index.html')

    logger.info("✅ Flask App Created.")
    return app
