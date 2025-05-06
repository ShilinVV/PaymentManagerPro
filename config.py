import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "vpn_bot")

# Marzban API configuration
MARZBAN_API_BASE_URL = os.getenv("MARZBAN_API_BASE_URL", "http://localhost:8000")
MARZBAN_API_USERNAME = os.getenv("MARZBAN_API_USERNAME")
MARZBAN_API_PASSWORD = os.getenv("MARZBAN_API_PASSWORD")

# ЮKassa configuration
YUKASSA_SHOP_ID = os.getenv("YUKASSA_SHOP_ID")
YUKASSA_SECRET_KEY = os.getenv("YUKASSA_SECRET_KEY")

# Telegram bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# VPN service configuration
VPN_PLANS = {
    "basic": {
        "name": "Базовый",
        "data_limit": 10 * 1024 * 1024 * 1024,  # 10 GB in bytes
        "duration": 30,  # days
        "price": 299.00  # rubles
    },
    "standard": {
        "name": "Стандартный",
        "data_limit": 50 * 1024 * 1024 * 1024,  # 50 GB in bytes
        "duration": 30,  # days
        "price": 599.00  # rubles
    },
    "premium": {
        "name": "Премиум",
        "data_limit": 100 * 1024 * 1024 * 1024,  # 100 GB in bytes
        "duration": 30,  # days
        "price": 999.00  # rubles
    }
}
