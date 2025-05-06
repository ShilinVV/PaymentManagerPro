import os
import logging
import aiohttp
import time
import json
from datetime import datetime, timedelta

from config import MARZBAN_API_BASE_URL, MARZBAN_API_USERNAME, MARZBAN_API_PASSWORD

logger = logging.getLogger(__name__)

class MarzbanService:
    """Service for interacting with Marzban API"""
    
    def __init__(self):
        self.base_url = MARZBAN_API_BASE_URL
        self.username = MARZBAN_API_USERNAME
        self.password = MARZBAN_API_PASSWORD
        self.token = None
        self.token_expires = 0
    
    async def _get_token(self):
        """Get authentication token from Marzban API"""
        if self.token and time.time() < self.token_expires:
            return self.token
        
        try:
            async with aiohttp.ClientSession() as session:
                login_data = {
                    "username": self.username,
                    "password": self.password
                }
                
                async with session.post(
                    f"{self.base_url}/api/admin/token",
                    data=login_data
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"Failed to get token: {error_text}")
                        raise Exception(f"Authentication failed: {response.status}")
                    
                    result = await response.json()
                    self.token = result.get("access_token")
                    # Set token expiry (1 hour by default)
                    self.token_expires = time.time() + 3500
                    return self.token
        except Exception as e:
            logger.error(f"Error getting Marzban token: {e}")
            raise
    
    async def _make_request(self, method, endpoint, data=None, params=None):
        """Make a request to Marzban API"""
        token = await self._get_token()
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        url = f"{self.base_url}/api{endpoint}"
        
        try:
            async with aiohttp.ClientSession() as session:
                if method.lower() == "get":
                    async with session.get(url, headers=headers, params=params) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.error(f"API error: {error_text}")
                            raise Exception(f"API error: {response.status}, {error_text}")
                        return await response.json()
                
                elif method.lower() == "post":
                    async with session.post(url, headers=headers, json=data) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.error(f"API error: {error_text}")
                            raise Exception(f"API error: {response.status}, {error_text}")
                        return await response.json()
                
                elif method.lower() == "put":
                    async with session.put(url, headers=headers, json=data) as response:
                        if response.status >= 400:
                            error_text = await response.text()
                            logger.error(f"API error: {error_text}")
                            raise Exception(f"API error: {response.status}, {error_text}")
                        return await response.json()
                
                elif method.lower() == "delete":
                    async with session.delete(url, headers=headers) as response:
                        return response.status < 400
                
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
        except Exception as e:
            logger.error(f"Request error: {e}")
            raise
    
    async def get_all_users(self):
        """Get all users from Marzban"""
        return await self._make_request("get", "/users")
    
    async def get_user(self, username):
        """Get user by username"""
        try:
            return await self._make_request("get", f"/user/{username}")
        except Exception as e:
            if "404" in str(e):
                return None
            raise
    
    async def create_user(self, username, data_limit=None, days=30):
        """Create a new user in Marzban"""
        # Calculate expire time
        expire = int((datetime.now() + timedelta(days=days)).timestamp())
        
        user_data = {
            "username": username,
            "proxies": {
                "vmess": {"enabled": True},
                "vless": {"enabled": True},
                "trojan": {"enabled": True},
                "shadowsocks": {"enabled": True}
            },
            "expire": expire,
            "data_limit": data_limit,
            "data_limit_reset_strategy": "no_reset" if data_limit else None
        }
        
        return await self._make_request("post", "/user", data=user_data)
    
    async def update_user(self, username, data_limit=None, days=30):
        """Update an existing user in Marzban"""
        # Get current user data
        current_user = await self.get_user(username)
        if not current_user:
            raise Exception(f"User {username} not found")
        
        # Calculate new expiry, adding days to current expiry or to now if expired
        current_expire = current_user.get("expire", 0)
        current_time = int(datetime.now().timestamp())
        
        if current_expire and current_expire > current_time:
            # User not expired, add days to current expiry
            new_expire = current_expire + (days * 86400)  # days in seconds
        else:
            # User expired or no expiry, set new expiry from now
            new_expire = current_time + (days * 86400)
        
        # Prepare update data
        update_data = {
            "expire": new_expire
        }
        
        # Update data limit if provided
        if data_limit:
            update_data["data_limit"] = data_limit
            update_data["data_limit_reset_strategy"] = "no_reset"
        
        # Set status to active
        update_data["status"] = "active"
        
        return await self._make_request("put", f"/user/{username}", data=update_data)
    
    async def delete_user(self, username):
        """Delete a user from Marzban"""
        return await self._make_request("delete", f"/user/{username}")
    
    async def reset_user_traffic(self, username):
        """Reset user traffic"""
        return await self._make_request("post", f"/user/{username}/reset")
