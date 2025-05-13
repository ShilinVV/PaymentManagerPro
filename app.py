import os
import logging
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Create Flask app
app = Flask(__name__)

# Define routes
@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "VPN Bot API is running"
    })

@app.route("/api/status")
def api_status():
    """API endpoint to check system status"""
    from config import VPN_PLANS
    
    # Check if YooKassa is configured
    yukassa_configured = bool(os.getenv("YUKASSA_SHOP_ID")) and bool(os.getenv("YUKASSA_SECRET_KEY"))
    
    # Check if Outline API is configured
    outline_configured = bool(os.getenv("OUTLINE_API_URL"))
    
    # Count available plans
    plans_count = len(VPN_PLANS) if VPN_PLANS else 0
    
    return jsonify({
        "status": "success",
        "bot_status": "running",
        "api_status": "running",
        "yukassa_configured": yukassa_configured,
        "outline_configured": outline_configured,
        "plans_available": plans_count
    })

# Webhook endpoint for YooKassa payments
@app.route("/webhook/payment", methods=["POST"])
def payment_webhook():
    try:
        data = request.json
        app.logger.info(f"Received webhook: {data}")
        
        if not data:
            app.logger.error("Invalid request - no JSON body")
            return jsonify({"status": "error", "message": "Invalid request - no JSON body"}), 400
            
        # Import asyncio to handle async function in Flask
        import asyncio
        from services.payment_service import process_webhook
        
        # Process the webhook notification
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(process_webhook(data))
        loop.close()
        
        if result:
            app.logger.info("Payment processed successfully")
            return jsonify({"status": "success"})
        else:
            app.logger.warning("Payment processing failed")
            return jsonify({"status": "error", "message": "Payment processing failed"}), 400
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)