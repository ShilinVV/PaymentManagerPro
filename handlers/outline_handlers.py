import os
import uuid
import logging
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import VPN_PLANS, ADMIN_IDS
from services.database_service_sql import (
    get_user, create_user, update_user, get_all_users,
    get_subscription, create_subscription, update_subscription, get_user_subscriptions,
    get_active_subscription, get_expiring_subscriptions,
    get_user_access_keys, create_access_key, get_access_key, update_access_key,
    get_payment, create_payment, update_payment
)
from services.outline_service import OutlineService
from utils.helpers import format_bytes, format_expiry_date, calculate_expiry

# Initialize Outline service
outline_service = OutlineService()

async def ensure_user_exists(user):
    """Ensure user exists in database, create if not"""
    if not user:
        return
    
    # Check if user exists
    db_user = await get_user(user.id)
    
    if not db_user:
        # Create new user
        user_data = {
            "telegram_id": user.id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "created_at": datetime.now()
        }
        await create_user(user_data)

async def create_vpn_access(user_id, subscription_id, plan_id, days, name=None):
    """Create VPN access key and save to database"""
    # Create key with Outline API
    outline_key = await outline_service.create_key_with_expiration(days, name)
    
    if not outline_key:
        return None
    
    # Save key to database
    key_data = {
        "key_id": outline_key.get("id"),
        "name": name or f"VPN Key {datetime.now().strftime('%Y-%m-%d')}",
        "access_url": outline_key.get("accessUrl"),
        "user_id": user_id,
        "subscription_id": subscription_id,
        "created_at": datetime.now()
    }
    
    new_key = await create_access_key(key_data)
    return new_key
    
async def extend_vpn_access(key_id, user_id, subscription_id, plan_id, days, name=None):
    """Extend existing VPN key instead of creating a new one"""
    # Get access key from database
    key = await get_access_key(key_id)
    if not key:
        logging.error(f"Key {key_id} not found for extension")
        return None
    
    # Extend key with Outline API
    outline_key = await outline_service.extend_key_expiration(key_id, days, name)
    
    if not outline_key or "error" in outline_key:
        logging.error(f"Failed to extend key {key_id}: {outline_key.get('error', 'Unknown error')}")
        return None
    
    # Calculate new expiry date
    expires_at = calculate_expiry(days)
    
    # Update key in database
    update_data = {
        "subscription_id": subscription_id,
        "updated_at": datetime.now(),
        "expires_at": expires_at
    }
    
    # Update the key and return the updated record
    await update_access_key(key_id, update_data)
    
    # Get the updated key
    updated_key = await get_access_key(key_id)
    return updated_key

async def get_user_active_keys(user_id):
    """Get all active (non-deleted) keys for a user"""
    try:
        # Get all keys for the user
        all_keys = await get_user_access_keys(user_id)
        
        # Filter out deleted keys (для SQLAlchemy используем прямой доступ к атрибуту)
        active_keys = [k for k in all_keys if not (getattr(k, 'deleted', False))]
        
        return active_keys
    except Exception as e:
        logging.error(f"Error getting user active keys: {e}")
        return []

async def check_subscription_expiry():
    """Check for expiring subscriptions and notify users"""
    # Get subscriptions expiring in 1 day
    expiring_subscriptions = await get_expiring_subscriptions(1)
    
    if not expiring_subscriptions:
        return
    
    # Process each expiring subscription
    logging.info(f"Found {len(expiring_subscriptions)} expiring subscriptions")
    # Implementation depends on notification mechanism

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    # Welcome message
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
    
    # Get active subscription
    subscription = await get_active_subscription(user.id)
    
    # Prepare keyboard based on subscription status
    keyboard = []
    
    if subscription:
        # User has active subscription
        keyboard = [
            [InlineKeyboardButton("🔑 Получить ключ", callback_data="plans")],
            [InlineKeyboardButton("📊 Статус подписки", callback_data="status")],
            [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
        ]
    else:
        # User hasn't used test period yet
        db_user = await get_user(user.id)
        test_used = False
        if db_user:
            if isinstance(db_user, dict):
                test_used = db_user.get("test_used", False)
            else:
                test_used = getattr(db_user, "test_used", False)
            
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
    
    keyboard = [
        [InlineKeyboardButton("🔑 Получить ключ", callback_data="plans")],
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
    
    # Get test plan
    test_plan = VPN_PLANS.get("test", {})
    
    # Display test plan first (if available)
    if test_plan:
        message += (
            f"*{test_plan.get('name', 'Тестовый период')}*\n"
            f"Стоимость: *Бесплатно*\n"
            f"Срок действия: {test_plan.get('duration', 3)} дня\n"
            f"Устройств: до {test_plan.get('devices', 1)}\n"
            f"Пробный доступ ко всем функциям VPN. По истечении тестового периода требуется оплата.\n\n"
        )
    
    # Add regular plans
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
    
    # Check if user already used test period
    db_user = await get_user(user.id)
    test_used = False
    if db_user:
        if isinstance(db_user, dict):
            test_used = db_user.get("test_used", False)
        else:
            test_used = getattr(db_user, "test_used", False)
            
    # Add test plan button if not used yet
    if test_plan and not test_used:
        keyboard.append([InlineKeyboardButton(
            "🔍 Попробовать бесплатно", 
            callback_data="test_period"
        )])
        
    # Add regular plans
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
    """Handler for the /keys command - redirects to plans"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    # Always redirect to plans
    message = (
        "Для получения ключа VPN выберите тарифный план:\n\n"
        "После выбора тарифа и оплаты вы получите доступ к VPN."
    )
    
    # Get test plan
    test_plan = VPN_PLANS.get("test", {})
    
    # Check if user already used test period
    db_user = await get_user(user.id)
    test_used = False
    if db_user:
        if isinstance(db_user, dict):
            test_used = db_user.get("test_used", False)
        else:
            test_used = getattr(db_user, "test_used", False)
    
    # Create keyboard with plan options
    keyboard = []
    
    # Add test plan button if not used yet
    if test_plan and not test_used:
        keyboard.append([InlineKeyboardButton(
            "🔍 Попробовать бесплатно", 
            callback_data="test_period"
        )])
        
    # Add regular plans
    regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
    for plan_id, plan in regular_plans.items():
        keyboard.append([InlineKeyboardButton(
            f"{plan['name']} - {plan['price']} руб.", 
            callback_data=f"buy_{plan_id}"
        )])
    
    keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup
    )
    return

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command"""
    user = update.effective_user
    await ensure_user_exists(user)
    
    message = (
        "*Инструкция по настройке VPN:*\n\n"
        "1. Скачайте клиент Outline:\n"
        "• Android: [Google Play](https://play.google.com/store/apps/details?id=org.outline.android.client)\n"
        "• iOS: [App Store](https://apps.apple.com/us/app/outline-app/id1356177741)\n"
        "• Windows: [outline.vpn](https://getoutline.org/get-started/#step-3)\n"
        "• macOS: [outline.vpn](https://getoutline.org/get-started/#step-3)\n"
        "• Linux: [outline.vpn](https://getoutline.org/get-started/#step-3)\n\n"
        "2. Получите ключ доступа, выбрав тарифный план.\n\n"
        "3. Скопируйте полученную ссылку и откройте ее в клиенте Outline.\n\n"
        "4. Подключитесь к VPN, нажав кнопку 'Подключиться'.\n\n"
        "*Дополнительная информация:*\n"
        "• Один ключ можно использовать на нескольких устройствах (в пределах лимита вашего тарифа).\n"
        "• При возникновении проблем напишите в поддержку.\n"
    )
    
    # Create keyboard
    keyboard = [
        [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        message,
        reply_markup=reply_markup,
        parse_mode="Markdown",
        disable_web_page_preview=True
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for button callbacks"""
    query = update.callback_query
    await query.answer()
    
    user = update.effective_user
    data = query.data
    
    # Обработка кнопки "Скопировать ключ"
    if data.startswith("copy_key_"):
        callback_id = data
        access_url = None
        
        # Получаем ключ из контекста, если он там сохранен
        if hasattr(context, 'user_data') and callback_id in context.user_data:
            access_url = context.user_data[callback_id]
        
        # Если ключ найден, отправляем его отдельным сообщением для копирования
        if access_url:
            # Подтверждаем действие кнопки
            await query.answer("Ключ готов для копирования")
            
            # Отправляем ключ в отдельном сообщении для удобного копирования
            await context.bot.send_message(
                chat_id=user.id,
                text=f"`{access_url}`",
                parse_mode="Markdown"
            )
            return
        else:
            await query.answer("Ключ не найден. Пожалуйста, получите новый ключ.")
            return
    
    # Admin panel button
    if data == "admin":
        # Check if user is admin
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
                [InlineKeyboardButton("🔑 Получить ключ", callback_data="plans")],
                [InlineKeyboardButton("📊 Статус подписки", callback_data="status")],
                [InlineKeyboardButton("📱 Как настроить", callback_data="help")]
            ]
        else:
            # User hasn't used test period yet
            db_user = await get_user(user.id)
            test_used = False
            if db_user:
                if isinstance(db_user, dict):
                    # MongoDB возвращает словарь
                    test_used = db_user.get("test_used", False)
                else:
                    # SQLAlchemy возвращает объект модели
                    test_used = getattr(db_user, "test_used", False)
            
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
        plan_id = ""
        subscription_id = ""
        
        # Обработка разных типов данных в зависимости от используемой БД
        if isinstance(subscription, dict):
            # MongoDB
            plan_id = subscription.get("plan_id", "")
            subscription_id = subscription.get("_id", "")
        else:
            # SQLAlchemy
            plan_id = getattr(subscription, "plan_id", "")
            subscription_id = getattr(subscription, "id", "")
            
        plan = VPN_PLANS.get(plan_id, {})
        
        # Get access keys for this user
        access_keys = await get_user_access_keys(user.id)
        
        # Filter keys for current subscription
        valid_keys = []
        for key in access_keys:
            key_subscription_id = ""
            if isinstance(key, dict):
                key_subscription_id = str(key.get("subscription_id", ""))
            else:
                key_subscription_id = str(getattr(key, "subscription_id", ""))
                
            if key_subscription_id == str(subscription_id):
                valid_keys.append(key)
        
        # Format expiry date
        expires_at = None
        if isinstance(subscription, dict):
            expires_at = subscription.get("expires_at")
        else:
            expires_at = getattr(subscription, "expires_at", None)
            
        expiry_str = format_expiry_date(expires_at) if expires_at else "Неизвестно"
        
        message = (
            f"*Информация о подписке:*\n\n"
            f"*План:* {plan.get('name', 'Неизвестно')}\n"
            f"*Статус:* Активна\n"
            f"*Действует до:* {expiry_str}\n"
            f"*Доступно устройств:* {plan.get('devices', 1)}\n"
            f"*Используется устройств:* {len(valid_keys)}\n\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("🔑 Получить ключ", callback_data="plans")],
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

    # Test period
    elif data == "test_period":
        # Make sure user exists in database
        db_user = await get_user(user.id)
        
        # Create user if not exists
        if not db_user:
            user_data = {
                "telegram_id": user.id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "created_at": datetime.now(),
                "test_used": False
            }
            db_user = await create_user(user_data)
        
        # Обработка результатов из разных баз данных
        test_used = False
        if db_user:
            if isinstance(db_user, dict):
                # MongoDB возвращает словарь
                test_used = db_user.get("test_used", False)
            else:
                # SQLAlchemy возвращает объект модели
                test_used = getattr(db_user, "test_used", False)
        
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
        # Получаем реальный ID пользователя из базы данных
        user_db_id = None
        if isinstance(db_user, dict):
            # MongoDB
            user_db_id = db_user.get("_id", user.id)
        else:
            # SQLAlchemy
            user_db_id = getattr(db_user, "id", None)
            
        if not user_db_id:
            await query.edit_message_text(
                "Произошла ошибка при активации тестового периода. Пожалуйста, попробуйте позже.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                ]])
            )
            return
            
        subscription_data = {
            "user_id": user_db_id,  # Используем ID из базы данных, а не из Telegram
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
        # Убедимся, что duration - это число
        duration_days = test_plan["duration"]
        if not isinstance(duration_days, int):
            duration_days = 3  # Значение по умолчанию, если не удалось получить число
            
        key = await create_vpn_access(
            user_db_id,  # Используем ID из базы данных, а не из Telegram 
            subscription_id, 
            "test", 
            duration_days, 
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
        
        # Обновляем пользователя в локальной переменной только если он существует
        if db_user:
            if isinstance(db_user, dict):
                db_user["test_used"] = True
            else:
                db_user.test_used = True
        
        # Получаем дату истечения срока действия
        expiry_date = datetime.now() + timedelta(days=test_plan["duration"])
        if isinstance(new_subscription, dict):
            expiry_date = new_subscription.get("expires_at", expiry_date)
        else:
            # SQLAlchemy объект
            expiry_date = getattr(new_subscription, "expires_at", expiry_date)
            
        # Форматируем дату для отображения
        expiry_str = format_expiry_date(expiry_date)
        
        # Форматируем URL ключа
        access_url = ""
        if isinstance(key, dict):
            access_url = key.get("access_url", "")
        else:
            access_url = getattr(key, "access_url", "")
        
        # Генерируем уникальный ID для callback копирования ключа
        copy_key_callback = f"copy_key_{uuid.uuid4().hex[:8]}"
        
        # Сохраняем URL-ключ в контексте, чтобы потом его можно было быстро отправить
        if not hasattr(context, 'user_data'):
            context.user_data = {}
        
        context.user_data[copy_key_callback] = access_url
        
        # Send success message with access key
        message = (
            f"*Тестовый период активирован!*\n\n"
            f"Вы получили бесплатный доступ к VPN на {test_plan['duration']} дня.\n\n"
            f"*Ваш ключ доступа:*\n"
            f"`{access_url}`\n\n"
            f"Используйте этот ключ для подключения к VPN через приложение Outline.\n\n"
            f"*Важно:* По истечении тестового периода ключ будет деактивирован. "
            f"Для продолжения использования необходимо приобрести один из платных тарифов.\n\n"
            f"*Срок действия:* до {expiry_str}"
        )
        
        keyboard = [
            [InlineKeyboardButton("💾 Скопировать ключ", callback_data=copy_key_callback)],
            [InlineKeyboardButton("💳 Тарифные планы", callback_data="plans")],
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
    
    # Plans callback
    elif data == "plans":
        message = "*Доступные тарифные планы:*\n\n"
        
        # Get test plan
        test_plan = VPN_PLANS.get("test", {})
        
        # Display test plan first (if available)
        if test_plan:
            message += (
                f"*{test_plan.get('name', 'Тестовый период')}*\n"
                f"Стоимость: *Бесплатно*\n"
                f"Срок действия: {test_plan.get('duration', 3)} дня\n"
                f"Устройств: до {test_plan.get('devices', 1)}\n"
                f"Пробный доступ ко всем функциям VPN. По истечении тестового периода требуется оплата.\n\n"
            )
        
        # Add regular plans in order of duration (shortest to longest)
        regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
        
        # Sort by duration
        sorted_plans = sorted(regular_plans.items(), key=lambda x: x[1]['duration'])
        
        for plan_id, plan in sorted_plans:
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
        
        # Check if user already used test period
        db_user = await get_user(user.id)
        test_used = False
        if db_user:
            if isinstance(db_user, dict):
                test_used = db_user.get("test_used", False)
            else:
                test_used = getattr(db_user, "test_used", False)
                
        # Add test plan button if not used yet
        if test_plan and not test_used:
            keyboard.append([InlineKeyboardButton(
                "🔍 Попробовать бесплатно", 
                callback_data="test_period"
            )])
            
        # Сортируем тарифы по длительности
        sorted_plans = sorted(regular_plans.items(), key=lambda x: x[1]['duration'])
        
        # Add regular plans
        for plan_id, plan in sorted_plans:
            # Добавляем информацию о скидке, если она есть
            discount_text = f" (-{plan.get('discount')})" if plan.get('discount') else ""
            keyboard.append([InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} руб.{discount_text}", 
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
