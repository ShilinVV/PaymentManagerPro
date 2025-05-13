#!/usr/bin/env python3
"""
Тестирование функциональности Telegram бота для VPN с использованием Outline API
"""

import asyncio
import logging
from datetime import datetime, timedelta

from telegram import Update, User, CallbackQuery, Message, Chat
from telegram.ext import CallbackContext

from handlers.outline_handlers import (
    start_command, button_handler, status_command, keys_command, help_command
)
from services.database_service import init_database, create_user, create_subscription, create_access_key

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Мокап контекста
class MockContext:
    def __init__(self):
        self.bot_data = {}
        self.args = []

# Мокап пользователя
def create_mock_user(user_id=12345678, first_name="Тестовый", last_name="Пользователь", username="test_user"):
    user = User(id=user_id, first_name=first_name, last_name=last_name, is_bot=False, 
                username=username, language_code="ru")
    return user

# Мокап сообщения
def create_mock_message(user, text="/start", message_id=1):
    chat = Chat(id=user.id, type="private", username=user.username, first_name=user.first_name, last_name=user.last_name)
    message = Message(message_id=message_id, date=datetime.now(), chat=chat, from_user=user, text=text)
    return message

# Мокап обновления
def create_mock_update(user=None, message=None, callback_query=None):
    if user is None:
        user = create_mock_user()
    if message is None and callback_query is None:
        message = create_mock_message(user)
    
    update = Update(update_id=1)
    update._effective_user = user
    
    if message:
        update.message = message
    
    if callback_query:
        update.callback_query = callback_query
    
    return update

# Создание мокап данных для тестирования
async def setup_mock_data():
    """Создание тестовых данных для пользователя и подписки"""
    await init_database()
    
    user_id = 12345678
    
    # Создание пользователя
    user_data = {
        "telegram_id": user_id,
        "username": "test_user",
        "first_name": "Тестовый",
        "last_name": "Пользователь",
        "created_at": datetime.now(),
        "is_premium": False,
        "test_used": False
    }
    await create_user(user_data)
    
    # Создание подписки
    subscription_id = "test_sub_1"
    subscription_data = {
        "subscription_id": subscription_id,
        "user_id": user_id,
        "plan_id": "monthly",
        "status": "active",
        "created_at": datetime.now(),
        "expiry_date": datetime.now() + timedelta(days=30),
        "price_paid": 150.0
    }
    await create_subscription(subscription_data)
    
    # Создание ключа доступа
    key_data = {
        "key_id": "test_key_1",
        "name": "Тестовый ключ",
        "access_url": "ss://test_access_url_string",
        "user_id": user_id,
        "subscription_id": subscription_id,
        "created_at": datetime.now(),
        "deleted": False
    }
    await create_access_key(key_data)
    
    logger.info("Mock data created successfully")

# Тестирование команды /start
async def test_start_command():
    """Тест команды /start"""
    logger.info("Testing /start command")
    user = create_mock_user()
    message = create_mock_message(user, "/start")
    update = create_mock_update(user, message)
    context = MockContext()
    
    await start_command(update, context)
    logger.info("✅ /start command test complete")

# Тестирование команды /status
async def test_status_command():
    """Тест команды /status"""
    logger.info("Testing /status command")
    user = create_mock_user()
    message = create_mock_message(user, "/status")
    update = create_mock_update(user, message)
    context = MockContext()
    
    await status_command(update, context)
    logger.info("✅ /status command test complete")

# Тестирование команды /keys
async def test_keys_command():
    """Тест команды /keys"""
    logger.info("Testing /keys command")
    user = create_mock_user()
    message = create_mock_message(user, "/keys")
    update = create_mock_update(user, message)
    context = MockContext()
    
    await keys_command(update, context)
    logger.info("✅ /keys command test complete")

# Тестирование команды /help
async def test_help_command():
    """Тест команды /help"""
    logger.info("Testing /help command")
    user = create_mock_user()
    message = create_mock_message(user, "/help")
    update = create_mock_update(user, message)
    context = MockContext()
    
    await help_command(update, context)
    logger.info("✅ /help command test complete")

# Запуск тестов
async def run_tests():
    """Запуск всех тестов"""
    logger.info("Starting bot functionality tests")
    
    # Создание тестовых данных
    await setup_mock_data()
    
    # Тестирование команд
    await test_start_command()
    await test_status_command()
    await test_keys_command()
    await test_help_command()
    
    logger.info("All tests completed ✅")

# Запуск тестов
if __name__ == "__main__":
    asyncio.run(run_tests())