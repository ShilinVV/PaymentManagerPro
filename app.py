import os
import logging
from flask import Flask, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import DeclarativeBase

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Create SQLAlchemy base class
class Base(DeclarativeBase):
    pass

# Initialize SQLAlchemy
db = SQLAlchemy(model_class=Base)

# Create Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "default-secret-key")

# Configure the database
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL")
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_recycle": 300,
    "pool_pre_ping": True,
}

# Initialize SQLAlchemy with app
db.init_app(app)

# Import models (after SQLAlchemy initialization)
with app.app_context():
    # Import to register models
    import models
    # Create tables
    db.create_all()

@app.route('/')
def home():
    """Home page"""
    return jsonify({
        "status": "ok",
        "message": "VPN management system"
    })

@app.route('/api/status')
def api_status():
    """API endpoint to check system status"""
    return jsonify({
        "status": "ok",
        "database": bool(app.config["SQLALCHEMY_DATABASE_URI"]),
        "timestamp": os.environ.get("REPL_STARTED_AT"),
        "bot_token": bool(os.environ.get("BOT_TOKEN")),
        "outline_api": bool(os.environ.get("OUTLINE_API_URL"))
    })

@app.route('/webhooks/payment', methods=['POST'])
def payment_webhook():
    """Webhook for payment notifications"""
    if request.method == 'POST':
        try:
            # Log payment notification
            logger.info("Payment webhook received")
            logger.info(f"Headers: {request.headers}")
            logger.info(f"Data: {request.data}")
            
            # Here would be processing of the payment notification
            # from services.payment_service import process_webhook
            # await process_webhook(request.json)
            
            # For now, just acknowledge receipt
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"Error processing payment webhook: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    else:
        return jsonify({"status": "error", "message": "Method not allowed"}), 405

if __name__ == '__main__':
    # Run the app
    app.run(host='0.0.0.0', port=5000, debug=True)