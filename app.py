import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create Flask app
app = Flask(__name__)

# Define routes
@app.route("/")
def home():
    return jsonify({
        "status": "success",
        "message": "VPN Bot API is running"
    })

# Webhook endpoint for YooKassa payments
@app.route("/webhook/payment", methods=["POST"])
def payment_webhook():
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "Invalid request"}), 400
            
        # Import asyncio to handle async function in Flask
        import asyncio
        from services.payment_service import process_webhook
        
        # Process the webhook notification
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(process_webhook(data))
        loop.close()
        
        if result:
            return jsonify({"status": "success"})
        else:
            return jsonify({"status": "error", "message": "Payment processing failed"}), 400
    except Exception as e:
        app.logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)