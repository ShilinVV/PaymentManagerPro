#!/usr/bin/env python3
"""
Простая проверка доступности телеграм-бота и основной функциональности
"""

import os
import logging
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    logger.info("Проверка функциональности телеграм-бота")
    
    # Проверяем переменные окружения
    bot_token = os.getenv("BOT_TOKEN")
    admin_ids = os.getenv("ADMIN_IDS")
    mongo_uri = os.getenv("MONGO_URI")
    outline_api_url = os.getenv("OUTLINE_API_URL")
    
    logger.info(f"BOT_TOKEN: {'Задан' if bot_token else 'Не задан'}")
    logger.info(f"ADMIN_IDS: {'Задан' if admin_ids else 'Не задан'}")
    logger.info(f"MONGO_URI: {'Задан' if mongo_uri else 'Не задан'}")
    logger.info(f"OUTLINE_API_URL: {'Задан' if outline_api_url else 'Не задан'}")
    
    # Выводим информацию о доступных командах
    logger.info("\nДоступные команды бота:")
    logger.info("/start - Начать работу с ботом")
    logger.info("/help - Получить справочную информацию")
    logger.info("/status - Проверить статус подписки")
    logger.info("/plans - Просмотреть доступные тарифные планы")
    logger.info("/keys - Управление ключами доступа")
    
    # Рекомендации по тестированию
    logger.info("\nДля полноценного тестирования бота:")
    logger.info("1. Откройте бота в Телеграм и отправьте команду /start")
    logger.info("2. Проверьте работу команд: /status, /plans, /keys, /help")
    logger.info("3. Попробуйте создать новый ключ через команду /keys")
    logger.info("4. Проверьте отображение ссылки доступа и возможность удаления ключа")

if __name__ == "__main__":
    main()
