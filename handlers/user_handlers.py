import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from bson import ObjectId

from config import VPN_PLANS, YUKASSA_SHOP_ID
from services.outline_service import OutlineService
from services.payment_service import create_payment, check_payment
from services.database_service import (
    get_user,
    create_user,
    update_user,
    create_subscription,
    update_subscription,
    get_user_subscriptions,
    get_active_subscription,
    get_user_access_keys,
    create_access_key,
    get_access_key
)
from utils.helpers import format_bytes, format_expiry_date

logger = logging.getLogger(__name__)
outline_service = OutlineService()

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /start command"""
    user_id = update.effective_user.id
    username = update.effective_user.username or f"user_{user_id}"
    
    # Check if user exists in database, if not, create them
    user = await get_user(user_id)
    if not user:
        await create_user({
            "telegram_id": user_id,
            "username": username,
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "created_at": datetime.now(),
            "is_admin": False
        })
    
    keyboard = [
        [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
        [InlineKeyboardButton("🔄 Мой статус", callback_data="status")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"👋 Привет, {update.effective_user.first_name}!\n\n"
        "🔐 Добро пожаловать в VPN Bot!\n\n"
        "Выберите действие из меню ниже:",
        reply_markup=reply_markup
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "buy":
        # Show available plans
        keyboard = []
        for plan_id, plan in VPN_PLANS.items():
            keyboard.append([InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} ₽", 
                callback_data=f"buy_{plan_id}"
            )])
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "📱 Выберите тарифный план:\n\n"
            "🔹 <b>Базовый</b>: 10 ГБ на 30 дней - 299 ₽\n"
            "🔹 <b>Стандартный</b>: 50 ГБ на 30 дней - 599 ₽\n"
            "🔹 <b>Премиум</b>: 100 ГБ на 30 дней - 999 ₽",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        
    elif query.data == "status":
        user_id = query.from_user.id
        user = await get_user(user_id)
        
        # Проверяем, есть ли активная подписка у пользователя
        active_subscription = await get_active_subscription(user_id)
        if not user or not active_subscription:
            keyboard = [
                [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
                [InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "❌ У вас нет активного аккаунта VPN.\n\n"
                "Нажмите 'Купить доступ', чтобы приобрести подписку.",
                reply_markup=reply_markup
            )
            return
        
        try:
            # Get user's active subscription
            active_subscription = await get_active_subscription(user_id)
            
            if active_subscription:
                # Get subscription plan
                plan_id = active_subscription.get("plan_id", "unknown")
                plan = VPN_PLANS.get(plan_id, {})
                
                # Format expiry date
                expiry_timestamp = active_subscription.get("expires_at", 0)
                expiry = format_expiry_date(expiry_timestamp)
                
                # Get access keys
                access_keys = await get_user_access_keys(user_id)
                
                # Get all keys from Outline API to get usage data
                outline_keys = await outline_service.get_keys()
                
                # Calculate traffic usage
                total_traffic = 0
                for key in access_keys:
                    key_id = key.get("key_id")
                    # Check if key exists in outline_keys (metrics data)
                    for outline_key in outline_keys.get("keys", []):
                        if str(outline_key.get("id")) == str(key_id):
                            # Add usage data
                            total_traffic += outline_key.get("metrics", {}).get("bytesTransferred", 0)
                
                # Format used data
                used = format_bytes(total_traffic)
                
                # Get user status
                status = "✅ Активна" if active_subscription.get("status") == "active" else "❌ Неактивна"
                
                message_text = f"📊 <b>Статус вашей подписки:</b>\n\n"
                message_text += f"🔑 План: {plan.get('name', 'Стандартный')}\n"
                message_text += f"🔋 Статус: {status}\n"
                message_text += f"📈 Использовано трафика: {used}\n"
                message_text += f"⏳ Действует до: {expiry}\n\n"
                
                # Add config links if there are any keys
                if access_keys:
                    message_text += "🔐 <b>Ваши ключи доступа:</b>\n\n"
                    for i, key in enumerate(access_keys[:2], 1):  # Limit to 2 keys to avoid message too long
                        key_name = key.get("name", f"Ключ {i}")
                        message_text += f"{i}. <b>{key_name}</b>:\n"
                        message_text += f"<code>{key.get('access_url')}</code>\n\n"
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Обновить", callback_data="status")],
                    [InlineKeyboardButton("💰 Продлить доступ", callback_data="buy")],
                    [InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    message_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                await query.edit_message_text(
                    "❌ Не удалось получить информацию о вашем аккаунте.\n"
                    "Попробуйте позже или обратитесь к администратору.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                    ]])
                )
        except Exception as e:
            logger.error(f"Error getting user status: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при получении статуса.\n"
                "Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                ]])
            )
    
    elif query.data == "back_to_main":
        keyboard = [
            [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
            [InlineKeyboardButton("🔄 Мой статус", callback_data="status")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "🔑 VPN Bot Меню:",
            reply_markup=reply_markup
        )

async def buy_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for buy plan buttons"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("buy_"):
        plan_id = data.replace("buy_", "")
        
        if plan_id in VPN_PLANS:
            plan = VPN_PLANS[plan_id]
            
            # Create order in database
            user_id = query.from_user.id
            order_id = await create_order({
                "telegram_id": user_id,
                "plan_id": plan_id,
                "amount": plan["price"],
                "status": "pending",
                "created_at": datetime.now()
            })
            
            keyboard = [
                [InlineKeyboardButton("💳 Оплатить", callback_data=f"pay_{order_id}")],
                [InlineKeyboardButton("↩️ Назад", callback_data="buy")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📝 <b>Заказ создан</b>\n\n"
                f"🔹 Тариф: <b>{plan['name']}</b>\n"
                f"💾 Трафик: {format_bytes(plan['data_limit'])}\n"
                f"⏳ Срок действия: {plan['duration']} дней\n"
                f"💰 Сумма: {plan['price']} ₽\n\n"
                f"Для оплаты нажмите кнопку ниже:",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await query.edit_message_text(
                "❌ Выбран неверный тарифный план. Попробуйте еще раз.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="buy")
                ]])
            )

async def payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for payment button"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("pay_"):
        order_id = data.replace("pay_", "")
        user_id = query.from_user.id
        
        try:
            # Start the payment process with ЮKassa
            payment_url = await create_payment(order_id, str(user_id))
            
            keyboard = [
                [InlineKeyboardButton("🔗 Перейти к оплате", url=payment_url)],
                [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_{order_id}")],
                [InlineKeyboardButton("↩️ Отмена", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "💳 Для оплаты перейдите по ссылке ниже.\n\n"
                "После успешной оплаты нажмите 'Я оплатил'.",
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Payment error: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при создании платежа.\n"
                "Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                ]])
            )
    
    elif data.startswith("check_"):
        order_id = data.replace("check_", "")
        
        try:
            # Check payment status
            is_paid = await check_payment(order_id)
            
            if is_paid:
                # Process the order
                user_id = query.from_user.id
                user = await get_user(user_id)
                
                # Get order details
                from services.database_service import get_order
                order = await get_order(ObjectId(order_id))
                plan_id = order.get("plan_id")
                plan = VPN_PLANS[plan_id]
                
                # Create subscription in database
                from datetime import datetime, timedelta
                from utils.helpers import calculate_expiry
                
                # Set subscription period
                expires_at = calculate_expiry(plan['duration'])
                
                # Create or update subscription
                subscription_data = {
                    "user_id": user_id,
                    "plan_id": plan_id,
                    "status": "active",
                    "created_at": datetime.now(),
                    "expires_at": expires_at,
                    "order_id": order_id
                }
                
                subscription_id = await create_subscription(subscription_data)
                
                # Create VPN access key in Outline
                device_limit = plan.get('devices', 1)
                
                # Create keys for the user
                for i in range(device_limit):
                    device_name = f"Device {i+1}" if i > 0 else "Main device"
                    key_name = f"{user.get('username', f'User_{user_id}')} - {device_name}"
                    
                    # Create key in Outline
                    key_data = await outline_service.create_key_with_expiration(
                        days=plan['duration'],
                        name=key_name
                    )
                    
                    if key_data:
                        # Save key to database
                        key_db = {
                            "user_id": user_id,
                            "subscription_id": str(subscription_id),
                            "key_id": key_data.get("id"),
                            "name": key_name,
                            "access_url": key_data.get("accessUrl"),
                            "created_at": datetime.now(),
                            "expires_at": expires_at
                        }
                        await create_access_key(key_db)
                    
                    # Update user in database with subscription status
                    await update_user(user_id, {"has_active_subscription": True})
                
                # Update order status
                await update_order(ObjectId(order_id), {
                    "status": "completed",
                    "completed_at": datetime.now()
                })
                
                keyboard = [
                    [InlineKeyboardButton("🔄 Мой статус", callback_data="status")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "✅ <b>Оплата успешно завершена!</b>\n\n"
                    f"🔹 Тариф: <b>{plan['name']}</b>\n"
                    f"💾 Трафик: {format_bytes(plan['data_limit'])}\n"
                    f"⏳ Срок действия: {plan['duration']} дней\n\n"
                    f"👤 Telegram ID: <code>{user_id}</code>\n\n"
                    f"Для получения ваших ключей доступа, используйте команду /keys",
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                keyboard = [
                    [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"check_{order_id}")],
                    [InlineKeyboardButton("↩️ Отмена", callback_data="back_to_main")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "⏳ Оплата еще не поступила.\n\n"
                    "Если вы уже произвели оплату, подождите немного и нажмите 'Проверить снова'.",
                    reply_markup=reply_markup
                )
        except Exception as e:
            logger.error(f"Payment check error: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при проверке платежа.\n"
                "Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                ]])
            )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /status command"""
    user_id = update.effective_user.id
    user = await get_user(user_id)
    
    # Check if user has active subscription
    active_subscription = await get_active_subscription(user_id)
    if not active_subscription:
        keyboard = [
            [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ У вас нет активной подписки VPN.\n\n"
            "Нажмите 'Купить доступ', чтобы приобрести подписку.",
            reply_markup=reply_markup
        )
        return
    
    try:
        # Get subscription info and access keys
        access_keys = await get_user_access_keys(user_id)
        
        # Get all keys from Outline API for usage info
        outline_keys = await outline_service.get_keys()
        
        # Calculate total traffic
        total_traffic = 0
        for key in access_keys:
            key_id = key.get("key_id")
            # Check if key exists in outline_keys (metrics data)
            for outline_key in outline_keys.get("keys", []):
                if str(outline_key.get("id")) == str(key_id):
                    # Add usage data
                    total_traffic += outline_key.get("metrics", {}).get("bytesTransferred", 0)
        
        # Get subscription plan info
        plan_id = active_subscription.get("plan_id", "unknown")
        plan = VPN_PLANS.get(plan_id, {})
        
        # Format used data
        used = format_bytes(total_traffic)
        
        # Format expiration date
        expiry = format_expiry_date(active_subscription.get("expires_at", 0))
        
        # Get subscription status
        status = "✅ Активна" if active_subscription.get("status") == "active" else "❌ Неактивна"
        
        keyboard = [
            [InlineKeyboardButton("💰 Продлить доступ", callback_data="buy")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Получаем количество активных ключей и максимальное количество устройств
        active_keys_count = len(access_keys)
        max_devices = plan.get("devices", 1)
        
        # Получим ссылки на конфигурацию
        key_urls = []
        for key in access_keys:
            if "access_url" in key:
                key_urls.append(key.get("access_url"))
        
        message = f"📊 <b>Статус вашей подписки:</b>\n\n" \
                 f"🚀 План: {plan.get('name', 'Стандартный')}\n" \
                 f"🔋 Статус: {status}\n" \
                 f"📈 Трафик: {used}\n" \
                 f"📱 Устройства: {active_keys_count} из {max_devices}\n" \
                 f"⏳ Действует до: {expiry}\n\n"
        
        # Добавим ссылки на конфигурацию
        if key_urls:
            message += "<b>Ваши ключи доступа:</b>\n"
            for i, url in enumerate(key_urls, 1):
                message += f"{i}. <code>{url}</code>\n"
        else:
            message += "У вас пока нет ключей доступа. Используйте /keys для их создания."
            
        await update.message.reply_text(
            message,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Error getting subscription status: {e}")
        await update.message.reply_text(
            "❌ Произошла ошибка при получении статуса.\n"
            "Попробуйте позже или обратитесь к администратору."
        )

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /plans command"""
    keyboard = []
    for plan_id, plan in VPN_PLANS.items():
        keyboard.append([InlineKeyboardButton(
            f"{plan['name']} - {plan['price']} ₽", 
            callback_data=f"buy_{plan_id}"
        )])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "📱 <b>Доступные тарифные планы:</b>\n\n"
        "🔹 <b>Базовый</b>: 10 ГБ на 30 дней - 299 ₽\n"
        "🔹 <b>Стандартный</b>: 50 ГБ на 30 дней - 599 ₽\n"
        "🔹 <b>Премиум</b>: 100 ГБ на 30 дней - 999 ₽\n\n"
        "Выберите тарифный план из списка ниже:",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def pre_checkout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for pre-checkout queries"""
    query = update.pre_checkout_query
    
    # This is only used with native Telegram payments, which we're not using
    # But keeping it here for future reference
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for successful payments"""
    # This is only used with native Telegram payments, which we're not using
    # But keeping it here for future reference
    payment_info = update.message.successful_payment
    
    await update.message.reply_text(
        "✅ Спасибо за оплату! Ваш аккаунт активирован."
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command"""
    await update.message.reply_text(
        "🔍 <b>Справка по командам:</b>\n\n"
        "/start - Начать работу с ботом\n"
        "/status - Проверить статус вашего аккаунта\n"
        "/plans - Посмотреть доступные тарифные планы\n"
        "/help - Показать эту справку\n\n"
        "По всем вопросам обращайтесь к администратору.",
        parse_mode="HTML"
    )
