import os
import logging
import uuid
import json
from datetime import datetime, timedelta

from yookassa import Configuration, Payment
from yookassa.domain.notification import WebhookNotification

from config import YUKASSA_SHOP_ID, YUKASSA_SECRET_KEY, VPN_PLANS
import services.database_service_sql as db

logger = logging.getLogger(__name__)

# Initialize YooKassa
try:
    Configuration.configure(YUKASSA_SHOP_ID, YUKASSA_SECRET_KEY)
    logger.info(f"YooKassa initialized successfully with shop_id: {YUKASSA_SHOP_ID}")
except Exception as e:
    logger.error(f"Failed to configure YooKassa: {e}")

async def create_payment(user_id, plan_id, return_url=None):
    """Create a payment with YooKassa"""
    try:
        logger.info(f"Starting payment creation for user_id: {user_id}, plan_id: {plan_id}")
        
        # Validate plan_id
        if plan_id not in VPN_PLANS:
            raise ValueError(f"Invalid plan ID: {plan_id}")
        
        # Get plan details
        plan = VPN_PLANS[plan_id]
        amount = plan.get("price", 0)
        logger.info(f"Plan details: {plan['name']}, price: {amount}")
        
        # Force test mode for troubleshooting
        is_test = True
        logger.info(f"Forcing test mode for troubleshooting")
        
        # Check if user exists in the database and create if not
        logger.info(f"Checking if user {user_id} exists in database")
        user = await db.get_user(user_id)
        if not user:
            # Create user in database
            logger.info(f"User {user_id} not found, creating new user record")
            user_data = {
                "telegram_id": user_id,
                "username": f"user_{user_id}",
                "created_at": datetime.now(),
                "is_premium": False
            }
            user = await db.create_user(user_data)
            if not user:
                logger.error(f"Failed to create user record for ID {user_id}")
                raise ValueError(f"Failed to create user record for ID {user_id}")
            logger.info(f"User created successfully: {user.telegram_id}, database ID: {user.id}")
        
        # Get the internal user ID (not telegram_id)
        db_user_id = user.id
        logger.info(f"Using database user ID: {db_user_id} for subscription")
        
        # Skip payment flow for test plan, free plans, or when troubleshooting
        if plan_id == "test" or amount <= 0 or is_test:
            logger.info(f"Test plan selected, skipping payment for user {user_id}")
            
            # Create subscription in database
            subscription_data = {
                "subscription_id": f"test_{str(uuid.uuid4())[:8]}",
                "user_id": user_id,
                "plan_id": plan_id,
                "status": "active",
                "created_at": datetime.now(),
                "expires_at": datetime.now() + timedelta(days=plan.get("duration", 3)),
                "price_paid": 0.0
            }
            
            subscription = await db.create_subscription(subscription_data)
            if not subscription:
                raise ValueError("Failed to create test subscription record")
                
            subscription_id = subscription.subscription_id
            
            # Return dummy payment info
            test_payment_id = f"test_payment_{str(uuid.uuid4())[:8]}"
            
            # Create payment record in database for test plan
            payment_data = {
                "payment_id": test_payment_id,
                "user_id": user_id,
                "subscription_id": subscription_id,
                "amount": 0.0,
                "currency": "RUB",
                "status": "succeeded",
                "created_at": datetime.now(),
                "completed_at": datetime.now()
            }
            
            await db.create_payment(payment_data)
            
            # Return payment info
            return {
                "id": test_payment_id,
                "status": "succeeded",
                "subscription_id": subscription_id,
                "is_test": True
            }
            
        # Create unique idempotence key
        idempotence_key = str(uuid.uuid4())
        
        # Create subscription record first
        subscription_data = {
            "subscription_id": str(uuid.uuid4()),
            "user_id": user_id,
            "plan_id": plan_id,
            "status": "pending",
            "created_at": datetime.now(),
            "expires_at": None,
            "price_paid": 0.0
        }
        
        subscription = await db.create_subscription(subscription_data)
        if not subscription:
            raise ValueError("Failed to create subscription record")
            
        subscription_id = subscription.subscription_id
        
        # Set default return_url if not provided
        if not return_url:
            return_url = "https://t.me/vpn_outline_manager_bot"  # Replace with your bot's username
        
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
                "return_url": return_url
            },
            "description": f"Оплата VPN, тариф {plan.get('name')}",
            "metadata": {
                "subscription_id": str(subscription_id),
                "user_id": str(user_id),
                "plan_id": plan_id
            }
        }, idempotence_key)
        
        # Create payment record in database
        payment_data = {
            "payment_id": payment.id,
            "user_id": user_id,
            "subscription_id": subscription_id,
            "amount": float(amount),
            "currency": "RUB",
            "status": "pending",
            "created_at": datetime.now()
        }
        
        await db.create_payment(payment_data)
        
        # Update subscription with payment ID
        await db.update_subscription(subscription_id, {
            "payment_id": payment.id,
            "status": "pending"
        })
        
        # Return payment info with confirmation URL
        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": payment.confirmation.confirmation_url,
            "subscription_id": subscription_id
        }
    
    except Exception as e:
        logger.error(f"Payment creation error: {e}")
        raise

async def check_payment_status(payment_id):
    """Check payment status in YooKassa"""
    try:
        # Special handling for test payment IDs
        if str(payment_id).startswith("test_"):
            logger.info(f"Test payment check for {payment_id}")
            return "succeeded"
            
        # Get payment from YooKassa
        payment = Payment.find_one(payment_id)
        if not payment:
            logger.error(f"Payment {payment_id} not found in YooKassa")
            return "not_found"
            
        logger.info(f"Payment {payment_id} status: {payment.status}")
        return payment.status
    
    except Exception as e:
        logger.error(f"Error checking payment status: {e}")
        return "error"

async def process_payment(payment_id):
    """Process a successful payment"""
    from datetime import timedelta
    
    try:
        # Get payment from database
        payment = await db.get_payment(payment_id)
        if not payment:
            logger.error(f"Payment {payment_id} not found in database")
            return False
            
        # If payment already processed
        if payment.status == "succeeded":
            logger.info(f"Payment {payment_id} already processed")
            return True
            
        # Get payment status from YooKassa
        status = await check_payment_status(payment_id)
        
        # For test payments, always succeed
        if str(payment_id).startswith("test_") or status == "succeeded":
            # Get subscription
            subscription = await db.get_subscription(payment.subscription_id)
            if not subscription:
                logger.error(f"Subscription {payment.subscription_id} not found")
                return False
                
            # Get plan details
            plan = VPN_PLANS.get(subscription.plan_id)
            if not plan:
                logger.error(f"Plan {subscription.plan_id} not found")
                return False
                
            # Calculate expiry date
            expires_at = datetime.now() + timedelta(days=plan.get("duration", 30))
            
            # Update subscription
            await db.update_subscription(subscription.subscription_id, {
                "status": "active",
                "expires_at": expires_at,
                "price_paid": float(payment.amount)
            })
            
            # Update payment
            await db.update_payment(payment_id, {
                "status": "succeeded",
                "completed_at": datetime.now()
            })
            
            logger.info(f"Payment {payment_id} processed successfully")
            return True
        else:
            logger.info(f"Payment {payment_id} status is {status}, not processing")
            return False
    
    except Exception as e:
        logger.error(f"Error processing payment: {e}")
        return False

async def process_webhook(payload):
    """Process YooKassa webhook notification"""
    try:
        # Parse standard webhook notification
        notification_object = WebhookNotification(payload)
        payment = notification_object.object
        
        if payment.status == "succeeded":
            # Payment successful, process subscription
            metadata = payment.metadata
            if not metadata:
                logger.error("No metadata in payment")
                return False
            
            subscription_id = metadata.get("subscription_id")
            if not subscription_id:
                logger.error("No subscription_id in metadata")
                return False
            
            user_id = metadata.get("user_id")
            if not user_id:
                logger.error("No user_id in metadata")
                return False
            
            # Update payment status in database
            await db.update_payment(payment.id, {
                "status": "succeeded",
                "completed_at": datetime.now()
            })
            
            # Process the payment (update subscription, etc.)
            await process_payment(payment.id)
            
            return True
        
        return False
    
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return False
