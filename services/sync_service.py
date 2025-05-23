"""
Сервис синхронизации для обеспечения соответствия между базой данных и Outline сервером
"""

import asyncio
import logging
from datetime import datetime

from services.database_service_sql import (
    get_all_users, get_user_access_keys, update_access_key,
    get_access_key, get_user_subscriptions
)
from services.outline_service import OutlineService

logger = logging.getLogger(__name__)
outline_service = OutlineService()

async def sync_outline_keys():
    """
    Синхронизирует ключи между Outline сервером и базой данных.
    Помечает удаленные ключи в базе данных.
    """
    try:
        logger.info("Начинаем синхронизацию ключей Outline")
        
        # Получаем все ключи с сервера Outline
        outline_keys_resp = await outline_service.get_keys()
        if not outline_keys_resp or "accessKeys" not in outline_keys_resp:
            logger.error("Не удалось получить ключи с сервера Outline")
            return False
            
        # Создаем словарь ключей Outline для быстрого поиска
        outline_keys = {key["id"]: key for key in outline_keys_resp["accessKeys"]}
        
        # Получаем всех пользователей из базы данных
        users = await get_all_users()
        
        for user in users:
            try:
                # Получаем ID пользователя (поддержка как словарей, так и объектов)
                if hasattr(user, 'id'):
                    user_id = user.id
                else:
                    user_id = user["id"]
                
                # Получаем все ключи пользователя из базы данных
                user_keys = await get_user_access_keys(user_id)
                
                for key in user_keys:
                    # Получаем key_id (поддержка как словарей, так и объектов)
                    if hasattr(key, 'key_id'):
                        key_id = key.key_id
                        is_deleted = getattr(key, 'deleted', False)
                    else:
                        key_id = key.get("key_id")
                        is_deleted = key.get("deleted", False)
                    
                    # Проверяем, существует ли ключ на сервере Outline
                    if key_id not in outline_keys and not is_deleted:
                        # Ключ удален на сервере Outline, но не в базе данных
                        logger.info(f"Ключ {key_id} не существует на сервере Outline, помечаем как удаленный")
                        await update_access_key(key_id, {
                            "deleted": True,
                            "updated_at": datetime.now()
                        })
            except Exception as e:
                logger.error(f"Ошибка при обработке пользователя: {e}")
                continue
        
        logger.info("Синхронизация ключей завершена успешно")
        return True
    except Exception as e:
        logger.error(f"Ошибка при синхронизации ключей: {e}")
        return False

async def get_server_stats():
    """
    Получает статистику сервера Outline.
    """
    try:
        stats = {
            "users_count": 0,
            "active_keys_count": 0,
            "total_keys_count": 0,
            "data_usage": 0,
            "server_info": {}
        }
        
        # Получаем информацию о сервере
        server_info = await outline_service.get_server_info()
        if server_info:
            stats["server_info"] = server_info
        
        # Получаем метрики сервера
        metrics = await outline_service.get_metrics()
        if metrics:
            stats["data_usage"] = metrics.get("bytesTransferredByUserId", {})
        
        # Получаем все ключи
        keys_resp = await outline_service.get_keys()
        if keys_resp and "accessKeys" in keys_resp:
            stats["total_keys_count"] = len(keys_resp["accessKeys"])
        
        # Получаем статистику пользователей
        users = await get_all_users()
        
        # Проверяем, что users не None
        if users:
            stats["users_count"] = len(users)
            
            # Считаем активные ключи
            active_keys = 0
            for user in users:
                try:
                    # Получаем ID пользователя (поддержка как словарей, так и объектов)
                    if hasattr(user, 'id'):
                        user_id = user.id
                    else:
                        user_id = user["id"]
                    
                    # Получаем ключи пользователя
                    user_keys = await get_user_access_keys(user_id)
                    
                    if user_keys:
                        for key in user_keys:
                            # Проверяем статус удаления ключа (поддержка как словарей, так и объектов)
                            if hasattr(key, 'deleted'):
                                is_deleted = key.deleted
                            else:
                                is_deleted = key.get("deleted", False)
                                
                            if not is_deleted:
                                active_keys += 1
                except Exception as e:
                    logger.error(f"Ошибка при обработке пользователя для статистики: {e}")
                    continue
            
            stats["active_keys_count"] = active_keys
        
        return stats
    except Exception as e:
        logger.error(f"Ошибка при получении статистики: {e}")
        return {}

async def start_sync_scheduler(interval_seconds=300):
    """
    Запускает планировщик регулярной синхронизации.
    
    Args:
        interval_seconds (int): Интервал между синхронизациями в секундах
    """
    logger.info(f"Запуск планировщика синхронизации с интервалом {interval_seconds} секунд")
    
    while True:
        await sync_outline_keys()
        await asyncio.sleep(interval_seconds)