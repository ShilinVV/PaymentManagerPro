import os
import uuid
import logging
from datetime import datetime, timedelta
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import and_, or_

from models import get_session, User, Subscription, AccessKey, Payment

# Настройка логирования
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def init_database():
    """Initialize the database connection"""
    try:
        from models import init_db
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        return False
    return True

async def create_user(user_data):
    """Create a new user in the database"""
    session = get_session()
    try:
        # Проверяем, существует ли пользователь
        existing_user = session.query(User).filter_by(
            telegram_id=user_data["telegram_id"]
        ).first()
        
        if existing_user:
            logger.info(f"User {user_data['telegram_id']} already exists")
            return existing_user
        
        # Создаем нового пользователя
        new_user = User(
            telegram_id=user_data["telegram_id"],
            username=user_data.get("username"),
            first_name=user_data.get("first_name"),
            last_name=user_data.get("last_name"),
            created_at=user_data.get("created_at", datetime.now()),
            is_premium=user_data.get("is_premium", False),
            test_used=user_data.get("test_used", False)
        )
        
        session.add(new_user)
        session.commit()
        logger.info(f"User {user_data['telegram_id']} created successfully")
        return new_user
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error creating user: {e}")
        return None
    finally:
        session.close()

async def get_user(telegram_id):
    """Get user by Telegram ID"""
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        return user
    except SQLAlchemyError as e:
        logger.error(f"Error getting user: {e}")
        return None
    finally:
        session.close()

async def update_user(telegram_id, update_data):
    """Update user data"""
    session = get_session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            logger.error(f"User {telegram_id} not found")
            return False
        
        # Обновляем данные пользователя
        for key, value in update_data.items():
            if hasattr(user, key):
                setattr(user, key, value)
        
        session.commit()
        logger.info(f"User {telegram_id} updated successfully")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error updating user: {e}")
        return False
    finally:
        session.close()

async def get_all_users():
    """Get all users"""
    session = get_session()
    try:
        users = session.query(User).all()
        return users
    except SQLAlchemyError as e:
        logger.error(f"Error getting all users: {e}")
        return []
    finally:
        session.close()

async def deactivate_user_subscriptions(user_id):
    """Деактивировать все активные подписки пользователя"""
    session = get_session()
    try:
        # Найти все активные подписки пользователя
        subscriptions = session.query(Subscription).filter(
            and_(
                Subscription.user_id == user_id,
                Subscription.status == "active"
            )
        ).all()
        
        # Деактивировать каждую подписку
        for subscription in subscriptions:
            subscription.status = "inactive"
            logger.info(f"Deactivated subscription {subscription.subscription_id} for user {user_id}")
        
        session.commit()
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error deactivating subscriptions: {e}")
        return False
    finally:
        session.close()

async def create_subscription(subscription_data):
    """Create a new subscription in the database"""
    session = get_session()
    try:
        # Генерируем уникальный ID для подписки, если не указан
        if not subscription_data.get("subscription_id"):
            subscription_data["subscription_id"] = str(uuid.uuid4())
        
        # Находим пользователя по telegram_id, если указан
        if "user_id" not in subscription_data and "telegram_id" in subscription_data:
            user = session.query(User).filter_by(telegram_id=subscription_data["telegram_id"]).first()
            if user:
                subscription_data["user_id"] = user.id
            else:
                logger.error(f"User with telegram_id {subscription_data['telegram_id']} not found")
                return None
        
        # Деактивировать предыдущие подписки пользователя
        if subscription_data.get("status", "active") == "active":
            await deactivate_user_subscriptions(subscription_data["user_id"])
            logger.info(f"Deactivated previous subscriptions for user {subscription_data['user_id']}")
        
        # Создаем новую подписку
        new_subscription = Subscription(
            subscription_id=subscription_data["subscription_id"],
            user_id=subscription_data["user_id"],
            plan_id=subscription_data["plan_id"],
            status=subscription_data.get("status", "active"),
            created_at=subscription_data.get("created_at", datetime.now()),
            expires_at=subscription_data.get("expires_at", subscription_data.get("expiry_date")),
            price_paid=subscription_data.get("price_paid", 0.0)
        )
        
        session.add(new_subscription)
        session.commit()
        logger.info(f"Subscription {new_subscription.subscription_id} created successfully")
        return new_subscription
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error creating subscription: {e}")
        return None
    finally:
        session.close()

async def get_subscription(subscription_id):
    """Get subscription by ID"""
    session = get_session()
    try:
        subscription = session.query(Subscription).filter_by(subscription_id=subscription_id).first()
        return subscription
    except SQLAlchemyError as e:
        logger.error(f"Error getting subscription: {e}")
        return None
    finally:
        session.close()

async def update_subscription(subscription_id, update_data):
    """Update subscription data"""
    session = get_session()
    try:
        subscription = session.query(Subscription).filter_by(subscription_id=subscription_id).first()
        if not subscription:
            logger.error(f"Subscription {subscription_id} not found")
            return False
        
        # Обновляем данные подписки
        for key, value in update_data.items():
            if hasattr(subscription, key):
                setattr(subscription, key, value)
        
        session.commit()
        logger.info(f"Subscription {subscription_id} updated successfully")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error updating subscription: {e}")
        return False
    finally:
        session.close()

async def get_user_subscriptions(user_id, status=None):
    """Get all subscriptions for a user, optionally filtered by status"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если передан telegram_id вместо user_id
        if isinstance(user_id, int) and user_id > 1000000:  # Предполагаем, что это telegram_id
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user_id = user.id
            else:
                logger.error(f"User with telegram_id {user_id} not found")
                return []
        
        # Формируем запрос в зависимости от статуса
        query = session.query(Subscription).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
            
        subscriptions = query.all()
        return subscriptions
    except SQLAlchemyError as e:
        logger.error(f"Error getting user subscriptions: {e}")
        return []
    finally:
        session.close()

async def get_active_subscription(user_id):
    """Get user's active subscription"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если передан telegram_id вместо user_id
        if isinstance(user_id, int) and user_id > 1000000:  # Предполагаем, что это telegram_id
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user_id = user.id
            else:
                logger.error(f"User with telegram_id {user_id} not found")
                return None
        
        # Ищем активную подписку с неистекшим сроком
        now = datetime.now()
        subscription = session.query(Subscription).filter(
            and_(
                Subscription.user_id == user_id,
                Subscription.status == "active",
                or_(
                    Subscription.expires_at > now,
                    Subscription.expires_at == None
                )
            )
        ).order_by(Subscription.expires_at.desc()).first()
        
        return subscription
    except SQLAlchemyError as e:
        logger.error(f"Error getting active subscription: {e}")
        return None
    finally:
        session.close()

async def get_expiring_subscriptions(days=1):
    """Get subscriptions expiring in the specified number of days"""
    session = get_session()
    try:
        # Вычисляем даты для фильтрации
        now = datetime.now()
        target_date = now + timedelta(days=days)
        
        # Ищем активные подписки, истекающие в указанный период
        subscriptions = session.query(Subscription).filter(
            and_(
                Subscription.status == "active",
                Subscription.expires_at >= now,
                Subscription.expires_at <= target_date
            )
        ).all()
        
        return subscriptions
    except SQLAlchemyError as e:
        logger.error(f"Error getting expiring subscriptions: {e}")
        return []
    finally:
        session.close()

async def create_access_key(key_data):
    """Create a new access key in the database"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если указан
        if "user_id" not in key_data and "telegram_id" in key_data:
            user = session.query(User).filter_by(telegram_id=key_data["telegram_id"]).first()
            if user:
                key_data["user_id"] = user.id
            else:
                logger.error(f"User with telegram_id {key_data['telegram_id']} not found")
                return None
        
        # Создаем новый ключ доступа
        new_key = AccessKey(
            key_id=key_data["key_id"],
            name=key_data.get("name"),
            access_url=key_data["access_url"],
            user_id=key_data["user_id"],
            subscription_id=key_data["subscription_id"],
            created_at=key_data.get("created_at", datetime.now()),
            deleted=key_data.get("deleted", False)
        )
        
        session.add(new_key)
        session.commit()
        logger.info(f"Access key {new_key.key_id} created successfully")
        return new_key
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error creating access key: {e}")
        return None
    finally:
        session.close()

async def get_access_key(key_id):
    """Get access key by Outline key ID"""
    session = get_session()
    try:
        key = session.query(AccessKey).filter_by(key_id=key_id).first()
        return key
    except SQLAlchemyError as e:
        logger.error(f"Error getting access key: {e}")
        return None
    finally:
        session.close()

async def update_access_key(key_id, update_data):
    """Update access key data"""
    session = get_session()
    try:
        key = session.query(AccessKey).filter_by(key_id=key_id).first()
        if not key:
            logger.error(f"Access key {key_id} not found")
            return False
        
        # Обновляем данные ключа
        for k, value in update_data.items():
            if hasattr(key, k):
                setattr(key, k, value)
        
        session.commit()
        logger.info(f"Access key {key_id} updated successfully")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error updating access key: {e}")
        return False
    finally:
        session.close()

async def deactivate_user_access_keys(user_id):
    """Деактивировать все ключи доступа пользователя"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если передан telegram_id вместо user_id
        if isinstance(user_id, int) and user_id > 1000000:  # Предполагаем, что это telegram_id
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user_id = user.id
            else:
                logger.error(f"User with telegram_id {user_id} not found")
                return False
        
        # Получаем все неудаленные ключи доступа пользователя
        keys = session.query(AccessKey).filter(
            and_(
                AccessKey.user_id == user_id,
                AccessKey.deleted == False
            )
        ).all()
        
        # Помечаем каждый ключ как удаленный
        for key in keys:
            key.deleted = True
            logger.info(f"Deactivated access key {key.key_id} for user {user_id}")
        
        session.commit()
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error deactivating access keys: {e}")
        return False
    finally:
        session.close()

async def get_user_access_keys(user_id):
    """Get all access keys for a user"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если передан telegram_id вместо user_id
        if isinstance(user_id, int) and user_id > 1000000:  # Предполагаем, что это telegram_id
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user_id = user.id
            else:
                logger.error(f"User with telegram_id {user_id} not found")
                return []
        
        # Получаем ключи доступа пользователя, которые не удалены
        keys = session.query(AccessKey).filter(
            and_(
                AccessKey.user_id == user_id,
                AccessKey.deleted == False
            )
        ).all()
        
        return keys
    except SQLAlchemyError as e:
        logger.error(f"Error getting user access keys: {e}")
        return []
    finally:
        session.close()

async def get_subscription_access_keys(subscription_id):
    """Get all access keys for a subscription"""
    session = get_session()
    try:
        # Получаем ключи доступа для подписки, которые не удалены
        keys = session.query(AccessKey).filter(
            and_(
                AccessKey.subscription_id == subscription_id,
                AccessKey.deleted == False
            )
        ).all()
        
        return keys
    except SQLAlchemyError as e:
        logger.error(f"Error getting subscription access keys: {e}")
        return []
    finally:
        session.close()

async def create_payment(payment_data):
    """Create a new payment record in the database"""
    session = get_session()
    try:
        # Генерируем уникальный ID для платежа, если не указан
        if not payment_data.get("payment_id"):
            payment_data["payment_id"] = str(uuid.uuid4())
        
        # Находим пользователя по telegram_id, если указан
        if "user_id" not in payment_data and "telegram_id" in payment_data:
            user = session.query(User).filter_by(telegram_id=payment_data["telegram_id"]).first()
            if user:
                payment_data["user_id"] = user.id
            else:
                logger.error(f"User with telegram_id {payment_data['telegram_id']} not found")
                return None
        
        # Создаем новый платеж
        new_payment = Payment(
            payment_id=payment_data["payment_id"],
            user_id=payment_data["user_id"],
            subscription_id=payment_data.get("subscription_id"),
            amount=payment_data["amount"],
            currency=payment_data.get("currency", "RUB"),
            status=payment_data.get("status", "pending"),
            created_at=payment_data.get("created_at", datetime.now()),
            completed_at=payment_data.get("completed_at")
        )
        
        session.add(new_payment)
        session.commit()
        logger.info(f"Payment {new_payment.payment_id} created successfully")
        return new_payment
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error creating payment: {e}")
        return None
    finally:
        session.close()

async def get_payment(payment_id):
    """Get payment by payment ID"""
    session = get_session()
    try:
        payment = session.query(Payment).filter_by(payment_id=payment_id).first()
        return payment
    except SQLAlchemyError as e:
        logger.error(f"Error getting payment: {e}")
        return None
    finally:
        session.close()

async def update_payment(payment_id, update_data):
    """Update payment data"""
    session = get_session()
    try:
        payment = session.query(Payment).filter_by(payment_id=payment_id).first()
        if not payment:
            logger.error(f"Payment {payment_id} not found")
            return False
        
        # Обновляем данные платежа
        for key, value in update_data.items():
            if hasattr(payment, key):
                setattr(payment, key, value)
        
        session.commit()
        logger.info(f"Payment {payment_id} updated successfully")
        return True
    except SQLAlchemyError as e:
        session.rollback()
        logger.error(f"Error updating payment: {e}")
        return False
    finally:
        session.close()

async def get_user_payments(user_id, status=None):
    """Get all payments for a user, optionally filtered by status"""
    session = get_session()
    try:
        # Находим пользователя по telegram_id, если передан telegram_id вместо user_id
        if isinstance(user_id, int) and user_id > 1000000:  # Предполагаем, что это telegram_id
            user = session.query(User).filter_by(telegram_id=user_id).first()
            if user:
                user_id = user.id
            else:
                logger.error(f"User with telegram_id {user_id} not found")
                return []
        
        # Формируем запрос в зависимости от статуса
        query = session.query(Payment).filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
            
        payments = query.all()
        return payments
    except SQLAlchemyError as e:
        logger.error(f"Error getting user payments: {e}")
        return []
    finally:
        session.close()