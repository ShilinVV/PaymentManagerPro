import os
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

def check_bot_token():
    """Check if the bot token is set"""
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        logger.error("BOT_TOKEN environment variable is not set")
        return False
    
    logger.info("BOT_TOKEN environment variable is set")
    return True

def check_outline_api():
    """Check if the Outline API URL is set"""
    outline_api_url = os.getenv("OUTLINE_API_URL")
    if not outline_api_url:
        logger.error("OUTLINE_API_URL environment variable is not set")
        return False
    
    logger.info("OUTLINE_API_URL environment variable is set")
    return True

def check_database_url():
    """Check if the database URL is set"""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL environment variable is not set")
        
        # Check MongoDB URI as fallback
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("Neither DATABASE_URL nor MONGO_URI environment variables are set")
            return False
        else:
            logger.warning("DATABASE_URL is not set, but MONGO_URI is available")
            return True
    
    logger.info("DATABASE_URL environment variable is set")
    return True

def check_admin_ids():
    """Check if admin IDs are set"""
    admin_ids = os.getenv("ADMIN_IDS")
    if not admin_ids:
        logger.error("ADMIN_IDS environment variable is not set")
        return False
    
    try:
        # Проверяем, что строка с админскими ID может быть разбита на числа
        admin_id_list = [int(id.strip()) for id in admin_ids.split(",")]
        logger.info(f"ADMIN_IDS environment variable is set: {admin_id_list}")
        return True
    except ValueError:
        logger.error("ADMIN_IDS must be a comma-separated list of integers")
        return False

def check_yukassa_credentials():
    """Check if YooKassa credentials are set"""
    shop_id = os.getenv("YUKASSA_SHOP_ID")
    secret_key = os.getenv("YUKASSA_SECRET_KEY")
    
    if not shop_id:
        logger.error("YUKASSA_SHOP_ID environment variable is not set")
        return False
    
    if not secret_key:
        logger.error("YUKASSA_SECRET_KEY environment variable is not set")
        return False
    
    logger.info("YooKassa credentials are set")
    return True

def check_all():
    """Check all required environment variables"""
    results = {
        "BOT_TOKEN": check_bot_token(),
        "OUTLINE_API": check_outline_api(),
        "DATABASE": check_database_url(),
        "ADMIN_IDS": check_admin_ids(),
        "YUKASSA": check_yukassa_credentials()
    }
    
    # Вывод сводки
    logger.info("========== Environment Check Summary ==========")
    for name, success in results.items():
        status = "OK" if success else "MISSING"
        logger.info(f"{name}: {status}")
    logger.info("==============================================")
    
    # Возвращаем True только если все проверки успешны
    return all(results.values())

if __name__ == "__main__":
    # Выполняем проверку всех переменных окружения
    if check_all():
        logger.info("All environment variables are properly set")
    else:
        logger.error("Some environment variables are missing or invalid")