import logging
import os
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import VPN_PLANS, ADMIN_IDS, EXPIRY_NOTIFICATION_DAYS
from services.outline_service import OutlineService
from services.database_service import (
    create_user, get_user, update_user, get_active_subscription,
    create_subscription, update_subscription, get_user_subscriptions,
    create_access_key, get_user_access_keys, get_access_key,
    update_access_key, get_expiring_subscriptions, get_subscription
)
from utils.helpers import format_bytes, format_expiry_date

# Configure logging
logger = logging.getLogger(__name__)

# Initialize Outline service
outline_service = OutlineService()

# Helper Functions

async def ensure_user_exists(user):
    """Ensure user exists in database, create if not"""
    telegram_id = user.id
    existing_user = await get_user(telegram_id)
    
    if not existing_user:
        # Create new user
        user_data = {
            "telegram_id": telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "created_at": datetime.now(),
            "is_premium": False,
            "test_used": False
        }
        await create_user(user_data)
        logger.info(f"Created new user: {telegram_id}")
        return user_data
    return existing_user

async def create_vpn_access(user_id, subscription_id, plan_id, days, name=None):
    """Create VPN access key and save to database"""
    # Get plan details
    plan = VPN_PLANS.get(plan_id)
    if not plan:
        logger.error(f"Invalid plan ID: {plan_id}")
        return None
    
    # Create key with expiration in Outline VPN
    key_name = name or f"User {user_id}"
    key_data = await outline_service.create_key_with_expiration(days, key_name)
    
    if not key_data or (isinstance(key_data, dict) and "error" in key_data):
        error_msg = key_data.get("error", "Unknown error") if isinstance(key_data, dict) else "Failed to create key"
        logger.error(f"Failed to create Outline key: {error_msg}")
        return None
    
    # Save key to database
    access_key = {
        "user_id": user_id,
        "subscription_id": subscription_id,
        "key_id": key_data.get("id"),
        "name": key_data.get("name"),
        "access_url": key_data.get("accessUrl"),
        "created_at": datetime.now(),
        "deleted": False
    }
    
    try:
        saved_key = await create_access_key(access_key)
        logger.info(f"Created VPN access key for user {user_id}, subscription {subscription_id}")
        
        # Для случая, когда create_access_key возвращает ORM-объект
        if hasattr(saved_key, 'key_id') and not isinstance(saved_key, dict):
            return {
                "key_id": saved_key.key_id,
                "name": saved_key.name,
                "access_url": saved_key.access_url
            }
        return saved_key
    except Exception as e:
        logger.error(f"Failed to save access key to database: {e}")
        # Всё равно возвращаем созданный ключ, чтобы пользователь мог им воспользоваться
        return {
            "key_id": key_data.get("id"),
            "name": key_data.get("name"),
            "access_url": key_data.get("accessUrl")
        }

async def check_subscription_expiry():
    """Check for expiring subscriptions and notify users"""
    try:
        # Get subscriptions expiring in the specified days
        expiring_subs = await get_expiring_subscriptions(EXPIRY_NOTIFICATION_DAYS)
        
        if not expiring_subs:
            logger.info("No expiring subscriptions found")
            return
        
        logger.info(f"Found {len(expiring_subs)} expiring subscriptions")
        
        # Send notification to each user
        for sub in expiring_subs:
            user_id = sub.get("user_id")
            expires_at = sub.get("expires_at")
            
            if not user_id or not expires_at:
                continue
                
            expiry_str = format_expiry_date(expires_at)
            plan_id = sub.get("plan_id")
            plan_name = VPN_PLANS.get(plan_id, {}).get("name", "VPN")
            
            message = (
                f"⚠️ *Ваша подписка скоро истекает* ⚠️\n\n"
                f"План: *{plan_name}*\n"
                f"Дата окончания: *{expiry_str}*\n\n"
                f"Чтобы продолжить пользоваться услугой, пожалуйста, продлите подписку."
            )
            
            # Create keyboard with renewal options
            keyboard = [
                [InlineKeyboardButton("🔄 Продлить подписку", callback_data="plans")],
                [InlineKeyboardButton("ℹ️ Мой статус", callback_data="status")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            try:
                from telegram import Bot
                bot = Bot(token=os.environ.get("BOT_TOKEN"))
                await bot.send_message(
                    chat_id=user_id,
                    text=message,
                    parse_mode="Markdown",
                    reply_markup=reply_markup
                )
                logger.info(f"Sent expiry notification to user {user_id}")
            except Exception as e:
                logger.error(f"Failed to send expiry notification to user {user_id}: {e}")
    
    except Exception as e:
        logger.error(f"Error checking subscription expiry: {e}")

# Command Handlers

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    welcome_message = (
        f"Привет, {user.first_name}! 👋\n\n"
        f"Я бот для управления VPN-подключением. С моей помощью вы можете получить "
        f"доступ к стабильному и быстрому VPN сервису.\n\n"
        f"*Что я умею:*\n"
        f"• Предоставлять защищенный доступ к сети интернет\n"
        f"• Поддерживать несколько устройств на одном аккаунте\n"
        f"• Предоставлять информацию о состоянии вашей подписки\n\n"
        f"Выберите действие из меню ниже:"
    )
    
    # Check if user has active subscription
    subscription = await get_active_subscription(user.id)
    
    # Prepare keyboard based on subscription status
    keyboard = []
    
    if subscription:
        # User has active subscription
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("📊 Статус подписки", callback_data="status")],
            [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
        ]
    else:
        # User hasn't used test period yet
        db_user = await get_user(user.id)
        test_used = db_user.get("test_used", False) if db_user else False
        
        if not test_used:
            keyboard = [
                [InlineKeyboardButton("🔍 Попробовать бесплатно", callback_data="test_period")],
                [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
            ]
        else:
            keyboard = [
                [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
            ]
    
    # Add admin button if user is admin
    if user.id in ADMIN_IDS:
        keyboard.append([InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        welcome_message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /status command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    # Get active subscription
    subscription = await get_active_subscription(user.id)
    
    if not subscription:
        # No active subscription
        message = (
            "У вас нет активной подписки.\n\n"
            "Для начала использования VPN выберите тарифный план:"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup
        )
        return
    
    # Get plan details
    plan_id = subscription.get("plan_id")
    plan = VPN_PLANS.get(plan_id, {})
    
    # Get access keys for this subscription
    subscription_id = subscription.get("_id")
    access_keys = await get_user_access_keys(user.id)
    
    # Filter keys for current subscription
    valid_keys = [key for key in access_keys if str(key.get("subscription_id")) == str(subscription_id)]
    
    # Format expiry date
    expires_at = subscription.get("expires_at")
    expiry_str = format_expiry_date(expires_at) if expires_at else "Неизвестно"
    
    message = (
        f"*Информация о подписке:*\n\n"
        f"*План:* {plan.get('name', 'Неизвестно')}\n"
        f"*Статус:* Активна\n"
        f"*Действует до:* {expiry_str}\n"
        f"*Доступно устройств:* {plan.get('devices', 1)}\n"
        f"*Используется устройств:* {len(valid_keys)}\n\n"
    )
    
    # Add access key information if available
    if valid_keys:
        message += "*Ваши ключи доступа:*\n\n"
        for i, key in enumerate(valid_keys, 1):
            key_name = key.get("name", f"Ключ {i}")
            message += f"{i}. {key_name}\n"
    
    keyboard = [
        [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
        [InlineKeyboardButton("🔄 Продлить подписку", callback_data="plans")],
        [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /plans command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    message = "*Доступные тарифные планы:*\n\n"
    
    # Skip test plan in regular plans view
    regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
    
    for plan_id, plan in regular_plans.items():
        discount = f" (скидка {plan.get('discount')})" if plan.get('discount') else ""
        message += (
            f"*{plan['name']}*{discount}\n"
            f"Стоимость: *{plan['price']} руб.*\n"
            f"Срок действия: {plan['duration']} дней\n"
            f"Устройств: до {plan.get('devices', 1)}\n"
            f"{plan.get('description', '')}\n\n"
        )
    
    # Create keyboard with plan options
    keyboard = []
    for plan_id, plan in regular_plans.items():
        keyboard.append([InlineKeyboardButton(
            f"{plan['name']} - {plan['price']} руб.", 
            callback_data=f"buy_{plan_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def keys_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /keys command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    # Get active subscription
    subscription = await get_active_subscription(user.id)
    
    if not subscription:
        # No active subscription
        message = (
            "У вас нет активной подписки.\n\n"
            "Для получения ключей доступа выберите тарифный план:"
        )
        
        keyboard = [
            [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup
        )
        return
    
    # Get access keys for this user
    access_keys = await get_user_access_keys(user.id)
    
    # Get plan details
    plan_id = subscription.get("plan_id")
    plan = VPN_PLANS.get(plan_id, {})
    max_devices = plan.get("devices", 1)
    
    if not access_keys:
        message = (
            "У вас пока нет ключей доступа.\n\n"
            "Нажмите кнопку ниже, чтобы создать новый ключ:"
        )
        
        keyboard = [
            [InlineKeyboardButton("➕ Создать ключ", callback_data="create_key")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message,
            reply_markup=reply_markup
        )
        return
    
    message = (
        f"*Ваши ключи доступа ({len(access_keys)}/{max_devices}):*\n\n"
    )
    
    # Add access key information
    for i, key in enumerate(access_keys, 1):
        key_name = key.get("name", f"Ключ {i}")
        created_at = key.get("created_at")
        created_str = created_at.strftime("%d.%m.%Y") if created_at else "Неизвестно"
        key_id = key.get("key_id")
        
        message += f"{i}. *{key_name}*\n"
        message += f"   Создан: {created_str}\n\n"
    
    # Create keyboard based on number of keys
    keyboard = []
    
    # Add individual key buttons
    for i, key in enumerate(access_keys, 1):
        key_id = key.get("key_id")
        keyboard.append([InlineKeyboardButton(f"📲 Показать ссылку для ключа {i}", callback_data=f"show_key_{key_id}")])
    
    if len(access_keys) < max_devices:
        keyboard.append([InlineKeyboardButton("➕ Создать ключ", callback_data="create_key")])
    
    keyboard.append([InlineKeyboardButton("📱 Инструкция по подключению", callback_data="help")])
    keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command"""
    user = update.effective_user
    
    message = (
        "*Инструкция по подключению VPN*\n\n"
        "Для использования нашего VPN сервиса вам потребуется:\n\n"
        "*1. Установить приложение Outline*\n"
        "• [Android](https://play.google.com/store/apps/details?id=org.outline.android.client)\n"
        "• [iOS](https://apps.apple.com/us/app/outline-app/id1356177741)\n"
        "• [Windows](https://s3.amazonaws.com/outline-releases/client/windows/stable/Outline-Client.exe)\n"
        "• [macOS](https://s3.amazonaws.com/outline-releases/client/macos/stable/Outline-Client.dmg)\n"
        "• [Linux](https://s3.amazonaws.com/outline-releases/client/linux/stable/Outline-Client.AppImage)\n\n"
        "*2. Добавить ключ доступа:*\n"
        "• Получите ключ доступа в разделе «Мои ключи»\n"
        "• Нажмите на кнопку «Скопировать ключ» или «Открыть в приложении»\n"
        "• Если нажали «Скопировать ключ», откройте приложение Outline и нажмите «+» для добавления ключа\n\n"
        "*3. Подключение к VPN:*\n"
        "• После добавления ключа, нажмите кнопку «Подключить» в приложении\n"
        "• Подтвердите запрос на установку VPN-профиля, если потребуется\n\n"
        "Если у вас возникли проблемы с подключением, обратитесь в поддержку, нажав кнопку ниже."
    )
    
    keyboard = [
        [InlineKeyboardButton("📞 Поддержка", url="https://t.me/your_support_username")],
        [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

# Callback Handlers

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user = update.effective_user
    
    # Admin panel
    if data == "admin":
        if user.id not in ADMIN_IDS:
            await query.edit_message_text("⛔ У вас нет доступа к этой команде.")
            return
        
        keyboard = [
            [InlineKeyboardButton("👥 Список пользователей", callback_data="admin_list_users")],
            [InlineKeyboardButton("➕ Добавить пользователя", callback_data="admin_add_user")],
            [InlineKeyboardButton("🗑️ Удалить пользователя", callback_data="admin_delete_user")],
            [InlineKeyboardButton("📢 Рассылка", callback_data="admin_broadcast")],
            [InlineKeyboardButton("📊 Статистика", callback_data="admin_stats")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🛠️ <b>Панель администратора</b>\n\n"
            "Выберите действие из списка ниже:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    # Main menu navigation
    elif data == "back_to_main":
        # Simulate /start command but edit message instead of sending new one
        welcome_message = (
            f"Привет, {user.first_name}! 👋\n\n"
            f"Я бот для управления VPN-подключением. С моей помощью вы можете получить "
            f"доступ к стабильному и быстрому VPN сервису.\n\n"
            f"*Что я умею:*\n"
            f"• Предоставлять защищенный доступ к сети интернет\n"
            f"• Поддерживать несколько устройств на одном аккаунте\n"
            f"• Предоставлять информацию о состоянии вашей подписки\n\n"
            f"Выберите действие из меню ниже:"
        )
        
        # Check if user has active subscription
        subscription = await get_active_subscription(user.id)
        
        # Prepare keyboard based on subscription status
        keyboard = []
        
        if subscription:
            # User has active subscription
            keyboard = [
                [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
                [InlineKeyboardButton("📊 Статус подписки", callback_data="status")],
                [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
            ]
        else:
            # User hasn't used test period yet
            db_user = await get_user(user.id)
            test_used = db_user.get("test_used", False) if db_user else False
            
            if not test_used:
                keyboard = [
                    [InlineKeyboardButton("🔍 Попробовать бесплатно", callback_data="test_period")],
                    [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                    [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
                ]
            else:
                keyboard = [
                    [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                    [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
                ]
        
        # Add admin button if user is admin
        if user.id in ADMIN_IDS:
            keyboard.append([InlineKeyboardButton("🔐 Админ-панель", callback_data="admin")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            welcome_message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Status callback
    elif data == "status":
        # Get active subscription
        subscription = await get_active_subscription(user.id)
        
        if not subscription:
            # No active subscription
            message = (
                "У вас нет активной подписки.\n\n"
                "Для начала использования VPN выберите тарифный план:"
            )
            
            keyboard = [
                [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
            return
        
        # Get plan details
        plan_id = subscription.get("plan_id")
        plan = VPN_PLANS.get(plan_id, {})
        
        # Get access keys for this subscription
        subscription_id = subscription.get("_id")
        access_keys = await get_user_access_keys(user.id)
        
        # Filter keys for current subscription
        valid_keys = [key for key in access_keys if str(key.get("subscription_id")) == str(subscription_id)]
        
        # Format expiry date
        expires_at = subscription.get("expires_at")
        expiry_str = format_expiry_date(expires_at) if expires_at else "Неизвестно"
        
        message = (
            f"*Информация о подписке:*\n\n"
            f"*План:* {plan.get('name', 'Неизвестно')}\n"
            f"*Статус:* Активна\n"
            f"*Действует до:* {expiry_str}\n"
            f"*Доступно устройств:* {plan.get('devices', 1)}\n"
            f"*Используется устройств:* {len(valid_keys)}\n\n"
        )
        
        # Add access key information if available
        if valid_keys:
            message += "*Ваши ключи доступа:*\n\n"
            for i, key in enumerate(valid_keys, 1):
                key_name = key.get("name", f"Ключ {i}")
                message += f"{i}. {key_name}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("🔄 Продлить подписку", callback_data="plans")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Plans callback
    elif data == "plans":
        message = "*Доступные тарифные планы:*\n\n"
        
        # Skip test plan in regular plans view
        regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
        
        for plan_id, plan in regular_plans.items():
            discount = f" (скидка {plan.get('discount')})" if plan.get('discount') else ""
            message += (
                f"*{plan['name']}*{discount}\n"
                f"Стоимость: *{plan['price']} руб.*\n"
                f"Срок действия: {plan['duration']} дней\n"
                f"Устройств: до {plan.get('devices', 1)}\n"
                f"{plan.get('description', '')}\n\n"
            )
        
        # Create keyboard with plan options
        keyboard = []
        for plan_id, plan in regular_plans.items():
            keyboard.append([InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} руб.", 
                callback_data=f"buy_{plan_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Keys callback
    elif data == "keys":
        # Get active subscription
        subscription = await get_active_subscription(user.id)
        
        if not subscription:
            # No active subscription
            message = (
                "У вас нет активной подписки.\n\n"
                "Для получения ключей доступа выберите тарифный план:"
            )
            
            keyboard = [
                [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
            return
        
        # Get access keys for this user
        access_keys = await get_user_access_keys(user.id)
        
        # Get plan details
        plan_id = subscription.get("plan_id")
        plan = VPN_PLANS.get(plan_id, {})
        max_devices = plan.get("devices", 1)
        
        if not access_keys:
            message = (
                "У вас пока нет ключей доступа.\n\n"
                "Нажмите кнопку ниже, чтобы создать новый ключ:"
            )
            
            keyboard = [
                [InlineKeyboardButton("➕ Создать ключ", callback_data="create_key")],
                [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
            return
        
        message = (
            f"*Ваши ключи доступа ({len(access_keys)}/{max_devices}):*\n\n"
        )
        
        # Add access key information
        for i, key in enumerate(access_keys, 1):
            key_name = key.get("name", f"Ключ {i}")
            created_at = key.get("created_at")
            created_str = created_at.strftime("%d.%m.%Y") if created_at else "Неизвестно"
            
            message += f"{i}. *{key_name}*\n"
            message += f"   Создан: {created_str}\n"
            message += f"   [Показать/скопировать ключ](callback_data=show_key_{key.get('key_id')})\n\n"
        
        # Create keyboard based on number of keys
        keyboard = []
        
        for i, key in enumerate(access_keys, 1):
            keyboard.append([InlineKeyboardButton(
                f"Ключ {i}: {key.get('name', 'Без имени')}",
                callback_data=f"show_key_{key.get('key_id')}"
            )])
        
        if len(access_keys) < max_devices:
            keyboard.append([InlineKeyboardButton("➕ Создать ключ", callback_data="create_key")])
        
        keyboard.append([InlineKeyboardButton("📱 Инструкция по подключению", callback_data="help")])
        keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Help callback
    elif data == "help":
        message = (
            "*Инструкция по подключению VPN*\n\n"
            "Для использования нашего VPN сервиса вам потребуется:\n\n"
            "*1. Установить приложение Outline*\n"
            "• [Android](https://play.google.com/store/apps/details?id=org.outline.android.client)\n"
            "• [iOS](https://apps.apple.com/us/app/outline-app/id1356177741)\n"
            "• [Windows](https://s3.amazonaws.com/outline-releases/client/windows/stable/Outline-Client.exe)\n"
            "• [macOS](https://s3.amazonaws.com/outline-releases/client/macos/stable/Outline-Client.dmg)\n"
            "• [Linux](https://s3.amazonaws.com/outline-releases/client/linux/stable/Outline-Client.AppImage)\n\n"
            "*2. Добавить ключ доступа:*\n"
            "• Получите ключ доступа в разделе «Мои ключи»\n"
            "• Нажмите на кнопку «Скопировать ключ» или «Открыть в приложении»\n"
            "• Если нажали «Скопировать ключ», откройте приложение Outline и нажмите «+» для добавления ключа\n\n"
            "*3. Подключение к VPN:*\n"
            "• После добавления ключа, нажмите кнопку «Подключить» в приложении\n"
            "• Подтвердите запрос на установку VPN-профиля, если потребуется\n\n"
            "Если у вас возникли проблемы с подключением, обратитесь в поддержку, нажав кнопку ниже."
        )
        
        keyboard = [
            [InlineKeyboardButton("📞 Поддержка", url="https://t.me/your_support_username")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        return
    
    # Test period
    elif data == "test_period":
        # Get user and check if test period already used
        db_user = await get_user(user.id)
        test_used = db_user.get("test_used", False) if db_user else False
        
        if test_used:
            message = (
                "Вы уже использовали бесплатный тестовый период.\n\n"
                "Выберите тарифный план для продолжения использования VPN:"
            )
            
            keyboard = [
                [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                message,
                reply_markup=reply_markup
            )
            return
        
        # Get test plan
        test_plan = VPN_PLANS.get("test")
        if not test_plan:
            await query.edit_message_text(
                "Тестовый период временно недоступен. Пожалуйста, выберите один из наших тарифных планов.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")
                ]])
            )
            return
        
        # Создаем уникальный ID для подписки
        import uuid
        subscription_id = str(uuid.uuid4())
        
        # Create subscription
        subscription_data = {
            "user_id": user.id,
            "subscription_id": subscription_id,
            "plan_id": "test",
            "status": "active",
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(days=test_plan["duration"]),
            "price_paid": 0
        }
        
        new_subscription = await create_subscription(subscription_data)
        
        if not new_subscription:
            await query.edit_message_text(
                "Произошла ошибка при активации тестового периода. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Получаем ID подписки (может быть разный формат в зависимости от типа БД)
        if isinstance(new_subscription, dict):
            # MongoDB возвращает словарь
            subscription_id = new_subscription.get("_id", subscription_id)
        else:
            # SQLAlchemy возвращает объект
            subscription_id = getattr(new_subscription, "id", subscription_id)
        
        # Create VPN access key
        key = await create_vpn_access(
            user.id, 
            subscription_id, 
            "test", 
            test_plan["duration"], 
            f"Test - {user.first_name}"
        )
        
        if not key:
            await query.edit_message_text(
                "Произошла ошибка при создании ключа доступа. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Mark test period as used
        await update_user(user.id, {"test_used": True})
        
        # Send success message with access key
        message = (
            f"*Тестовый период активирован!*\n\n"
            f"Вы получили бесплатный доступ к VPN на {test_plan['duration']} дня.\n\n"
            f"*Ваш ключ доступа:*\n"
            f"{key.get('access_url')}\n\n"
            f"Используйте этот ключ для подключения к VPN через приложение Outline.\n\n"
            f"*Важно:* Сохраните этот ключ или нажмите кнопку 'Мои ключи' для доступа к нему позже.\n\n"
            f"*Срок действия:* до {format_expiry_date(new_subscription.get('expires_at'))}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("📱 Как подключиться", callback_data="help")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    
    # Create key
    elif data.startswith("delete_key_"):
        # Extract key ID from callback data
        key_id = data.replace("delete_key_", "")
        
        # Get access key
        key = await get_access_key(key_id)
        
        if not key:
            await query.edit_message_text(
                "⚠️ Ключ не найден или уже был удален.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад к списку ключей", callback_data="keys")]
                ])
            )
            return
        
        try:
            # Delete key in Outline
            await outline_service.delete_key(key_id)
            
            # Update status in database
            await update_access_key(key_id, {"deleted": True, "deleted_at": datetime.now()})
            
            # Confirm deletion
            await query.edit_message_text(
                "✅ Ключ успешно удален!",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад к списку ключей", callback_data="keys")]
                ])
            )
        except Exception as e:
            logger.error(f"Error deleting key {key_id}: {e}")
            await query.edit_message_text(
                "❌ Ошибка при удалении ключа. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад к списку ключей", callback_data="keys")]
                ])
            )
    
    elif data.startswith("show_key_"):
        # Extract key ID from callback data
        key_id = data.replace("show_key_", "")
        
        # Get access key
        key = await get_access_key(key_id)
        
        if not key:
            await query.edit_message_text(
                "⚠️ Ключ не найден или был удален.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("↩️ Назад к списку ключей", callback_data="keys")]
                ])
            )
            return
        
        # Get key name and access URL
        key_name = key.get("name", "Ключ без имени")
        access_url = key.get("access_url", "Ссылка недоступна")
        
        message = (
            f"*Информация о ключе:* {key_name}\n\n"
            f"Для подключения устройства, откройте приложение Outline и добавьте доступ по ссылке ниже:\n\n"
            f"`{access_url}`\n\n"
            f"Или отсканируйте QR-код в приложении Outline.\n\n"
            f"Инструкция по установке Outline доступна по команде /help."
        )
        
        # Create keyboard
        keyboard = [
            [InlineKeyboardButton("🗑️ Удалить ключ", callback_data=f"delete_key_{key_id}")],
            [InlineKeyboardButton("↩️ Назад к списку ключей", callback_data="keys")],
            [InlineKeyboardButton("📱 Инструкция по подключению", callback_data="help")]
        ]
        
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        
    elif data == "create_key":
        # Get active subscription
        subscription = await get_active_subscription(user.id)
        
        if not subscription:
            await query.edit_message_text(
                "У вас нет активной подписки для создания ключа.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Тарифные планы", callback_data="plans"),
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Get current keys and check limit
        access_keys = await get_user_access_keys(user.id)
        plan_id = subscription.get("plan_id")
        plan = VPN_PLANS.get(plan_id, {})
        max_devices = plan.get("devices", 1)
        
        if len(access_keys) >= max_devices:
            await query.edit_message_text(
                f"Вы достигли максимального количества ключей ({max_devices}) для вашего тарифа.\n\n"
                f"Чтобы создать больше ключей, перейдите на тариф с большим количеством устройств.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ])
            )
            return
        
        # Получаем ID подписки (может быть разный формат в зависимости от типа БД)
        if isinstance(subscription, dict):
            # MongoDB возвращает словарь
            subscription_id = subscription.get("_id")
            expires_at = subscription.get("expires_at")
        else:
            # SQLAlchemy возвращает объект
            subscription_id = getattr(subscription, "id", None)
            expires_at = getattr(subscription, "expires_at", None)
        
        if not subscription_id:
            await query.edit_message_text(
                "Произошла ошибка при получении информации о подписке. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Вычисляем оставшиеся дни
        remaining_days = 30  # Значение по умолчанию, если не сможем рассчитать
        if expires_at:
            if isinstance(expires_at, str):
                try:
                    expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    pass
            
            if isinstance(expires_at, datetime):
                delta = expires_at - datetime.now()
                remaining_days = max(delta.days, 1)  # Минимум 1 день
            
        key_name = f"Device {len(access_keys) + 1} - {user.first_name}"
        key = await create_vpn_access(user.id, subscription_id, plan_id, remaining_days, key_name)
        
        if not key:
            await query.edit_message_text(
                "Произошла ошибка при создании ключа доступа. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Send success message with access key
        message = (
            f"*Новый ключ доступа создан!*\n\n"
            f"*Имя:* {key.get('name')}\n"
            f"*Ключ:* `{key.get('access_url')}`\n\n"
            f"Используйте этот ключ для подключения к VPN через приложение Outline.\n\n"
            f"*Срок действия:* до {format_expiry_date(subscription.get('expires_at'))}"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("📱 Как подключиться", callback_data="help")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    
    # Show key details
    elif data.startswith("show_key_"):
        key_id = data.replace("show_key_", "")
        
        # Get key details
        key = await get_access_key(key_id)
        
        if not key:
            await query.edit_message_text(
                "Ключ не найден или был удален.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔑 Мои ключи", callback_data="keys"),
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Get subscription
        subscription_id = key.get("subscription_id")
        subscription = await get_subscription(subscription_id) if subscription_id else None
        
        # Format expiry date
        expires_at = subscription.get("expires_at") if subscription else None
        expiry_str = format_expiry_date(expires_at) if expires_at else "Неизвестно"
        
        message = (
            f"*Информация о ключе доступа*\n\n"
            f"*Имя:* {key.get('name')}\n"
            f"*Создан:* {key.get('created_at').strftime('%d.%m.%Y') if key.get('created_at') else 'Неизвестно'}\n"
            f"*Действует до:* {expiry_str}\n\n"
            f"*Ключ доступа:*\n`{key.get('access_url')}`\n\n"
            f"Скопируйте этот ключ и добавьте его в приложение Outline."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("📱 Как подключиться", callback_data="help")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    
    # Buy plan
    elif data.startswith("buy_"):
        plan_id = data.replace("buy_", "")
        plan = VPN_PLANS.get(plan_id)
        
        if not plan:
            await query.edit_message_text(
                "Выбранный тарифный план не найден.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("💳 Тарифные планы", callback_data="plans"),
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # For testing, since YooKassa integration not implemented yet
        # In production, this should generate a payment link
        # Create temporary fake payment and let user manually confirm it
        payment_id = f"test_payment_{plan_id}_{user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Create subscription (inactive until payment confirmed)
        subscription_data = {
            "user_id": user.id,
            "plan_id": plan_id,
            "status": "pending",
            "created_at": datetime.now(),
            "expires_at": datetime.now() + timedelta(days=plan["duration"]),
            "price": plan["price"],
            "payment_id": payment_id
        }
        
        new_subscription = await create_subscription(subscription_data)
        
        if not new_subscription:
            await query.edit_message_text(
                "Произошла ошибка при создании подписки. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
            
        message = (
            f"*Оформление подписки: {plan['name']}*\n\n"
            f"Стоимость: *{plan['price']} руб.*\n"
            f"Срок действия: {plan['duration']} дней\n"
            f"Максимум устройств: {plan.get('devices', 1)}\n\n"
            f"{plan.get('description', '')}\n\n"
            f"Для активации этого плана, пожалуйста, выполните следующие шаги:\n\n"
            f"1. Перейдите по ссылке оплаты\n"
            f"2. Выполните платеж по инструкции\n"
            f"3. После оплаты нажмите «Проверить статус платежа»\n\n"
        )
        
        # In a real implementation, use YooKassa to create a payment
        # and provide a proper URL here
        
        keyboard = [
            [InlineKeyboardButton("💲 Перейти к оплате", callback_data=f"payment_placeholder_{new_subscription['_id']}")],
            [InlineKeyboardButton("🔄 Проверить статус платежа", callback_data=f"check_payment_{new_subscription['_id']}")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Payment placeholder
    elif data.startswith("payment_placeholder_"):
        subscription_id = data.replace("payment_placeholder_", "")
        
        # Get subscription
        subscription = await get_subscription(subscription_id)
        
        if not subscription:
            await query.edit_message_text(
                "Подписка не найдена или была удалена.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
            
        plan_id = subscription.get("plan_id")
        plan = VPN_PLANS.get(plan_id, {})
        
        # In a test implementation, automatically confirm payment
        # In production, this would redirect to YooKassa
        
        message = (
            f"*Тестовый режим оплаты*\n\n"
            f"В режиме тестирования, платеж автоматически считается успешным.\n\n"
            f"План: *{plan.get('name', 'Неизвестно')}*\n"
            f"Стоимость: *{plan.get('price', 0)} руб.*\n\n"
            f"Нажмите кнопку «Считать оплаченным» для имитации успешного платежа."
        )
        
        keyboard = [
            [InlineKeyboardButton("✅ Считать оплаченным", callback_data=f"simulate_payment_{subscription_id}")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Check payment status
    elif data.startswith("check_payment_"):
        subscription_id = data.replace("check_payment_", "")
        
        # Get subscription
        subscription = await get_subscription(subscription_id)
        
        if not subscription:
            await query.edit_message_text(
                "Подписка не найдена или была удалена.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
            
        # Check payment status
        status = subscription.get("status")
        
        if status == "active":
            # Payment successful, show access keys
            await query.edit_message_text(
                "Ваш платеж успешно обработан! Подписка активирована.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ])
            )
            return
        elif status == "pending":
            # Payment still pending
            await query.edit_message_text(
                "Ваш платеж еще обрабатывается. Пожалуйста, проверьте статус позже.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Проверить статус платежа", callback_data=f"check_payment_{subscription_id}")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ])
            )
            return
        else:
            # Payment failed or cancelled
            await query.edit_message_text(
                "Платеж не удался или был отменен. Пожалуйста, попробуйте снова.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ])
            )
            return
            
    # Simulate payment (for testing)
    elif data.startswith("simulate_payment_"):
        subscription_id = data.replace("simulate_payment_", "")
        
        # Get subscription
        subscription = await get_subscription(subscription_id)
        
        if not subscription:
            await query.edit_message_text(
                "Подписка не найдена или была удалена.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
            
        # Update subscription to active
        await update_subscription(subscription_id, {"status": "active"})
        
        # Get plan
        plan_id = subscription.get("plan_id")
        plan = VPN_PLANS.get(plan_id, {})
        
        # Create VPN access key
        key = await create_vpn_access(
            user.id, 
            subscription_id, 
            plan_id, 
            plan.get("duration", 30), 
            f"{plan.get('name', 'VPN')} - {user.first_name}"
        )
        
        if not key:
            await query.edit_message_text(
                "Платеж обработан, но произошла ошибка при создании ключа доступа. Пожалуйста, обратитесь в поддержку.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
        
        # Send success message with access key
        message = (
            f"*Подписка успешно активирована!*\n\n"
            f"План: *{plan.get('name', 'VPN')}*\n"
            f"Срок действия: до {format_expiry_date(subscription.get('expires_at'))}\n\n"
            f"*Ваш ключ доступа:*\n"
            f"`{key.get('access_url')}`\n\n"
            f"Используйте этот ключ для подключения к VPN через приложение Outline.\n\n"
            f"Вы можете создать дополнительные ключи (до {plan.get('devices', 1)} устройств) в разделе 'Мои ключи'."
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Мои ключи", callback_data="keys")],
            [InlineKeyboardButton("📱 Как подключиться", callback_data="help")],
            [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            message,
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
    
    # If none of the above conditions match, return to main menu
    await query.edit_message_text(
        "Произошла ошибка. Пожалуйста, вернитесь в главное меню и попробуйте снова.",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
        ]])
    )