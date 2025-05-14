import os
import json
import logging
import aiohttp
import certifi
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

class OutlineService:
    """Service for interacting with Outline VPN API"""
    
    def __init__(self):
        """Initialize the Outline service with API URL"""
        self.api_url = os.environ.get("OUTLINE_API_URL")
        if not self.api_url:
            logger.error("OUTLINE_API_URL environment variable is not set")
            raise ValueError("OUTLINE_API_URL environment variable is not set")
        
        # For SSL verification
        self.ssl_context = certifi.where()
        logger.info(f"Outline API URL: {self.api_url}")
    
    async def _make_request(self, method, endpoint, data=None):
        """Make a request to Outline API
        
        Args:
            method (str): HTTP method (GET, POST, DELETE, PUT)
            endpoint (str): API endpoint
            data (dict, optional): Request data. Defaults to None.
            
        Returns:
            dict: Response data
        """
        url = f"{self.api_url}/{endpoint}"
        
        # Don't verify SSL in development for self-signed certs
        # In production, this should be removed or set to True
        ssl = False  
        
        try:
            async with aiohttp.ClientSession() as session:
                if method == "GET":
                    async with session.get(url, ssl=ssl) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            error_text = await response.text()
                            logger.error(f"Outline API error: {error_text}")
                            return {"error": f"API request failed with status {response.status}: {error_text}"}
                
                elif method == "POST":
                    headers = {"Content-Type": "application/json"}
                    async with session.post(url, json=data, headers=headers, ssl=ssl) as response:
                        if response.status in (200, 201):
                            return await response.json()
                        else:
                            error_text = await response.text()
                            logger.error(f"Outline API error: {error_text}")
                            return {"error": f"API request failed with status {response.status}: {error_text}"}
                
                elif method == "DELETE":
                    async with session.delete(url, ssl=ssl) as response:
                        if response.status == 204:
                            return {"success": True}
                        else:
                            error_text = await response.text()
                            logger.error(f"Outline API error: {error_text}")
                            return {"error": f"API request failed with status {response.status}: {error_text}"}
                
                elif method == "PUT":
                    headers = {"Content-Type": "application/json"}
                    async with session.put(url, json=data, headers=headers, ssl=ssl) as response:
                        if response.status == 200:
                            return await response.json()
                        else:
                            error_text = await response.text()
                            logger.error(f"Outline API error: {error_text}")
                            return {"error": f"API request failed with status {response.status}: {error_text}"}
        
        except Exception as e:
            logger.error(f"Error in Outline API request: {e}")
            return {"error": str(e)}
    
    async def get_server_info(self):
        """Get server information
        
        Returns:
            dict: Server information
        """
        return await self._make_request("GET", "server")
    
    async def get_metrics(self):
        """Get server metrics
        
        Returns:
            dict: Server metrics
        """
        return await self._make_request("GET", "metrics")
    
    async def get_keys(self):
        """Get all access keys
        
        Returns:
            dict: List of access keys
        """
        return await self._make_request("GET", "access-keys")
    
    async def create_key(self, name=None):
        """Create a new access key
        
        Args:
            name (str, optional): Key name. Defaults to None.
            
        Returns:
            dict: Created key information
        """
        data = {}
        if name:
            data["name"] = name
        
        return await self._make_request("POST", "access-keys", data)
    
    async def delete_key(self, key_id):
        """Delete an access key
        
        Args:
            key_id (str): Key ID
            
        Returns:
            dict: Success status
        """
        return await self._make_request("DELETE", f"access-keys/{key_id}")
    
    async def rename_key(self, key_id, name):
        """Rename an access key
        
        Args:
            key_id (str): Key ID
            name (str): New name
            
        Returns:
            dict: Updated key information
        """
        data = {"name": name}
        return await self._make_request("PUT", f"access-keys/{key_id}/name", data)
    
    async def get_key_metrics(self, key_id):
        """Get metrics for a specific key
        
        Args:
            key_id (str): Key ID
            
        Returns:
            dict: Key metrics
        """
        return await self._make_request("GET", f"access-keys/{key_id}/metrics")
    
    async def get_key(self, key_id):
        """Get information about a specific key
        
        Args:
            key_id (str): Key ID
            
        Returns:
            dict: Key information
        """
        # Get all keys first and then filter for the specific key
        keys_resp = await self.get_keys()
        if "error" in keys_resp:
            return keys_resp
        
        for key in keys_resp.get("accessKeys", []):
            if key.get("id") == key_id:
                return key
        
        return {"error": f"Key with ID {key_id} not found"}

    async def create_key_with_expiration(self, days, name=None):
        """Create a key and set an expiration date in the name (for tracking)
        
        Args:
            days (int): Number of days until expiration
            name (str, optional): Base name. Defaults to None.
            
        Returns:
            dict: Created key information with expiration
        """
        # Calculate expiration date
        expiry_date = datetime.now() + timedelta(days=days)
        expiry_str = expiry_date.strftime("%Y-%m-%d")
        
        # Create name with expiration info
        key_name = f"{name or 'VPN'} (До: {expiry_str})"
        
        # Create the key
        key_data = await self.create_key(key_name)
        
        # Add expiration date to returned data
        if "error" not in key_data:
            key_data["expiresAt"] = expiry_str
        
        return key_data
        
    async def extend_key_expiration(self, key_id, days, name=None):
        """Extend the expiration date of an existing key by updating its name
        
        Args:
            key_id (str): ID of the existing key to extend
            days (int): Number of days until new expiration
            name (str, optional): Base name. If None, will try to preserve existing name format
            
        Returns:
            dict: Updated key information with new expiration
        """
        try:
            # Get current key info
            current_key = await self.get_key(key_id)
            if "error" in current_key:
                logging.error(f"Key {key_id} not found for extension")
                return current_key
                
            current_name = current_key.get('name', '')
            
            # Extract base name from current format if possible
            base_name = name
            if not base_name and current_name:
                # Try to extract base name from "Name (До: YYYY-MM-DD)"
                import re
                match = re.match(r'^(.*?)\s*\(До:', current_name)
                if match:
                    base_name = match.group(1).strip()
                else:
                    base_name = current_name
            
            # Set new expiration date
            expiry_date = datetime.now() + timedelta(days=days)
            expiry_str = expiry_date.strftime("%Y-%m-%d")
            
            # Create new name with expiration info
            key_name = f"{base_name or 'VPN'} (До: {expiry_str})"
            
            # Update the key name
            result = await self.rename_key(key_id, key_name)
            
            # Add expiration date to returned data
            if "error" not in result:
                result["expiresAt"] = expiry_str
            
            return result
        except Exception as e:
            logging.error(f"Failed to extend key expiration: {e}")
            return {"error": f"Failed to extend key: {str(e)}"}
            
    async def find_user_keys(self, user_id, subscription_id=None):
        """Find all keys associated with a user
        
        Args:
            user_id: Telegram user ID
            subscription_id (optional): Filter by subscription ID
            
        Returns:
            list: List of matching keys from database
        """
        # Implement this when integrating with database service
        # This functionality should be implemented in database service
        return []