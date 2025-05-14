import logging
import uuid
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes

from config import VPN_PLANS, YUKASSA_SHOP_ID
from services.outline_service import OutlineService
import services.payment_service as payment_service
import services.database_service_sql as db
from utils.helpers import format_bytes, format_expiry_date, calculate_expiry

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
    
    # Обработка кнопки "Скопировать ключ"
    if query.data.startswith("copy_key_"):
        callback_id = query.data
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
                chat_id=query.from_user.id,
                text=f"`{access_url}`",
                parse_mode="Markdown"
            )
            return
        else:
            await query.answer("Ключ не найден. Пожалуйста, получите новый ключ.")
            return
    
    if query.data == "buy":
        # Show available plans
        keyboard = []
        
        # Фильтруем и сортируем планы по длительности (кроме тестового)
        regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
        sorted_plans = sorted(regular_plans.items(), key=lambda x: x[1]['duration'])
        
        # Добавляем тарифы в порядке возрастания длительности
        for plan_id, plan in sorted_plans:
            # Форматируем название с учетом скидки
            discount_text = f" (-{plan.get('discount')})" if plan.get('discount') else ""
            keyboard.append([InlineKeyboardButton(
                f"{plan['name']} - {plan['price']} ₽{discount_text}", 
                callback_data=f"buy_{plan_id}"
            )])
        
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Формируем текст с описанием тарифов из конфигурации
        plans_text = "📱 <b>Выберите тарифный план:</b>\n\n"
        
        # Добавляем описание каждого тарифа кроме тестового
        regular_plans = {k: v for k, v in VPN_PLANS.items() if k != "test"}
        for plan_id, plan in regular_plans.items():
            discount = f" (скидка {plan.get('discount')})" if plan.get('discount') else ""
            plans_text += (
                f"🔹 <b>{plan['name']}</b>{discount}: {plan['price']} ₽\n"
                f"   └ {plan['duration']} дней, до {plan.get('devices', 1)} устройств\n"
            )
        
        await query.edit_message_text(
            plans_text,
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
                
                # Создаем клавиатуру с основными кнопками
                keyboard = [
                    [InlineKeyboardButton("🔄 Обновить", callback_data="status")],
                    [InlineKeyboardButton("💰 Продлить доступ", callback_data="buy")]
                ]
                
                # Add config links if there are any keys
                if access_keys:
                    message_text += "🔐 <b>Ваши ключи доступа:</b>\n\n"
                    
                    # Сохраняем ключи в контексте для возможности копирования
                    if not hasattr(context, 'user_data'):
                        context.user_data = {}
                        
                    for i, key in enumerate(access_keys[:2], 1):  # Limit to 2 keys to avoid message too long
                        key_name = key.get("name", f"Ключ {i}")
                        access_url = key.get('access_url')
                        message_text += f"{i}. <b>{key_name}</b>:\n"
                        message_text += f"<code>{access_url}</code>\n\n"
                        
                        # Создаем уникальный идентификатор для коллбэка копирования
                        copy_key_callback = f"copy_key_{uuid.uuid4().hex[:8]}"
                        context.user_data[copy_key_callback] = access_url
                        
                        # Добавляем кнопку копирования для каждого ключа
                        keyboard.append([
                            InlineKeyboardButton(f"💾 Скопировать ключ {i}", callback_data=copy_key_callback)
                        ])
                
                # Добавляем кнопку возврата в главное меню
                keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")])
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
            
            # Get user from database
            user_id = query.from_user.id
            user = await db.get_user(user_id)
            
            # Check if user has already used test plan
            if plan_id == "test" and user and user.test_used:
                await query.edit_message_text(
                    "⚠️ Вы уже использовали тестовый период.\n\n"
                    "Пожалуйста, выберите другой тарифный план:",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Назад к тарифам", callback_data="buy")
                    ]])
                )
                return
            
            # Show confirmation before payment
            devices_text = f"Подключение до {plan.get('devices', 1)} устройств"
            discount_text = f", скидка {plan.get('discount')}" if plan.get('discount') else ""
            
            keyboard = [
                [InlineKeyboardButton("💳 Перейти к оплате", callback_data=f"pay_{plan_id}")],
                [InlineKeyboardButton("↩️ Назад", callback_data="buy")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"📝 <b>Подтверждение заказа</b>\n\n"
                f"🔹 Тариф: <b>{plan['name']}</b>\n"
                f"⏳ Срок действия: {plan['duration']} дней\n"
                f"📱 {devices_text}{discount_text}\n"
                f"💰 Стоимость: {plan['price']} ₽\n\n"
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
    
    data = query.data
    if data.startswith("pay_"):
        # Отображаем индикатор загрузки
        await query.answer("Создаём платёж...")
        
        plan_id = data.replace("pay_", "")
        user_id = query.from_user.id
        
        try:
            # Получаем план
            if plan_id not in VPN_PLANS:
                raise ValueError(f"Invalid plan ID: {plan_id}")
            
            plan = VPN_PLANS[plan_id]
            
            # Создаем платеж в ЮKassa через обновленный сервис
            payment_result = await payment_service.create_payment(
                user_id=user_id,
                plan_id=plan_id,
                return_url="https://t.me/vpn_outline_manager_bot"
            )
            
            # Сохраняем ID платежа и подписки в контексте для проверки
            if not hasattr(context, 'user_data'):
                context.user_data = {}
            
            context.user_data['current_payment'] = {
                'payment_id': payment_result['id'],
                'subscription_id': payment_result.get('subscription_id'),
                'plan_id': plan_id
            }
            
            # Проверяем, тестовый ли это платеж
            if payment_result.get('is_test', False) or plan_id == "test":
                # Для тестового плана сразу создаем доступ
                from handlers.outline_handlers import create_vpn_access
                
                # Получаем данные пользователя
                user = await db.get_user(user_id)
                
                # Отмечаем, что пользователь использовал тестовый период
                if not user.test_used and plan_id == "test":
                    await db.update_user(user_id, {"test_used": True})
                
                # Создаем ключи доступа
                device_limit = plan.get('devices', 1)
                success_keys = []
                
                for i in range(device_limit):
                    device_name = f"Device {i+1}" if i > 0 else "Main device"
                    key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                    
                    # Создаем ключ доступа
                    key = await create_vpn_access(
                        user_id=user_id,
                        subscription_id=payment_result['subscription_id'],
                        plan_id=plan_id,
                        days=plan['duration'],
                        name=key_name
                    )
                    
                    if key:
                        success_keys.append(key)
                
                # Показываем результат
                if success_keys:
                    await query.edit_message_text(
                        f"✅ <b>Тестовый доступ активирован!</b>\n\n"
                        f"⏳ Срок действия: {plan['duration']} дней\n"
                        f"📱 Создано ключей: {len(success_keys)}\n\n"
                        f"Используйте команду /status, чтобы получить ваши ключи доступа.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🔑 Посмотреть мои ключи", callback_data="status")
                        ]]),
                        parse_mode="HTML"
                    )
                else:
                    await query.edit_message_text(
                        "❌ Произошла ошибка при создании ключей доступа.\n"
                        "Пожалуйста, обратитесь к администратору.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                        ]])
                    )
                return
                
            # Для обычных платежей показываем ссылку на оплату
            keyboard = [
                [InlineKeyboardButton("🔗 Перейти к оплате", url=payment_result['confirmation_url'])],
                [InlineKeyboardButton("✅ Я оплатил", callback_data=f"check_{payment_result['id']}")],
                [InlineKeyboardButton("↩️ Отмена", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "💳 <b>Оплата тарифа</b>\n\n"
                f"🔹 Тариф: <b>{plan['name']}</b>\n"
                f"💰 Сумма: {plan['price']} ₽\n\n"
                "1️⃣ Нажмите кнопку 'Перейти к оплате'\n"
                "2️⃣ Оплатите заказ на сайте ЮKassa\n"
                "3️⃣ После оплаты нажмите 'Я оплатил'",
                reply_markup=reply_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Payment creation error: {e}")
            await query.edit_message_text(
                "❌ Произошла ошибка при создании платежа.\n"
                "Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                ]])
            )
    
    elif data.startswith("check_"):
        payment_id = data.replace("check_", "")
        
        try:
            # Отображаем индикатор загрузки
            await query.answer("Проверяем статус платежа...")
            
            # Проверяем статус платежа
            payment_status = await payment_service.check_payment_status(payment_id)
            
            if payment_status == "succeeded" or payment_status == "waiting_for_capture":
                # Обрабатываем успешный платеж
                payment_result = await payment_service.process_payment(payment_id)
                
                if payment_result:
                    # Получаем данные пользователя и платежа
                    user_id = query.from_user.id
                    user = await db.get_user(user_id)
                    payment = await db.get_payment(payment_id)
                    
                    if not payment:
                        raise ValueError(f"Payment {payment_id} not found")
                    
                    # Получаем план и подписку
                    subscription = await db.get_subscription(payment.subscription_id)
                    if not subscription:
                        raise ValueError(f"Subscription {payment.subscription_id} not found")
                        
                    plan_id = subscription.plan_id
                    plan = VPN_PLANS.get(plan_id)
                    if not plan:
                        raise ValueError(f"Plan {plan_id} not found")
                
                # Create subscription in database
                from datetime import datetime, timedelta
                from utils.helpers import calculate_expiry
                from handlers.outline_handlers import create_vpn_access, extend_vpn_access, get_user_active_keys
                
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
                
                # Check if user has active keys we can extend
                active_keys = await get_user_active_keys(user_id)
                device_limit = plan.get('devices', 1)
                
                # If user has existing keys from test period, extend them instead of creating new ones
                if active_keys and len(active_keys) > 0:
                    # Extend existing keys up to the device limit
                    keys_extended = 0
                    for key in active_keys:
                        if keys_extended >= device_limit:
                            break
                            
                        # Get base name for the key
                        device_name = f"Device {keys_extended+1}" if keys_extended > 0 else "Main device"
                        key_name = f"{user.get('username', f'User_{user_id}')} - {device_name}"
                        
                        # Extend this key
                        updated_key = await extend_vpn_access(
                            key_id=key.get("key_id"),
                            user_id=user_id,
                            subscription_id=str(subscription_id),
                            plan_id=plan_id,
                            days=plan['duration'],
                            name=key_name
                        )
                        
                        if updated_key:
                            keys_extended += 1
                    
                    # If we need more keys than we extended, create new ones
                    for i in range(keys_extended, device_limit):
                        device_name = f"Device {i+1}" if i > 0 else "Main device"
                        key_name = f"{user.get('username', f'User_{user_id}')} - {device_name}"
                        
                        # Create new key
                        await create_vpn_access(
                            user_id=user_id,
                            subscription_id=str(subscription_id),
                            plan_id=plan_id,
                            days=plan['duration'],
                            name=key_name
                        )
                
                else:
                    # User has no existing keys, create new ones
                    for i in range(device_limit):
                        device_name = f"Device {i+1}" if i > 0 else "Main device"
                        key_name = f"{user.get('username', f'User_{user_id}')} - {device_name}"
                        
                        # Create new key
                        await create_vpn_access(
                            user_id=user_id,
                            subscription_id=str(subscription_id),
                            plan_id=plan_id,
                            days=plan['duration'],
                            name=key_name
                        )
                
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
        
        # Создаем клавиатуру с кнопкой продления и кнопками копирования ключей
        keyboard = [
            [InlineKeyboardButton("💰 Продлить доступ", callback_data="buy")]
        ]
        
        # Добавим ссылки на конфигурацию и кнопки для копирования
        if key_urls:
            message += "<b>Ваши ключи доступа:</b>\n"
            
            # Сохраняем ключи в контексте для возможности копирования
            if not hasattr(context, 'user_data'):
                context.user_data = {}
                
            for i, url in enumerate(key_urls, 1):
                message += f"{i}. <code>{url}</code>\n"
                
                # Создаем уникальный идентификатор для коллбэка копирования
                copy_key_callback = f"copy_key_{uuid.uuid4().hex[:8]}"
                context.user_data[copy_key_callback] = url
                
                # Добавляем кнопку копирования для каждого ключа
                keyboard.append([
                    InlineKeyboardButton(f"💾 Скопировать ключ {i}", callback_data=copy_key_callback)
                ])
        else:
            message += "У вас пока нет ключей доступа. Используйте /keys для их создания."
            
        # Обновляем клавиатуру с новыми кнопками
        reply_markup = InlineKeyboardMarkup(keyboard)
            
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
