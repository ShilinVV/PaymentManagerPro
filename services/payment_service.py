import os
import logging
import uuid
import json
from datetime import datetime
from bson.objectid import ObjectId

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

from config import YUKASSA_SHOP_ID, YUKASSA_SECRET_KEY, VPN_PLANS
from services.database_service import get_order, update_order

logger = logging.getLogger(__name__)

# Initialize YooKassa
try:
    Configuration.configure(YUKASSA_SHOP_ID, YUKASSA_SECRET_KEY)
except Exception as e:
    logger.error(f"Failed to configure YooKassa: {e}")

async def create_payment(order_id, user_id):
    """Create a payment with YooKassa"""
    try:
        # Get order details
        order = await get_order(ObjectId(order_id))
        if not order:
            raise ValueError(f"Order {order_id} not found")
        
        plan_id = order.get("plan_id")
        if not plan_id or plan_id not in VPN_PLANS:
            raise ValueError(f"Invalid plan ID: {plan_id}")
        
        plan = VPN_PLANS[plan_id]
        amount = plan.get("price")
        
        # Create unique idempotence key
        idempotence_key = str(uuid.uuid4())
        
        # Create payment
        payment = Payment.create({
            "amount": {
                "value": str(amount),
                "currency": "RUB"
            },
            "payment_method_data": {
                "type": "bank_card"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": "https://t.me/your_bot_username"  # Replace with your bot username
            },
            "description": f"Оплата услуг VPN, тариф {plan.get('name')}",
            "metadata": {
                "order_id": str(order_id),
                "user_id": user_id
            }
        }, idempotence_key)
        
        # Update order with payment ID
        await update_order(ObjectId(order_id), {
            "payment_id": payment.id,
            "idempotence_key": idempotence_key
        })
        
        # Return confirmation URL
        return payment.confirmation.confirmation_url
    
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        raise

async def check_payment(order_id):
    """Check payment status in YooKassa"""
    try:
        # Get order details
        order = await get_order(ObjectId(order_id))
        if not order:
            raise ValueError(f"Order {order_id} not found")
        
        payment_id = order.get("payment_id")
        if not payment_id:
            raise ValueError(f"No payment ID for order {order_id}")
        
        # Get payment from YooKassa
        payment = Payment.find_one(payment_id)
        
        if payment.status == "succeeded":
            # Update order status if payment succeeded
            await update_order(ObjectId(order_id), {
                "status": "paid",
                "paid_at": datetime.now()
            })
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Payment check error: {e}")
        raise

async def process_webhook(payload):
    """Process YooKassa webhook notification"""
    try:
        # Parse webhook notification
        notification_object = WebhookNotification(payload)
        payment = notification_object.object
        
        if payment.status == "succeeded":
            # Payment successful, process order
            metadata = payment.metadata
            if not metadata:
                logger.error("No metadata in payment")
                return False
            
            order_id = metadata.get("order_id")
            if not order_id:
                logger.error("No order_id in metadata")
                return False
            
            # Update order status
            await update_order(ObjectId(order_id), {
                "status": "paid",
                "paid_at": datetime.now()
            })
            
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        raise
