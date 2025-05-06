import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ContextTypes
)
import mysql.connector
from dotenv import load_dotenv

# Настройка логов
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Загрузка конфига
load_dotenv()

class MarzbanBot:
    def __init__(self):
        self.db_config = {
            "host": os.getenv("DB_HOST"),
            "user": os.getenv("DB_USER"),
            "password": os.getenv("DB_PASSWORD"),
            "database": os.getenv("DB_NAME")
        }

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка команды /start"""
        keyboard = [
            [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
            [InlineKeyboardButton("🔄 Мой статус", callback_data="status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "🔑 VPN Bot Menu:",
            reply_markup=reply_markup
        )

    async def create_account(self, user_id: int) -> str:
        """Создает аккаунт в Marzban DB"""
        try:
            conn = mysql.connector.connect(**self.db_config)
            cursor = conn.cursor()
            
            username = f"user_{user_id}"
            cursor.execute(
                """INSERT INTO users 
                (username, status, data_limit, expire, created_at, data_limit_reset_strategy) 
                VALUES (%s, 'active', 1073741824, 
                UNIX_TIMESTAMP(DATE_ADD(NOW(), INTERVAL 7 DAY)), NOW(), 'no_reset')""",
                (username,)
            )
            conn.commit()
            return username
            
        except Exception as e:
            logging.error(f"DB error: {e}")
            raise
        finally:
            if conn.is_connected():
                conn.close()

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка кнопок"""
        query = update.callback_query
        await query.answer()
        
        if query.data == "buy":
            try:
                username = await self.create_account(query.from_user.id)
                await query.edit_message_text(
                    f"✅ Аккаунт создан!\n\n"
                    f"👤 Логин: `{username}`\n"
                    f"📊 Лимит: 1 ГБ\n"
                    f"⏳ Срок: 7 дней\n\n"
                    f"Оплата: /pay",
                    parse_mode="Markdown"
                )
            except Exception as e:
                await query.edit_message_text(f"❌ Ошибка: {e}")

def main():
    bot = MarzbanBot()
    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    
    # Обработчики
    app.add_handler(CommandHandler("start", bot.start))
    app.add_handler(CallbackQueryHandler(bot.button_handler))
    
    # Запуск бота
    app.run_polling()

if __name__ == "__main__":
    main()