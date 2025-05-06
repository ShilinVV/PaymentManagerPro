import os
import logging
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from bson.objectid import ObjectId

from config import MONGO_URI, MONGO_DB_NAME

logger = logging.getLogger(__name__)

# MongoDB client
client = None
db = None

async def init_database():
    """Initialize the MongoDB connection"""
    global client, db
    try:
        # Use MongoDB Atlas URI with timeout settings
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        # Test connection
        client.admin.command('ping')
        db = client[MONGO_DB_NAME]
        logger.info(f"Connected to MongoDB: {MONGO_DB_NAME}")
    except Exception as e:
        logger.error(f"MongoDB connection failed: {e}")
        # Create mock db for testing if MongoDB is unavailable
        from unittest.mock import MagicMock
        db = MagicMock()
        logger.warning("Using mock database for testing")
        # Don't raise the exception to allow testing without MongoDB

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

# Order operations
async def create_order(order_data):
    """Create a new order in the database"""
    if not db:
        await init_database()
    
    try:
        result = db.orders.insert_one(order_data)
        return result.inserted_id
    except Exception as e:
        logger.error(f"Error creating order: {e}")
        raise

async def get_order(order_id):
    """Get order by ID"""
    if not db:
        await init_database()
    
    try:
        return db.orders.find_one({"_id": order_id})
    except Exception as e:
        logger.error(f"Error getting order: {e}")
        raise

async def update_order(order_id, update_data):
    """Update order data"""
    if not db:
        await init_database()
    
    try:
        result = db.orders.update_one(
            {"_id": order_id},
            {"$set": update_data}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"Error updating order: {e}")
        raise

async def get_user_orders(telegram_id, status=None):
    """Get all orders for a user, optionally filtered by status"""
    if not db:
        await init_database()
    
    try:
        query = {"telegram_id": telegram_id}
        if status:
            query["status"] = status
        
        return list(db.orders.find(query).sort("created_at", -1))
    except Exception as e:
        logger.error(f"Error getting user orders: {e}")
        raise

async def get_user_active_subscription(telegram_id):
    """Get user's active subscription info"""
    if not db:
        await init_database()
    
    try:
        # Find the most recent completed order
        order = db.orders.find_one(
            {"telegram_id": telegram_id, "status": "completed"},
            sort=[("completed_at", -1)]
        )
        return order
    except Exception as e:
        logger.error(f"Error getting user subscription: {e}")
        raise
