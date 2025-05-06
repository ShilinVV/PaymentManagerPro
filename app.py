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
    data = request.json
    
    # Here will be code to process the payment webhook
    # This will be integrated with the Telegram bot

    return jsonify({
        "status": "success"
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)