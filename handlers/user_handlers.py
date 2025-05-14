import logging
import uuid
from datetime import datetime, timedelta
from time import time
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
    is_new_user = not user
    if is_new_user:
        user = await db.create_user({
            "telegram_id": user_id,
            "username": username,
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "created_at": datetime.now(),
            "is_premium": False
        })
        logger.info(f"Новый пользователь зарегистрирован: {user_id}, username: {username}")
    
    # Создаем клавиатуру с кнопками
    keyboard = [
        [
            InlineKeyboardButton("🔍 Тестовый период", callback_data="buy_test")
        ],
        [
            InlineKeyboardButton("💰 Купить доступ", callback_data="buy"), 
            InlineKeyboardButton("👤 Личный кабинет", callback_data="status")
        ],
        [
            InlineKeyboardButton("ℹ️ Информация", callback_data="info"), 
            InlineKeyboardButton("🛠 Сервис", callback_data="help")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # Формируем приветственное сообщение
    if is_new_user:
        message = (
            f"👋 Привет, {update.effective_user.first_name}!\n\n"
            f"🆔 Ваш ID: {user_id}\n\n"
            "🔐 Добро пожаловать в VPN Bot!\n"
            "Вы успешно зарегистрированы в системе.\n\n"
            "Что вы хотите сделать?"
        )
    else:
        message = (
            f"👋 С возвращением, {update.effective_user.first_name}!\n\n"
            "🔐 Добро пожаловать в VPN Bot!\n\n"
            "Что вы хотите сделать?"
        )
    
    # Устанавливаем команды бота в "бургер-меню"
    commands = [
        ("start", "Перезапустить бота"),
        ("status", "Личный кабинет"),
        ("plans", "Тарифы"),
        ("help", "Сервис")
    ]
    
    try:
        await context.bot.set_my_commands(commands)
    except Exception as e:
        logger.error(f"Ошибка при установке команд бота: {e}")
    
    # Отправляем сообщение
    await update.message.reply_text(message, reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for button callbacks"""
    query = update.callback_query
    await query.answer()
    
    # Получаем данные из кнопки
    data = query.data
    
    # Обработка тестового периода - прямой переход к активации
    if data == "buy_test":
        # Для тестового периода сразу предоставляем доступ без оплаты
        if "test" in VPN_PLANS:
            # Получаем данные из конфигурации
            plan_id = "test"
            plan = VPN_PLANS[plan_id]
            user_id = query.from_user.id
            
            # Проверяем, использовал ли пользователь тестовый период ранее
            user = await db.get_user(user_id)
            if user and user.test_used:
                await query.answer("Вы уже использовали тестовый период ранее")
                
                # Создаем клавиатуру с кнопками
                keyboard = [
                    [InlineKeyboardButton("💰 Купить платный доступ", callback_data="buy")],
                    [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                ]
                
                await query.edit_message_text(
                    "⚠️ <b>Тестовый период уже использован</b>\n\n"
                    "Вы уже активировали бесплатный тестовый период ранее.\n"
                    "Для продолжения использования сервиса VPN, пожалуйста, выберите один из платных тарифов.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
                return
            
            # Создаем подписку для тестового периода
            try:
                # Получаем данные для создания подписки
                subscription_id = f"test_{user_id}_{int(time())}"
                
                # Создаем запись о подписке
                from handlers.outline_handlers import create_vpn_access, get_user_active_keys
                
                # Создаем ключ доступа
                key = await create_vpn_access(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    plan_id=plan_id,
                    days=plan["duration"],
                    name=f"Test {plan['duration']} days"
                )
                
                # Обновляем статус пользователя - тестовый период использован
                await db.update_user(user_id, {"test_used": True})
                
                # Показываем результат
                if key:
                    # Создаем клавиатуру с кнопками для доступа к ключу
                    keyboard = [
                        [InlineKeyboardButton(f"🔑 Скачать ключ", url=key.access_url)],
                        [InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")]
                    ]
                    
                    await query.edit_message_text(
                        f"✅ <b>Тестовый доступ активирован!</b>\n\n"
                        f"⏳ Срок действия: {plan['duration']} дня\n"
                        f"📱 Подключаемые устройства: {plan.get('devices', 1)}\n\n"
                        f"ℹ️ <b>Как использовать:</b>\n"
                        f"1. Установите приложение <a href='https://getoutline.org/get-started/'>Outline VPN</a>\n"
                        f"2. Нажмите на кнопку ниже для загрузки ключа\n"
                        f"3. Установите соединение в приложении\n\n"
                        f"Ваш ключ также будет доступен в разделе <b>Личный кабинет</b>.",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML",
                        disable_web_page_preview=True
                    )
                else:
                    await query.edit_message_text(
                        "❌ Произошла ошибка при создании ключа доступа.\n"
                        "Пожалуйста, обратитесь к администратору.",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                        ]])
                    )
            except Exception as e:
                logger.error(f"Error creating test period: {e}")
                await query.edit_message_text(
                    "❌ Произошла ошибка при активации тестового периода.\n"
                    "Пожалуйста, попробуйте позже или обратитесь к администратору.",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")
                    ]])
                )
            return
    
    # Обработка кнопки "Вернуться в главное меню"
    if data == "back_to_main":
        # Создаем клавиатуру с кнопками
        keyboard = [
            [
                InlineKeyboardButton("🔍 Тестовый период", callback_data="buy_test")
            ],
            [
                InlineKeyboardButton("💰 Купить доступ", callback_data="buy"), 
                InlineKeyboardButton("👤 Личный кабинет", callback_data="status")
            ],
            [
                InlineKeyboardButton("ℹ️ Информация", callback_data="info"), 
                InlineKeyboardButton("🛠 Сервис", callback_data="help")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем сообщение
        await query.edit_message_text(
            f"👋 Здравствуйте, {query.from_user.first_name}!\n\n"
            "🔐 Добро пожаловать в VPN Bot!\n\n"
            "Что вы хотите сделать?",
            reply_markup=reply_markup
        )
        return
    
    # Обработка кнопки "Информация о тарифах"
    elif data == "info":
        # Информация о тарифах
        plans_info = ""
        for plan_id, plan in VPN_PLANS.items():
            days = plan.get("days", 0)
            price = plan.get("price", 0)
            
            if plan_id == "test":
                plans_info += f"📌 *Тестовый период*: {days} дня бесплатно\n"
            else:
                plans_info += f"📌 *{plan.get('name', 'План')}*: {days} дней за {price} ₽\n"
        
        # Создаем клавиатуру с кнопками
        keyboard = [
            [InlineKeyboardButton("🔍 Тестовый период", callback_data="buy_test")],
            [InlineKeyboardButton("💰 Купить доступ", callback_data="buy")],
            [InlineKeyboardButton("↩️ Вернуться в главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем сообщение
        await query.edit_message_text(
            "ℹ️ *Информация о тарифах*\n\n"
            f"{plans_info}\n"
            "Попробуйте бесплатно: нажмите кнопку 'Тестовый период'.\n"
            "Или выберите платный тариф через кнопку 'Купить доступ'.\n\n"
            "Наш VPN сервис предоставляет:\n"
            "✅ Стабильное соединение\n"
            "✅ Высокую скорость\n"
            "✅ Анонимность и безопасность\n"
            "✅ Поддержку всех устройств\n"
            "✅ Простую настройку",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return
        
    # Обработка кнопки "Сервис"
    elif data == "help":
        with open('help_command.txt', 'r', encoding='utf-8') as file:
            help_text = file.read()
        
        # Создаем клавиатуру с кнопками
        keyboard = [
            [InlineKeyboardButton("↩️ Вернуться в главное меню", callback_data="back_to_main")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Отправляем сообщение
        await query.edit_message_text(
            help_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        return
    
    # Обработка кнопки "Скопировать ключ"
    elif data.startswith("copy_key_"):
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
        
        # Тестовый тариф теперь выносим в главное меню, так что здесь его не показываем
        
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
    
    # Личный кабинет - получить статус подписки пользователя
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
                    f"🆔 ID пользователя: {user_id}\n"
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
                    f"🆔 ID пользователя: {user_id}\n\n"
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
            
            # Разные кнопки и тексты для тестового тарифа и платных тарифов
            if plan_id == "test":
                keyboard = [
                    [InlineKeyboardButton("🔑 Получить ключ", callback_data=f"pay_{plan_id}")],
                    [InlineKeyboardButton("↩️ Назад", callback_data="buy")]
                ]
                button_text = "Для получения тестового ключа нажмите кнопку ниже:"
                title = "📝 <b>Активация тестового периода</b>"
            else:
                keyboard = [
                    [InlineKeyboardButton("💳 Перейти к оплате", callback_data=f"pay_{plan_id}")],
                    [InlineKeyboardButton("↩️ Назад", callback_data="buy")]
                ]
                button_text = "Для оплаты нажмите кнопку ниже:"
                title = "📝 <b>Подтверждение заказа</b>"
                
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                f"{title}\n\n"
                f"🔹 Тариф: <b>{plan['name']}</b>\n"
                f"⏳ Срок действия: {plan['duration']} дней\n"
                f"📱 {devices_text}{discount_text}\n"
                f"💰 Стоимость: {plan['price']} ₽\n\n"
                f"{button_text}",
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
            
            # Проверяем, тестовый ли это платеж или бесплатный тариф
            if payment_result.get('is_test', False) or plan_id == "test" or plan.get('price', 0) <= 0:
                # Для тестового плана или бесплатного тарифа сразу создаем доступ
                from handlers.outline_handlers import create_vpn_access
                
                # Получаем данные пользователя
                user = await db.get_user(user_id)
                
                # Отмечаем, что пользователь использовал тестовый период
                if not getattr(user, 'test_used', False) and plan_id == "test":
                    await db.update_user(user_id, {"test_used": True})
                
                # Деактивировать предыдущие ключи доступа пользователя
                logger.info(f"🔶 PAYMENT HANDLER: Deactivating previous access keys for user {user.id}")
                await db.deactivate_user_access_keys(user.id)
                
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
                    # Создаем клавиатуру с кнопками для доступа к ключам
                    keyboard = []
                    for key in success_keys:
                        keyboard.append([InlineKeyboardButton(f"🔑 Скачать ключ: {key.name}", url=key.access_url)])
                    
                    keyboard.append([InlineKeyboardButton("↩️ В главное меню", callback_data="back_to_main")])
                    
                    plan_type = "Тестовый" if plan_id == "test" else "Бесплатный" if plan.get('price', 0) <= 0 else ""
                    
                    await query.edit_message_text(
                        f"✅ <b>{plan_type} доступ активирован!</b>\n\n"
                        f"⏳ Срок действия: {plan['duration']} дней\n"
                        f"📱 Подключаемые устройства: {plan.get('devices', 1)}\n\n"
                        f"ℹ️ <b>Как использовать:</b>\n"
                        f"1. Установите приложение <a href='https://getoutline.org/get-started/'>Outline VPN</a>\n"
                        f"2. Нажмите на кнопку ниже для загрузки ключа\n"
                        f"3. Установите соединение в приложении\n\n"
                        f"Спасибо за использование нашего сервиса!",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode="HTML",
                        disable_web_page_preview=True
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
                
            # Для платных тарифов показываем ссылку на оплату и информацию
            keyboard = [
                [InlineKeyboardButton("🔗 Перейти к оплате", url=payment_result['confirmation_url'])],
                [InlineKeyboardButton("↩️ Отмена", callback_data="back_to_main")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                "💳 <b>Оплата тарифа</b>\n\n"
                f"🔹 Тариф: <b>{plan['name']}</b>\n"
                f"💰 Сумма: {plan['price']} ₽\n\n"
                "1️⃣ Нажмите кнопку 'Перейти к оплате'\n"
                "2️⃣ Оплатите заказ на сайте ЮKassa\n"
                "3️⃣ После успешной оплаты вы получите уведомление\n"
                "    и ключ будет автоматически активирован\n\n"
                "ℹ️ Обработка платежа может занять несколько минут.",
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
    
    # Обработчик check_ больше не нужен, так как теперь используем автоматические вебхуки
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for the /status command"""
    user_id = update.effective_user.id
    
    # Получаем данные о пользователе
    user = await db.get_user(user_id)
    if not user:
        # Если пользователь не найден, регистрируем его
        user = await db.create_user({
            "telegram_id": user_id,
            "username": update.effective_user.username or f"user_{user_id}",
            "first_name": update.effective_user.first_name,
            "last_name": update.effective_user.last_name,
            "created_at": datetime.now(),
            "is_premium": False
        })
        logger.info(f"Пользователь зарегистрирован при запросе статуса: {user_id}")
    
    # Create and trigger the личный кабинет button handler
    keyboard = [[InlineKeyboardButton("👤 Личный кабинет", callback_data="status")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    message = await update.message.reply_text(
        f"🆔 Ваш ID: {user_id}\n\n"
        "📊 Загрузка личного кабинета...",
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
    
    # Create keyboard with return button
    keyboard = [
        [InlineKeyboardButton("↩️ Вернуться в главное меню", callback_data="back_to_main")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        help_text,
        reply_markup=reply_markup,
        parse_mode="HTML"
    )
