import os
import logging
import time  # Добавлено для token_expires
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class MarzbanService:
    """Temporary stub for MarzbanService to maintain compatibility"""
    
    def __init__(self):
        """Initialize the service"""
        logger.warning("Using stub MarzbanService - this will be replaced with OutlineService")
        self.base_url = None
        self.username = None
        self.password = None
        self.token = None
        self.token_expires = 0
    
    async def _get_token(self):
        """Stub for _get_token"""
        logger.warning("Using stub MarzbanService._get_token")
        return "stub_token"
    
    async def _make_request(self, method, endpoint, data=None, params=None):
        """Stub for _make_request"""
        logger.warning(f"Using stub MarzbanService._make_request: {method} {endpoint}")
        # Не используется aiohttp в заглушке
        return {}
    
    async def get_all_users(self):
        """Stub for get_all_users"""
        logger.warning("Using stub MarzbanService.get_all_users")
        return {"users": []}
    
    async def get_user(self, username):
        """Stub for get_user"""
        logger.warning(f"Using stub MarzbanService.get_user: {username}")
        # Return a mock user for compatibility
        return {
            "username": username,
            "status": "active",
            "created_at": str(datetime.now()),
            "data_limit": 0,
            "data_usage": 0,
            "expire": int((datetime.now() + timedelta(days=30)).timestamp())
        }
    
    async def create_user(self, username, data_limit=None, days=30):
        """Stub for create_user"""
        logger.warning(f"Using stub MarzbanService.create_user: {username}")
        # Return a mock user for compatibility
        return {
            "username": username,
            "status": "active",
            "created_at": str(datetime.now()),
            "data_limit": data_limit,
            "data_usage": 0,
            "expire": int((datetime.now() + timedelta(days=days)).timestamp())
        }
    
    async def update_user(self, username, data_limit=None, days=30):
        """Stub for update_user"""
        logger.warning(f"Using stub MarzbanService.update_user: {username}")
        # Return a mock user for compatibility
        return {
            "username": username,
            "status": "active",
            "data_limit": data_limit,
            "expire": int((datetime.now() + timedelta(days=days)).timestamp())
        }
    
    async def delete_user(self, username):
        """Stub for delete_user"""
        logger.warning(f"Using stub MarzbanService.delete_user: {username}")
        return True
    
    async def reset_user_traffic(self, username):
        """Stub for reset_user_traffic"""
        logger.warning(f"Using stub MarzbanService.reset_user_traffic: {username}")
        return {"success": True}
