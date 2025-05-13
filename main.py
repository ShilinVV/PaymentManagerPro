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

from handlers.outline_handlers import (
    start_command, 
    button_handler, 
    status_command,
    plans_command,
    help_command,
    keys_command,
    check_subscription_expiry
)
from handlers.admin_handlers import (
    admin_command,
    add_user_command,
    delete_user_command,
    list_users_command,
    broadcast_command,
    admin_button_handler
)
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
    # Initialize MongoDB connection
    await init_database()

async def main():
    """Start the bot."""
    # Create the Application
    token = os.getenv("BOT_TOKEN")
    if not token:
        logger.error("BOT_TOKEN environment variable is not set")
        return
        
    # Run database initialization
    await init_database()
        
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
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # Start the Bot
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    logger.info("Bot started and polling for updates...")
    
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
