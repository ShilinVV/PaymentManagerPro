import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bson import ObjectId

from config import ADMIN_IDS, VPN_PLANS
from services.outline_service import OutlineService
from utils.helpers import format_bytes
from services.database_service import (
    get_user,
    get_all_users,
    update_user,
    create_user,
    create_subscription,
    update_subscription,
    get_user_subscriptions,
    get_active_subscription,
    get_user_access_keys,
    create_access_key
)
from utils.helpers import format_bytes, format_expiry_date

logger = logging.getLogger(__name__)
outline_service = OutlineService()

async def is_admin(update: Update) -> bool:
    """Check if the user is an admin"""
    user_id = update.effective_user.id
    return user_id in ADMIN_IDS

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /admin command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    keyboard = [
        [InlineKeyboardButton("👥 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
        [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "🛠️ <b>Панель администратора</b>\n\n"
        "Выберите действие из списка ниже:",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for admin panel buttons"""
    query = update.callback_query
    await query.answer()
    
    if not await is_admin(update):
        await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
        return
    
    data = query.data
    
    if data == "admin_list_users":
        # Get all users from database
        try:
            all_users = await get_all_users()
            
            if not all_users:
                await query.edit_message_text(
                    "📊 Пользователи не найдены.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Назад", callback_data="admin_back")
                    ]])
                )
                return
            
            # Get all keys from Outline API to get usage data
            outline_keys = await outline_service.get_keys()
            
            users_text = "📊 <b>Список пользователей:</b>\n\n"
            
            # Process first 10 users to avoid message too long
            for user in all_users[:10]:
                telegram_id = user.get("telegram_id")
                username = user.get("username", "Unknown")
                first_name = user.get("first_name", "")
                has_active = user.get("has_active_subscription", False)
                
                display_name = f"{first_name} (@{username})" if first_name else f"@{username}"
                status = "✅ Active" if has_active else "❌ Inactive"
                
                # Get user subscriptions
                subscriptions = await get_user_subscriptions(telegram_id, status="active")
                
                # Get user keys
                access_keys = await get_user_access_keys(telegram_id)
                
                # Calculate traffic usage from Outline API
                total_traffic = 0
                for key in access_keys:
                    key_id = key.get("key_id")
                    # Check if key exists in outline_keys (metrics data)
                    for outline_key in outline_keys.get("keys", []):
                        if str(outline_key.get("id")) == str(key_id):
                            # Add usage data
                            total_traffic += outline_key.get("metrics", {}).get("bytesTransferred", 0)
                
                # Build user information
                users_text += f"👤 <code>{display_name}</code> - {status}\n"
                
                if subscriptions:
                    # Get the latest subscription
                    latest_sub = max(subscriptions, key=lambda x: x.get("expires_at", 0))
                    plan_id = latest_sub.get("plan_id", "unknown")
                    expires_at = latest_sub.get("expires_at", 0)
                    
                    plan_name = VPN_PLANS.get(plan_id, {}).get("name", "Unknown")
                    users_text += f"🔑 План: {plan_name}\n"
                    users_text += f"📈 Трафик: {format_bytes(total_traffic)}\n"
                    users_text += f"⏳ До: {format_expiry_date(expires_at)}\n\n"
                else:
                    users_text += "\n"
            
            if len(all_users) > 10:
                users_text += f"...и еще {len(all_users) - 10} пользователей"
            
            await query.edit_message_text(
                users_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="admin_back")
                ]]),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            await query.edit_message_text(
                f"❌ Ошибка при получении списка пользователей: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="admin_back")
                ]])
            )
    
    elif data == "admin_add_user":
        # Show plans for adding user
        keyboard = []
        for plan_id, plan in VPN_PLANS.items():
            keyboard.append([InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} ₽", 
                callback_data=f"admin_create_user_{plan_id}"
            )])
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="admin_back")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Store state in context
        context.user_data["admin_state"] = "waiting_for_username"
        
        await query.edit_message_text(
            "➕ <b>Добавление нового пользователя</b>\n\n"
            "Выберите тарифный план для нового пользователя:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    elif data.startswith("admin_create_user_"):
        plan_id = data.replace("admin_create_user_", "")
        
        # Store the plan in context
        context.user_data["admin_plan_id"] = plan_id
        
        await query.edit_message_text(
            "👤 Введите имя пользователя для нового аккаунта:\n\n"
            "Отправьте сообщение с именем пользователя или введите /cancel для отмены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Отмена", callback_data="admin_back")
            ]])
        )
        
        # Set state to wait for username
        context.user_data["admin_state"] = "waiting_for_username"
    
    elif data == "admin_delete_user":
        # Show prompt for username to delete
        await query.edit_message_text(
            "🗑️ Введите имя пользователя для удаления:\n\n"
            "Отправьте сообщение с именем пользователя или введите /cancel для отмены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Отмена", callback_data="admin_back")
            ]])
        )
        
        # Set state to wait for username to delete
        context.user_data["admin_state"] = "waiting_for_delete_username"
    
    elif data == "admin_broadcast":
        # Show prompt for broadcast message
        await query.edit_message_text(
            "📢 Введите сообщение для рассылки всем пользователям:\n\n"
            "Отправьте сообщение с текстом рассылки или введите /cancel для отмены.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↩️ Отмена", callback_data="admin_back")
            ]])
        )
        
        # Set state to wait for broadcast message
        context.user_data["admin_state"] = "waiting_for_broadcast"
    
    elif data == "admin_stats":
        # Show server statistics
        try:
            # Используем сервис синхронизации для получения статистики
            from services.sync_service import get_server_stats
            from utils.helpers import format_bytes
            
            stats = await get_server_stats()
            
            # Получаем основные данные из статистики
            users_count = stats.get("users_count", 0)
            active_keys_count = stats.get("active_keys_count", 0)
            total_keys_count = stats.get("total_keys_count", 0)
            
            # Получаем информацию о сервере
            server_info = stats.get("server_info", {})
            server_name = server_info.get("name", "Unknown")
            server_version = server_info.get("version", "Unknown")
            
            # Подсчитываем общее использование данных
            data_usage = stats.get("data_usage", {})
            total_bytes = sum(data_usage.values()) if data_usage else 0
            
            # Count active users (users with active subscriptions)
            all_users = await get_all_users()
            active_users = 0
            
            if all_users:
                for user in all_users:
                    if hasattr(user, 'has_active_subscription'):
                        if user.has_active_subscription:
                            active_users += 1
                    elif user.get("has_active_subscription", False):
                        active_users += 1
            
            # Форматируем статистику
            stats_text = "📊 <b>Статистика сервера</b>\n\n"
            stats_text += f"👥 Пользователей: {users_count}\n"
            stats_text += f"👤 Активных подписок: {active_users}\n"
            stats_text += f"🔑 Активных ключей: {active_keys_count}\n"
            stats_text += f"🔐 Всего ключей в Outline: {total_keys_count}\n"
            stats_text += f"📊 Использовано данных: {format_bytes(total_bytes)}\n"
            stats_text += f"📝 Имя сервера: {server_name}\n"
            stats_text += f"📌 Версия: {server_version}\n"
            
            # Добавляем кнопку синхронизации ключей
            keyboard = [
                [InlineKeyboardButton("🔄 Синхронизировать ключи", callback_data="admin_sync_keys")],
                [InlineKeyboardButton("↩️ Назад", callback_data="admin_back")]
            ]
            
            await query.edit_message_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await query.edit_message_text(
                f"❌ Ошибка при получении статистики: {str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="admin_back")
                ]])
            )
    
    elif data == "admin_sync_keys":
        # Синхронизация ключей
        try:
            # Отображаем сообщение о начале синхронизации
            await query.edit_message_text(
                "🔄 <b>Синхронизация ключей...</b>\n\n"
                "Пожалуйста, подождите.",
                parse_mode="HTML"
            )
            
            # Импортируем функцию синхронизации
            from services.sync_service import sync_outline_keys
            
            # Запускаем синхронизацию
            result = await sync_outline_keys()
            
            # Проверяем результат
            if result:
                # Синхронизация успешна, получаем обновленную статистику
                await query.edit_message_text(
                    "✅ <b>Синхронизация успешно завершена!</b>\n\n"
                    "Обновляем статистику...",
                    parse_mode="HTML"
                )
                
                # Вызываем обработчик статистики через callback_data
                await query.answer()
                return await admin_button_handler(update, context)
            else:
                # Ошибка синхронизации
                await query.edit_message_text(
                    "❌ <b>Ошибка синхронизации ключей.</b>\n\n"
                    "Проверьте журнал ошибок для получения дополнительной информации.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Назад к статистике", callback_data="admin_stats")
                    ]]),
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.error(f"Error synchronizing keys: {e}")
            await query.edit_message_text(
                f"❌ <b>Ошибка при синхронизации ключей:</b>\n\n{str(e)}",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад к статистике", callback_data="admin_stats")
                ]]),
                parse_mode="HTML"
            )
            
    elif data == "admin_back":
        # Return to admin panel
        keyboard = [
            [InlineKeyboardButton("👥 Список пользователей", callback_data="admin_list_users")],
            [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
            [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🛠️ <b>Панель администратора</b>\n\n"
            "Выберите действие из списка ниже:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
        # Clear admin state
        if "admin_state" in context.user_data:
            del context.user_data["admin_state"]

async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /add_user command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    # Check if we have arguments
    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ Недостаточно аргументов.\n\n"
            "Использование: /add_user <username> <plan_id>\n"
            "Например: /add_user test_user basic"
        )
        return
    
    username = args[0]
    plan_id = args[1]
    
    if plan_id not in VPN_PLANS:
        await update.message.reply_text(
            f"❌ Неверный тарифный план: {plan_id}\n\n"
            f"Доступные планы: {', '.join(VPN_PLANS.keys())}"
        )
        return
    
    plan = VPN_PLANS[plan_id]
    
    try:
        # Create user in Marzban
        # Create new subscription in database
        subscription_id = str(ObjectId())
        plan_id = context.user_data.get("selected_plan")
        days = plan.get("duration", 30)  # Default to 30 days if not specified
        
        # Create subscription
        subscription_data = {
            "subscription_id": subscription_id,
            "user_id": telegram_id,
            "plan_id": plan_id,
            "status": "active",
            "created_at": datetime.now().timestamp(),
            "expires_at": datetime.now().timestamp() + days * 86400,
        }
        await create_subscription(subscription_data)
        
        # Create access key via Outline API
        try:
            key_info = await outline_service.create_key_with_expiration(
                days=days,
                name=f"{username} {subscription_id[:8]}"
            )
            
            # Save key info to database
            key_data = {
                "key_id": key_info["id"],
                "user_id": telegram_id,
                "subscription_id": subscription_id,
                "name": key_info.get("name", f"Key for {username}"),
                "access_url": key_info["accessUrl"],
                "created_at": datetime.now().timestamp(),
            }
            await create_access_key(key_data)
            
            # Update user data
            await update_user(telegram_id, {"has_active_subscription": True})
        except Exception as e:
            logger.error(f"Error creating Outline key for user {username}: {e}")
        
        await update.message.reply_text(
            f"✅ Пользователь успешно создан!\n\n"
            f"👤 Логин: <code>{username}</code>\n"
            f"📋 Тариф: {plan['name']}\n"
            f"💾 Трафик: {format_bytes(plan['data_limit'])}\n"
            f"⏳ Срок: {plan['duration']} дней",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        await update.message.reply_text(f"❌ Ошибка при создании пользователя: {str(e)}")

async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /delete_user command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    # Check if we have arguments
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Недостаточно аргументов.\n\n"
            "Использование: /delete_user <username>\n"
            "Например: /delete_user test_user"
        )
        return
    
    username = args[0]
    
    try:
        # Find user by username
        user = None
        all_users = await get_all_users()
        for u in all_users:
            if u.get("username") == username:
                user = u
                break
        
        if not user:
            await update.message.reply_text(f"❌ Пользователь с именем {username} не найден.")
            return
        
        user_id = user.get("telegram_id")
        
        # Get all active subscriptions and keys
        subscriptions = await get_user_subscriptions(user_id)
        access_keys = await get_user_access_keys(user_id)
        
        # Delete all keys in Outline
        deleted_keys = 0
        for key in access_keys:
            try:
                key_id = key.get("key_id")
                await outline_service.delete_key(key_id)
                deleted_keys += 1
            except Exception as e:
                logger.error(f"Error deleting key {key.get('key_id')} for user {username}: {e}")
        
        # Update user data
        await update_user(user_id, {"has_active_subscription": False})
        
        # Set all subscriptions to inactive
        for sub in subscriptions:
            sub_id = sub.get("subscription_id")
            await update_subscription(sub_id, {"status": "inactive"})
        
        await update.message.reply_text(
            f"✅ Пользователь {username} успешно удален.\n"
            f"- Удалено ключей: {deleted_keys}/{len(access_keys)}\n"
            f"- Деактивировано подписок: {len(subscriptions)}"
        )
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        await update.message.reply_text(f"❌ Ошибка при удалении пользователя: {str(e)}")

async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /list_users command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    try:
        # Get all users from database
        all_users = await get_all_users()
        
        if not all_users:
            await update.message.reply_text("📊 Пользователи не найдены.")
            return
        
        # Get all keys from Outline API to get usage data
        outline_keys = await outline_service.get_keys()
        
        users_text = "📊 <b>Список пользователей:</b>\n\n"
        
        # Process first 10 users to avoid message too long
        for user in all_users[:10]:
            telegram_id = user.get("telegram_id")
            username = user.get("username", "Unknown")
            first_name = user.get("first_name", "")
            has_active = user.get("has_active_subscription", False)
            
            status = "✅" if has_active else "❌"
            display_name = f"{first_name} ({username})" if first_name else username
            
            # Get user subscriptions
            subscriptions = await get_user_subscriptions(telegram_id, status="active")
            
            # Get user keys
            access_keys = await get_user_access_keys(telegram_id)
            
            # Calculate traffic usage
            total_traffic = 0
            for key in access_keys:
                key_id = key.get("key_id")
                # Check if key exists in outline_keys (metrics data)
                for outline_key in outline_keys.get("keys", []):
                    if str(outline_key.get("id")) == str(key_id):
                        # Add usage data
                        total_traffic += outline_key.get("metrics", {}).get("bytesTransferred", 0)
            
            # Format user information
            users_text += f"👤 <code>{display_name}</code> - {status}\n"
            users_text += f"📈 Трафик: {format_bytes(total_traffic)}\n"
            
            # Show subscription expiry if available
            if subscriptions:
                # Get the latest subscription
                latest_sub = max(subscriptions, key=lambda x: x.get("expires_at", 0))
                expires_at = latest_sub.get("expires_at", 0)
                if expires_at:
                    users_text += f"⏳ До: {format_expiry_date(expires_at)}\n\n"
                else:
                    users_text += "\n"
            else:
                users_text += "\n"
        
        if len(all_users) > 10:
            users_text += f"...и еще {len(all_users) - 10} пользователей"
        
        await update.message.reply_text(users_text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        await update.message.reply_text(f"❌ Ошибка при получении списка пользователей: {str(e)}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /broadcast command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    # Check if we have arguments
    args = context.args
    if not args:
        await update.message.reply_text(
            "❌ Недостаточно аргументов.\n\n"
            "Использование: /broadcast <message>\n"
            "Например: /broadcast Здравствуйте! Это тестовое сообщение."
        )
        return
    
    message = " ".join(args)
    
    try:
        # Get all users from database
        users = await get_all_users()
        
        if not users:
            await update.message.reply_text("❌ Пользователи не найдены.")
            return
        
        sent_count = 0
        for user in users:
            telegram_id = user.get("telegram_id")
            if telegram_id:
                try:
                    await context.bot.send_message(
                        chat_id=telegram_id,
                        text=f"📢 <b>Объявление:</b>\n\n{message}",
                        parse_mode="HTML"
                    )
                    sent_count += 1
                except Exception as e:
                    logger.error(f"Error sending broadcast to {telegram_id}: {e}")
        
        await update.message.reply_text(
            f"✅ Сообщение отправлено {sent_count} из {len(users)} пользователей."
        )
    except Exception as e:
        logger.error(f"Error broadcasting: {e}")
        await update.message.reply_text(f"❌ Ошибка при отправке рассылки: {str(e)}")
