import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL")
USE_SQL_DATABASE = bool(DATABASE_URL)

# Outline API configuration
OUTLINE_API_URL = os.getenv("OUTLINE_API_URL")

# ЮKassa configuration (может использоваться в будущем)
YUKASSA_SHOP_ID = os.getenv("YUKASSA_SHOP_ID")
YUKASSA_SECRET_KEY = os.getenv("YUKASSA_SECRET_KEY")

# Telegram bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(","))) if os.getenv("ADMIN_IDS") else []

# VPN service configuration
VPN_PLANS = {
    "test": {
        "name": "Тестовый на 3 дня",
        "duration": 3,  # days
        "price": 0.00,  # бесплатно
        "devices": 2,   # количество устройств
        "description": "Тестовый период на 3 дня для двух устройств (мобильный и компьютер)."
    },
    "weekly": {
        "name": "7 дней",
        "duration": 7,  # days
        "price": 75.00,  # rubles
        "devices": 1,   # количество устройств
        "description": "Доступ к VPN на 7 дней для одного устройства - PC или мобильного."
    },
    "monthly": {
        "name": "30 дней",
        "duration": 30,  # days
        "price": 150.00,  # rubles
        "devices": 2,   # количество устройств
        "description": "Доступ к VPN на 30 дней без ограничений по трафику."
    },
    "quarterly": {
        "name": "90 дней",
        "duration": 90,  # days
        "price": 425.00,  # rubles
        "discount": "5%",
        "devices": 3,   # количество устройств
        "description": "Доступ к VPN на 90 дней со скидкой 5%. Возможность подключения до 3 устройств."
    },
    "semi_annual": {
        "name": "180 дней",
        "duration": 180,  # days
        "price": 765.00,  # rubles
        "discount": "15%",
        "devices": 3,   # количество устройств
        "description": "Доступ к VPN на 180 дней со скидкой 15%. Возможность подключения до 3 устройств."
    },
    "annual": {
        "name": "365 дней",
        "duration": 365,  # days
        "price": 1260.00,  # rubles
        "discount": "30%",
        "devices": 5,   # количество устройств
        "description": "Доступ к VPN на 365 дней со скидкой 30%. Возможность подключения до 5 устройств."
    }
}

# Notification settings
EXPIRY_NOTIFICATION_DAYS = 1  # За сколько дней до окончания подписки отправлять уведомление
