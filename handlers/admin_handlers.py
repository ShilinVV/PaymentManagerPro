import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bson import ObjectId

from config import ADMIN_IDS, VPN_PLANS
from services.outline_service import OutlineService
from services.database_service import (
    get_user,
    get_all_users,
    update_user,
    create_user,
    create_subscription,
    update_subscription,
    get_user_subscriptions,
    get_active_subscription
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
        # Get all users from Marzban
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
            
            users_text = "📊 <b>Список пользователей:</b>\n\n"
            
            for user in all_users[:10]:  # Limit to 10 users to avoid message too long
                telegram_id = user.get("telegram_id")
                username = user.get("username", "Unknown")
                full_name = user.get("full_name", "Unknown")
                # Get user's active subscription
                active_subscription = await get_active_subscription(telegram_id)
                if active_subscription:
                    plan_id = active_subscription.get("plan_id", "unknown")
                    plan_name = VPN_PLANS.get(plan_id, {}).get("name", "Unknown")
                    status = "✅ Active"
                    expiry = format_expiry_date(active_subscription.get("expires_at", 0))
                    
                    # Get access keys for subscription
                    access_keys = await get_user_access_keys(telegram_id)
                    
                    # Calculate usage
                    total_usage = 0
                    for key in access_keys:
                        key_metrics = key.get("metrics", {})
                        key_usage = key_metrics.get("bytesTransferred", 0)
                        total_usage += key_usage
                    
                    used = format_bytes(total_usage)
                else:
                    status = "❌ No active subscription"
                    used = "0 B"
                    expiry = "N/A"
                
                users_text += f"👤 <code>{full_name}</code> (@{username}) - {status}\n"
                
                if active_subscription:
                    plan_id = active_subscription.get("plan_id", "unknown")
                    plan_name = VPN_PLANS.get(plan_id, {}).get("name", "Unknown")
                    users_text += f"🔑 План: {plan_name}\n"
                    users_text += f"📈 Трафик: {used}\n"
                    users_text += f"⏳ До: {expiry}\n\n"
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
        # Get statistics
        try:
            marzban_users = await marzban_service.get_all_users()
            db_users = await get_all_users()
            
            total_marzban_users = len(marzban_users) if marzban_users else 0
            total_db_users = len(db_users) if db_users else 0
            
            active_users = sum(1 for user in marzban_users if user.get("status") == "active") if marzban_users else 0
            
            total_traffic = sum(user.get("used_traffic", 0) for user in marzban_users) if marzban_users else 0
            
            stats_text = "📊 <b>Статистика:</b>\n\n"
            stats_text += f"👥 Всего пользователей в базе: {total_db_users}\n"
            stats_text += f"👥 Всего аккаунтов в Marzban: {total_marzban_users}\n"
            stats_text += f"✅ Активных аккаунтов: {active_users}\n"
            stats_text += f"📈 Общий трафик: {format_bytes(total_traffic)}\n"
            
            await query.edit_message_text(
                stats_text,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="admin_back")
                ]]),
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
        await marzban_service.create_user(
            username,
            data_limit=plan['data_limit'],
            days=plan['duration']
        )
        
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
        # Delete user from Marzban
        success = await marzban_service.delete_user(username)
        
        if success:
            await update.message.reply_text(f"✅ Пользователь {username} успешно удален.")
        else:
            await update.message.reply_text(f"❌ Не удалось удалить пользователя {username}.")
    except Exception as e:
        logger.error(f"Error deleting user: {e}")
        await update.message.reply_text(f"❌ Ошибка при удалении пользователя: {str(e)}")

async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /list_users command"""
    if not await is_admin(update):
        await update.message.reply_text("⛔ У вас нет доступа к этой команде.")
        return
    
    try:
        # Get all users from Marzban
        marzban_users = await marzban_service.get_all_users()
        
        if not marzban_users:
            await update.message.reply_text("📊 Пользователи не найдены.")
            return
        
        users_text = "📊 <b>Список пользователей:</b>\n\n"
        
        for user in marzban_users[:10]:  # Limit to 10 users to avoid message too long
            username = user.get("username", "Unknown")
            status = "✅" if user.get("status") == "active" else "❌"
            used = format_bytes(user.get("used_traffic", 0))
            data_limit = format_bytes(user.get("data_limit", 0)) if user.get("data_limit") else "∞"
            expiry = format_expiry_date(user.get("expire", 0))
            
            users_text += f"👤 <code>{username}</code> - {status}\n"
            users_text += f"📈 Трафик: {used} / {data_limit}\n"
            users_text += f"⏳ До: {expiry}\n\n"
        
        if len(marzban_users) > 10:
            users_text += f"...и еще {len(marzban_users) - 10} пользователей"
        
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
