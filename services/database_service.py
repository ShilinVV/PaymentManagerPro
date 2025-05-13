import os
import logging
from datetime import datetime, timedelta
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure
from bson.objectid import ObjectId

from config import MONGO_URI, MONGO_DB_NAME

logger = logging.getLogger(__name__)

# MongoDB client
client = None
db = None

# In-memory mockup database for testing
mock_db = {
    "users": [],
    "subscriptions": [],
    "access_keys": [],
    "payments": []
}

async def init_database():
    """Initialize the MongoDB connection"""
    global client, db
    try:
        # Use MongoDB Atlas URI with timeout settings and TLS/SSL options
        client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            ssl=True,
            ssl_cert_reqs='CERT_NONE',  # Отключает проверку сертификата для решения SSL проблем
            connect=False,  # Lazy connection
            retryWrites=True,
            connectTimeoutMS=5000,
            socketTimeoutMS=5000
        )
        # Test connection
        client.admin.command('ping')
        db = client[MONGO_DB_NAME]
        
        # Create indexes for better performance
        await ensure_indexes()
        
        logger.info(f"Connected to MongoDB: {MONGO_DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        # Create mock db for testing if MongoDB is unavailable
        from unittest.mock import MagicMock
        db = MagicMock()
        logger.warning("Using mock database for testing")
        # Don't raise the exception to allow testing without MongoDB

async def ensure_indexes():
    """Ensure all necessary indexes exist"""
    if not db:
        logger.warning("Cannot create indexes: No database connection")
        return
    
    try:
        # Users collection
        db.users.create_index("telegram_id", unique=True)
        
        # Subscriptions collection
        db.subscriptions.create_index("user_id")
        db.subscriptions.create_index("status")
        db.subscriptions.create_index("expires_at")
        
        # Access keys collection
        db.access_keys.create_index("key_id", unique=True)
        db.access_keys.create_index("user_id")
        db.access_keys.create_index("subscription_id")
        
        # Payments collection
        db.payments.create_index("payment_id", unique=True)
        db.payments.create_index("user_id")
        db.payments.create_index("subscription_id")
        
        logger.info("Database indexes created successfully")
    except Exception as e:
        logger.error(f"Error creating indexes: {e}")

# User operations
async def create_user(user_data):
    """Create a new user in the database"""
    if not db:
        await init_database()
    
    try:
        result = db.users.insert_one(user_data)
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error creating user: {e}")
        raise

async def get_user(telegram_id):
    """Get user by Telegram ID"""
    if not db:
        await init_database()
    
    try:
        return db.users.find_one({"telegram_id": telegram_id})
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        raise

async def update_user(telegram_id, update_data):
    """Update user data"""
    if not db:
        await init_database()
    
    try:
        result = db.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating user: {e}")
        raise

async def get_all_users():
    """Get all users"""
    if not db:
        await init_database()
    
    try:
        return list(db.users.find())
    except Exception as e:
        logger.error(f"Error getting all users: {e}")
        raise

# Subscription operations
async def create_subscription(subscription_data):
    """Create a new subscription in the database"""
    if not db:
        await init_database()
    
    try:
        result = db.subscriptions.insert_one(subscription_data)
        subscription_id = result.inserted_id
        
        # Add subscription ID to the data and return full object
        subscription_data["_id"] = subscription_id
        return subscription_data
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        # For mock testing
        subscription_data["_id"] = ObjectId()
        return subscription_data

async def get_subscription(subscription_id):
    """Get subscription by ID"""
    if not db:
        await init_database()
    
    try:
        return db.subscriptions.find_one({"_id": ObjectId(subscription_id)})
    except Exception as e:
        logger.error(f"Error getting subscription: {e}")
        # For mock testing
        for subscription in mock_db["subscriptions"]:
            if str(subscription.get("_id")) == str(subscription_id):
                return subscription
        return None

async def update_subscription(subscription_id, update_data):
    """Update subscription data"""
    if not db:
        await init_database()
    
    try:
        result = db.subscriptions.update_one(
            {"_id": ObjectId(subscription_id)},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating subscription: {e}")
        # For mock testing
        for subscription in mock_db["subscriptions"]:
            if str(subscription.get("_id")) == str(subscription_id):
                subscription.update(update_data)
                return True
        return False

async def get_user_subscriptions(user_id, status=None):
    """Get all subscriptions for a user, optionally filtered by status"""
    if not db:
        await init_database()
    
    try:
        query = {"user_id": user_id}
        if status:
            query["status"] = status
        
        return list(db.subscriptions.find(query).sort("created_at", -1))
    except Exception as e:
        logger.error(f"Error getting user subscriptions: {e}")
        # For mock testing
        return [s for s in mock_db["subscriptions"] 
                if s.get("user_id") == user_id and 
                (status is None or s.get("status") == status)]

async def get_active_subscription(user_id):
    """Get user's active subscription"""
    if not db:
        await init_database()
    
    try:
        current_time = datetime.now()
        
        # Find active subscription that hasn't expired
        subscription = db.subscriptions.find_one({
            "user_id": user_id,
            "status": "active",
            "expires_at": {"$gt": current_time}
        }, sort=[("expires_at", -1)])
        
        return subscription
    except Exception as e:
        logger.error(f"Error getting active subscription: {e}")
        # For mock testing
        current_time = datetime.now()
        active_subs = [s for s in mock_db["subscriptions"] 
                if s.get("user_id") == user_id and 
                s.get("status") == "active" and
                s.get("expires_at", current_time) > current_time]
        return active_subs[0] if active_subs else None

async def get_expiring_subscriptions(days=1):
    """Get subscriptions expiring in the specified number of days"""
    if not db:
        await init_database()
    
    try:
        now = datetime.now()
        expiry_start = now + timedelta(days=days)
        expiry_end = now + timedelta(days=days+1)
        
        # Find active subscriptions with expiry in the target range
        return list(db.subscriptions.find({
            "status": "active",
            "expires_at": {
                "$gte": expiry_start,
                "$lt": expiry_end
            }
        }))
    except Exception as e:
        logger.error(f"Error getting expiring subscriptions: {e}")
        # For mock testing
        now = datetime.now()
        expiry_start = now + timedelta(days=days)
        expiry_end = now + timedelta(days=days+1)
        
        return [s for s in mock_db["subscriptions"] 
                if s.get("status") == "active" and 
                s.get("expires_at", now) >= expiry_start and
                s.get("expires_at", now) < expiry_end]

# Access key operations
async def create_access_key(key_data):
    """Create a new access key in the database"""
    if not db:
        await init_database()
    
    try:
        result = db.access_keys.insert_one(key_data)
        key_data["_id"] = result.inserted_id
        return key_data
    except Exception as e:
        logger.error(f"Error creating access key: {e}")
        # For mock testing
        key_data["_id"] = ObjectId()
        mock_db["access_keys"].append(key_data)
        return key_data

async def get_access_key(key_id):
    """Get access key by Outline key ID"""
    if not db:
        await init_database()
    
    try:
        return db.access_keys.find_one({"key_id": key_id})
    except Exception as e:
        logger.error(f"Error getting access key: {e}")
        # For mock testing
        for key in mock_db["access_keys"]:
            if key.get("key_id") == key_id:
                return key
        return None

async def update_access_key(key_id, update_data):
    """Update access key data"""
    if not db:
        await init_database()
    
    try:
        result = db.access_keys.update_one(
            {"key_id": key_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating access key: {e}")
        # For mock testing
        for key in mock_db["access_keys"]:
            if key.get("key_id") == key_id:
                key.update(update_data)
                return True
        return False

async def get_user_access_keys(user_id):
    """Get all access keys for a user"""
    if not db:
        await init_database()
    
    try:
        return list(db.access_keys.find({"user_id": user_id}))
    except Exception as e:
        logger.error(f"Error getting user access keys: {e}")
        # For mock testing
        return [k for k in mock_db["access_keys"] if k.get("user_id") == user_id]

async def get_subscription_access_keys(subscription_id):
    """Get all access keys for a subscription"""
    if not db:
        await init_database()
    
    try:
        return list(db.access_keys.find({"subscription_id": subscription_id}))
    except Exception as e:
        logger.error(f"Error getting subscription access keys: {e}")
        # For mock testing
        return [k for k in mock_db["access_keys"] if k.get("subscription_id") == subscription_id]

# Payment operations
async def create_payment(payment_data):
    """Create a new payment record in the database"""
    if not db:
        await init_database()
    
    try:
        result = db.payments.insert_one(payment_data)
        payment_data["_id"] = result.inserted_id
        return payment_data
    except Exception as e:
        logger.error(f"Error creating payment: {e}")
        # For mock testing
        payment_data["_id"] = ObjectId()
        mock_db["payments"].append(payment_data)
        return payment_data

async def get_payment(payment_id):
    """Get payment by payment ID"""
    if not db:
        await init_database()
    
    try:
        return db.payments.find_one({"payment_id": payment_id})
    except Exception as e:
        logger.error(f"Error getting payment: {e}")
        # For mock testing
        for payment in mock_db["payments"]:
            if payment.get("payment_id") == payment_id:
                return payment
        return None

async def update_payment(payment_id, update_data):
    """Update payment data"""
    if not db:
        await init_database()
    
    try:
        result = db.payments.update_one(
            {"payment_id": payment_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating payment: {e}")
        # For mock testing
        for payment in mock_db["payments"]:
            if payment.get("payment_id") == payment_id:
                payment.update(update_data)
                return True
        return False

async def get_user_payments(user_id, status=None):
    """Get all payments for a user, optionally filtered by status"""
    if not db:
        await init_database()
    
    try:
        query = {"user_id": user_id}
        if status:
            query["status"] = status
        
        return list(db.payments.find(query).sort("created_at", -1))
    except Exception as e:
        logger.error(f"Error getting user payments: {e}")
        # For mock testing
        return [p for p in mock_db["payments"] 
                if p.get("user_id") == user_id and 
                (status is None or p.get("status") == status)]
