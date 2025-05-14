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
    user = await db.get_user(user_id)
    if not user:
        await db.create_user({
            "telegram_id": user_id,
            "username": username,
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "created_at": datetime.now(),
            "is_premium": False
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
    data = query.data
    if data.startswith("copy_key_"):
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
                text=f"\`{access_url}\`",
                parse_mode="Markdown"
            )
            return
        else:
            await query.answer("Ключ не найден. Пожалуйста, получите новый ключ.")
            return
    
    if data == "buy":
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
                f"{plan['name']} ({plan['duration']} дней) - {plan['price']} ₽{discount_text}",
                callback_data=f"buy_{plan_id}"
            )])
        
        # Добавляем тестовый тариф в конец списка
        if "test" in VPN_PLANS:
            test_plan = VPN_PLANS["test"]
            keyboard.append([InlineKeyboardButton(
                f"🔍 {test_plan['name']} ({test_plan['duration']} дня)",
                callback_data="buy_test"
            )])
        
        # Add back button
        keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            "💰 <b>Выберите тарифный план:</b>\n\n"
            "Выберите подходящий вам вариант для подключения к сервису VPN.\n"
            "Вы можете выбрать тариф в зависимости от срока использования и количества устройств:",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    # Status command - get user's subscription status
    elif data == "status":
        user_id = query.from_user.id
        user = await db.get_user(user_id)
        
        try:
            # Get active subscription
            active_subscription = await db.get_active_subscription(user_id)
            
            # Get user's VPN keys
            from handlers.outline_handlers import get_user_active_keys
            active_keys = await get_user_active_keys(user_id)
            
            if active_subscription:
                # User has an active subscription
                plan_id = active_subscription.plan_id
                plan = VPN_PLANS.get(plan_id, {"name": "Неизвестный", "devices": 0})
                
                # Format expiry date
                expiry_date = active_subscription.expires_at
                days_left = (expiry_date - datetime.now()).days if expiry_date else 0
                
                # Create inline keyboard with keys
                keyboard = []
                
                # Add keys
                if active_keys and len(active_keys) > 0:
                    for i, key in enumerate(active_keys):
                        key_name = key.name or f"Ключ {i+1}"
                        
                        # Save access URL in context for later retrieval
                        key_id = f"copy_key_{key.id}"
                        if not hasattr(context, 'user_data'):
                            context.user_data = {}
                        context.user_data[key_id] = key.access_url
                        
                        keyboard.append([InlineKeyboardButton(f"📋 Копировать {key_name}", callback_data=key_id)])
                
                # Add renewal option if subscription is about to expire
                if days_left <= 7:
                    keyboard.append([InlineKeyboardButton("🔄 Продлить подписку", callback_data="buy")])
                
                # Add back button
                keyboard.append([InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                status_text = (
                    "✅ <b>Статус подписки:</b>\n\n"
                    f"🔹 Тариф: <b>{plan['name']}</b>\n"
                    f"⏳ Подписка: активна\n"
                    f"📅 Дата окончания: {expiry_date.strftime('%d.%m.%Y')}\n"
                    f"⌛️ Осталось дней: {days_left}\n"
                    f"📱 Устройств: {len(active_keys)} из {plan['devices']}\n\n"
                )
                
                if active_keys and len(active_keys) > 0:
                    status_text += "🔑 <b>Ваши ключи доступа:</b>\n"
                    status_text += "Нажмите на кнопку ниже, чтобы скопировать ключ."
                else:
                    status_text += "❗️ У вас нет активных ключей. Обратитесь к администратору."
                
                await query.edit_message_text(
                    status_text,
                    reply_markup=reply_markup,
                    parse_mode="HTML"
                )
            else:
                # User has no active subscription
                keyboard = [
                    [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
                    [InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")]
                ]
                
                if "test" in VPN_PLANS and not (user and getattr(user, 'test_used', False)):
                    keyboard.insert(0, [InlineKeyboardButton("🔍 Попробовать бесплатно", callback_data="buy_test")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.edit_message_text(
                    "❌ <b>У вас нет активной подписки</b>\n\n"
                    "Для использования VPN сервиса необходимо приобрести подписку "
                    "или активировать пробный период.",
                    reply_markup=reply_markup,
                    parse_mode="HTML"
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
    
    elif data == "back_to_main":
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
            if plan_id == "test" and user and getattr(user, 'test_used', False):
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
        await query.answer("Создаём доступ...")
        
        plan_id = data.replace("pay_", "")
        user_id = query.from_user.id
        logger.info(f"🔶 PAYMENT HANDLER: Processing payment for user_id={user_id}, plan_id={plan_id}")
        
        try:
            # Получаем план
            if plan_id not in VPN_PLANS:
                raise ValueError(f"Invalid plan ID: {plan_id}")
            
            plan = VPN_PLANS[plan_id]
            logger.info(f"🔶 PAYMENT HANDLER: Selected plan: {plan['name']}, price: {plan.get('price', 0)}")
            
            # For testing, process immediately without payment
            logger.info(f"🔶 PAYMENT HANDLER: TEST MODE - creating direct access")
            
            # Get user from database or create
            logger.info(f"🔶 PAYMENT HANDLER: Getting user from database")
            user = await db.get_user(user_id)
            if not user:
                # Create user
                logger.info(f"🔶 PAYMENT HANDLER: User not found, creating new user")
                first_name = query.from_user.first_name or ""
                last_name = query.from_user.last_name or ""
                username = query.from_user.username or f"user_{user_id}"
                
                user_data = {
                    "telegram_id": user_id,
                    "username": username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "created_at": datetime.now()
                }
                user = await db.create_user(user_data)
                if not user:
                    raise ValueError(f"Failed to create user record for ID {user_id}")
                logger.info(f"🔶 PAYMENT HANDLER: User created successfully: {user.id}")
            
            # Create direct subscription
            logger.info(f"🔶 PAYMENT HANDLER: Creating subscription")
            subscription_data = {
                "subscription_id": f"direct_{str(uuid.uuid4())[:8]}",
                "user_id": user.id,  # Use internal ID
                "plan_id": plan_id,
                "status": "active",
                "created_at": datetime.now(),
                "expires_at": datetime.now() + timedelta(days=plan.get("duration", 30)),
                "price_paid": 0.0  # Free for testing
            }
            
            subscription = await db.create_subscription(subscription_data)
            if not subscription:
                raise ValueError("Failed to create subscription record")
            logger.info(f"🔶 PAYMENT HANDLER: Subscription created successfully: {subscription.id}")
            
            # Деактивировать предыдущие ключи доступа пользователя
            logger.info(f"🔶 PAYMENT HANDLER: Deactivating previous access keys for user {user.id}")
            await db.deactivate_user_access_keys(user.id)
            
            # Create VPN keys
            device_limit = plan.get('devices', 1)
            success_keys = []
            
            for i in range(device_limit):
                device_name = f"Device {i+1}" if i > 0 else "Main device"
                key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                logger.info(f"🔶 PAYMENT HANDLER: Creating key {i+1}/{device_limit}: {key_name}")
                
                # Create access key directly using internal IDs
                outline_key = await outline_service.create_key_with_expiration(
                    days=plan['duration'], 
                    name=key_name
                )
                
                if not outline_key:
                    logger.error(f"Failed to create outline key for user {user_id}")
                    continue
                
                # Save key to database
                key_data = {
                    "key_id": outline_key.get("id"),
                    "name": key_name,
                    "access_url": outline_key.get("accessUrl"),
                    "user_id": user.id,  # Use internal ID
                    "subscription_id": subscription.id,  # Use internal ID
                    "created_at": datetime.now()
                }
                
                new_key = await db.create_access_key(key_data)
                if new_key:
                    success_keys.append(new_key)
                    logger.info(f"🔶 PAYMENT HANDLER: Key created successfully: {new_key.id}")
            
            # Show result
            if success_keys:
                logger.info(f"🔶 PAYMENT HANDLER: Successfully created {len(success_keys)} keys")
                keyboard = []
                for key in success_keys:
                    keyboard.append([InlineKeyboardButton(f"🔑 Скачать ключ: {key.name}", url=key.access_url)])
                
                keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
                
                await query.edit_message_text(
                    f"✅ <b>Доступ активирован!</b>\n\n"
                    f"⏳ Срок действия: {plan['duration']} дней\n"
                    f"📱 Подключаемые устройства: {plan.get('devices', 1)}\n\n"
                    "ℹ️ <b>Как использовать:</b>\n"
                    "1. Установите приложение <a href='https://getoutline.org/get-started/'>Outline VPN</a>\n"
                    "2. Нажмите на кнопку ниже для загрузки ключа\n"
                    "3. Установите соединение в приложении\n\n"
                    "Спасибо за использование нашего сервиса!",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return
            
            # Если продолжить использовать оригинальный код, то вот так:
            # Создаем платеж в ЮKassa через обновленный сервис
            logger.info(f"🔶 PAYMENT HANDLER: Создаем платеж в ЮKassa для пользователя {user_id}, план {plan_id}")
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
                if not getattr(user, 'test_used', False) and plan_id == "test":
                    await db.update_user(user_id, {"test_used": True})
                
                # Создаем ключи доступа
                device_limit = plan.get('devices', 1)
                success_keys = []
                
                for i in range(device_limit):
                    device_name = f"Device {i+1}" if i > 0 else "Main device"
                    key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                    
                    # Получаем объект подписки, чтобы использовать его внутренний ID
                    subscription = await db.get_subscription(payment_result['subscription_id'])
                    if not subscription:
                        logger.error(f"Failed to get subscription with ID {payment_result['subscription_id']}")
                        continue

                    # Используем внутренний ID подписки (числовой)
                    db_subscription_id = subscription.id
                    
                    # Получаем объект пользователя, чтобы использовать его внутренний ID
                    db_user = await db.get_user(user_id)
                    if not db_user:
                        logger.error(f"Failed to get user with telegram_id {user_id}")
                        continue
                        
                    # Используем внутренний ID пользователя (числовой)
                    db_user_id = db_user.id
                    
                    # Создаем ключ доступа с правильными числовыми ID
                    key = await create_vpn_access(
                        user_id=db_user_id,  # Используем внутренний ID пользователя
                        subscription_id=db_subscription_id,  # Используем внутренний ID подписки
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
                    
                    # Импортируем функции для работы с VPN ключами
                    from handlers.outline_handlers import create_vpn_access, extend_vpn_access, get_user_active_keys
                    
                    # Проверяем, есть ли у пользователя активные ключи
                    active_keys = await get_user_active_keys(user_id)
                    device_limit = plan.get('devices', 1)
                    
                    # Если у пользователя уже есть активные ключи, продлеваем их
                    keys_created = 0
                    if active_keys and len(active_keys) > 0:
                        # Продлеваем существующие ключи до лимита устройств
                        keys_extended = 0
                        for key in active_keys:
                            if keys_extended >= device_limit:
                                break
                                
                            # Формируем имя для ключа
                            device_name = f"Device {keys_extended+1}" if keys_extended > 0 else "Main device"
                            key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                            
                            # Продлеваем ключ
                            updated_key = await extend_vpn_access(
                                key_id=key.key_id,
                                user_id=user_id,
                                subscription_id=subscription.subscription_id,
                                plan_id=plan_id,
                                days=plan['duration'],
                                name=key_name
                            )
                            
                            if updated_key:
                                keys_extended += 1
                                keys_created += 1
                        
                        # Если нужно больше ключей, создаем новые
                        for i in range(keys_extended, device_limit):
                            device_name = f"Device {i+1}" if i > 0 else "Main device"
                            key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                            
                            # Создаем новый ключ
                            new_key = await create_vpn_access(
                                user_id=user_id,
                                subscription_id=subscription.subscription_id,
                                plan_id=plan_id,
                                days=plan['duration'],
                                name=key_name
                            )
                            
                            if new_key:
                                keys_created += 1
                    else:
                        # У пользователя нет ключей, создаем новые
                        for i in range(device_limit):
                            device_name = f"Device {i+1}" if i > 0 else "Main device"
                            key_name = f"{user.username or f'User_{user_id}'} - {device_name}"
                            
                            # Создаем ключ доступа
                            new_key = await create_vpn_access(
                                user_id=user_id,
                                subscription_id=subscription.subscription_id,
                                plan_id=plan_id,
                                days=plan['duration'],
                                name=key_name
                            )
                            
                            if new_key:
                                keys_created += 1
                    
                    # Показываем сообщение об успехе
                    await query.edit_message_text(
                        "✅ <b>Доступ к VPN успешно активирован!</b>\n\n"
                        f"🔹 Тариф: <b>{plan['name']}</b>\n"
                        f"⏳ Срок действия: {plan['duration']} дней\n"
                        f"📱 Создано/продлено ключей: {keys_created}\n\n"
                        f"Используйте команду /status или нажмите кнопку ниже, "
                        f"чтобы получить ваши ключи доступа.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔑 Мои ключи", callback_data="status")],
                            [InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main")]
                        ]),
                        parse_mode="HTML"
                    )
                else:
                    # Не удалось обработать платеж
                    await query.edit_message_text(
                        "❓ <b>Ошибка обработки платежа</b>\n\n"
                        "Платеж получен, но возникла ошибка при активации VPN.\n"
                        "Пожалуйста, обратитесь к администратору.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                        ]]),
                        parse_mode="HTML"
                    )
            elif payment_status == "pending" or payment_status == "waiting_for_confirmation":
                # Платеж еще не подтвержден
                await query.edit_message_text(
                    "⏳ <b>Ожидание подтверждения платежа...</b>\n\n"
                    "Платеж еще обрабатывается. Это может занять несколько минут.\n\n"
                    "Если вы уже оплатили, подождите немного и проверьте снова.",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🔄 Проверить снова", callback_data=f"check_{payment_id}")],
                        [InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")]
                    ]),
                    parse_mode="HTML"
                )
            else:
                # Ошибка платежа или отмена
                await query.edit_message_text(
                    "❌ <b>Платеж не подтвержден</b>\n\n"
                    f"Статус платежа: {payment_status}\n\n"
                    "Возможно, платеж был отменен или произошла ошибка. "
                    "Попробуйте снова или выберите другой способ оплаты.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ Назад к тарифам", callback_data="buy")
                    ]]),
                    parse_mode="HTML"
                )
                
        except Exception as e:
            logger.error(f"Payment check error: {e}")
            await query.edit_message_text(
                "❌ <b>Ошибка при проверке платежа</b>\n\n"
                "Не удалось проверить статус платежа. Попробуйте позже или обратитесь к администратору.",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↩️ Назад", callback_data="back_to_main")
                ]]),
                parse_mode="HTML"
            )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /status command"""
    user_id = update.effective_user.id
    
    # Create and trigger the status button handler
    keyboard = [[InlineKeyboardButton("🔄 Мой статус", callback_data="status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "📊 Загрузка статуса...",
        reply_markup=reply_markup
    )

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /plans command"""
    # Create and trigger the buy button handler
    keyboard = [[InlineKeyboardButton("💰 Купить доступ", callback_data="buy")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        "📊 Загрузка тарифных планов...",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /help command"""
    with open('help_command.txt', 'r', encoding='utf-8') as file:
        help_text = file.read()
    
    await update.message.reply_text(
        help_text,
        parse_mode="HTML"
    )
