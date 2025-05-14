import os
import logging
import asyncio
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler
)
from dotenv import load_dotenv

# Import Flask app for gunicorn
from app import app

from handlers.user_handlers import (
    start_command, 
    button_handler, 
    status_command,
    plans_command,
    help_command,
    buy_handler,
    payment_handler
)
from handlers.outline_handlers import (
    keys_command,
    check_subscription_expiry
)
from services.sync_service import sync_outline_keys, start_sync_scheduler
from handlers.admin_handlers import (
    admin_command,
    add_user_command,
    delete_user_command,
    list_users_command,
    broadcast_command,
    admin_button_handler
)

# Import database services
from config import USE_SQL_DATABASE
if USE_SQL_DATABASE:
    from services.database_service_sql import init_database
    from models import init_db
else:
    from services.database_service import init_database

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def init():
    """Initialize database connection"""
    if USE_SQL_DATABASE:
        # Initialize SQLAlchemy models
        try:
            init_db()
            logger.info("SQL database initialized")
        except Exception as e:
            logger.error(f"Error initializing SQL database: {e}")
    
    # Initialize database connection
    await init_database()

async def main():
    """Start the bot."""
    # Create the Application
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN environment variable is not set")
        return
        
    # Run database initialization
    await init()
        
    application = Application.builder().token(token).build()
    
    # User command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("plans", plans_command))
    application.add_handler(CommandHandler("keys", keys_command))
    
    # Admin command handlers
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("add_user", add_user_command))
    application.add_handler(CommandHandler("delete_user", delete_user_command))
    application.add_handler(CommandHandler("list_users", list_users_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    
    # Callback query handlers
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))
    application.add_handler(CallbackQueryHandler(buy_handler, pattern="^buy_"))
    application.add_handler(CallbackQueryHandler(payment_handler, pattern="^pay_"))  # Упрощаем паттерн
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Логируем все обработчики для отладки
    logger.info("Telegram bot handlers registered successfully")
    
    # Start the Bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Bot started and polling for updates...")
    
    # Запускаем первичную синхронизацию ключей
    logger.info("Starting initial key synchronization...")
    await sync_outline_keys()
    
    # Запускаем задачу периодической синхронизации
    asyncio.create_task(start_sync_scheduler(300))  # Синхронизация каждые 5 минут
    
    # Keep the bot running
    try:
        # Keep application running until stopped
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        # Exit gracefully on Ctrl+C or system exit
        pass
    finally:
        # Stop the application when finished
        await application.stop()

if __name__ == "__main__":
    # Use asyncio.run() to properly handle the event loop
    import asyncio
    asyncio.run(main())
