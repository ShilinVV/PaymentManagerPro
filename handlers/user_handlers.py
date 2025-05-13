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
        
        if not user or not user.get("marzban_username"):
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
                
                marzban_username = user.get("marzban_username")
                
                # Check if user already has an account in Marzban
                if marzban_username:
                    # Update existing user
                    await marzban_service.update_user(
                        marzban_username,
                        data_limit=plan['data_limit'],
                        days=plan['duration']
                    )
                else:
                    # Create new user in Marzban
                    marzban_username = f"tg_{user_id}"
                    await marzban_service.create_user(
                        marzban_username,
                        data_limit=plan['data_limit'],
                        days=plan['duration']
                    )
                    
                    # Update user in database with Marzban username
                    await update_user(user_id, {"marzban_username": marzban_username})
                
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
                    f"👤 Логин: <code>{marzban_username}</code>\n\n"
                    f"Для получения конфигурации, обратитесь к администратору.",
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
    
    if not user or not user.get("marzban_username"):
        keyboard = [
            [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "❌ У вас нет активного аккаунта VPN.\n\n"
            "Нажмите 'Купить доступ', чтобы приобрести подписку.",
            reply_markup=reply_markup
        )
        return
    
    try:
        # Get user account info from Marzban
        marzban_username = user.get("marzban_username")
        user_info = await marzban_service.get_user(marzban_username)
        
        if user_info:
            # Format used data
            used = format_bytes(user_info.get("used_traffic", 0))
            data_limit = format_bytes(user_info.get("data_limit", 0))
            
            # Format expiration date
            expiry = format_expiry_date(user_info.get("expire", 0))
            
            # Get user status
            status = "✅ Активен" if user_info.get("status") == "active" else "❌ Неактивен"
            
            keyboard = [
                [InlineKeyboardButton("💰 Продлить доступ", callback_data="buy")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await update.message.reply_text(
                f"📊 <b>Статус вашего аккаунта:</b>\n\n"
                f"👤 Логин: <code>{marzban_username}</code>\n"
                f"🔋 Статус: {status}\n"
                f"📈 Трафик: {used} из {data_limit}\n"
                f"⏳ Действует до: {expiry}\n\n"
                f"Для получения конфигурации, обратитесь к администратору.",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "❌ Не удалось получить информацию о вашем аккаунте.\n"
                "Попробуйте позже или обратитесь к администратору."
            )
    except Exception as e:
        logger.error(f"Error getting user status: {e}")
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
