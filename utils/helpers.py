import time
from datetime import datetime

def format_bytes(size_bytes):
    """
    Format bytes to human-readable form
    """
    if size_bytes is None:
        return "0 B"
    
    size_bytes = int(size_bytes)
    
    if size_bytes == 0:
        return "0 B"
    
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = 0
    while size_bytes >= 1024 and i < len(size_name) - 1:
        size_bytes /= 1024
        i += 1
    
    return f"{size_bytes:.2f} {size_name[i]}"

def format_expiry_date(timestamp_or_date):
    """
    Format Unix timestamp or datetime object to human-readable date
    """
    if not timestamp_or_date:
        return "Бессрочно"
    
    # Convert to datetime if timestamp
    if isinstance(timestamp_or_date, (int, float, str)):
        try:
            date = datetime.fromtimestamp(int(timestamp_or_date))
        except (ValueError, TypeError):
            return "Неверный формат даты"
    else:
        # Assume it's already a datetime object
        date = timestamp_or_date
    
    # If expired
    if date < datetime.now():
        return "Истек"
    
    # Format date
    return date.strftime("%d.%m.%Y %H:%M")

def calculate_expiry(days):
    """
    Calculate expiry timestamp from days
    """
    return int(time.time()) + (days * 86400)  # 86400 seconds in a day
