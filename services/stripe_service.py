"""
Stripe service for handling subscription payments and webhooks.
"""

import os
import stripe
import json
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from flask import request
from core.logging_utils import get_safe_logger

from services.user_service import get_user_service


class StripeService:
    def __init__(self):
        """Initialize Stripe with API keys."""
        stripe.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.publishable_key = os.getenv('STRIPE_PUBLISHABLE_KEY')
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        
        # Price IDs for subscription plans (set these in Stripe dashboard)
        self.monthly_price_id = os.getenv('STRIPE_MONTHLY_PRICE_ID')
        self.yearly_price_id = os.getenv('STRIPE_YEARLY_PRICE_ID')
        
        self.user_service = get_user_service()
        
        # Context-aware logger
        self.logger = get_safe_logger(__name__)
    
    def find_existing_stripe_customer(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Search for existing Stripe customer by email.
        Returns customer data if found, None if not found.
        """
        try:
            email = email.lower().strip()
            self.logger.info(f"🔍 Searching for existing Stripe customer with email: {email}")
            
            # Search for customers with this email
            customers = stripe.Customer.list(
                email=email,
                limit=10  # Should only be 1, but safety margin
            )
            
            active_customers = []
            deleted_customers = []
            
            for customer in customers.data:
                if customer.get('deleted', False):
                    deleted_customers.append(customer)
                else:
                    active_customers.append(customer)
            
            # Log findings
            if active_customers:
                self.logger.info(f"✅ Found {len(active_customers)} active Stripe customer(s) for {email}")
                for customer in active_customers:
                    self.logger.info(f"   - Customer ID: {customer.id}, Created: {customer.created}")
            
            if deleted_customers:
                self.logger.info(f"🗑️ Found {len(deleted_customers)} deleted Stripe customer(s) for {email}")
            
            if not active_customers and not deleted_customers:
                self.logger.info(f"❌ No Stripe customers found for {email}")
                return None
            
            # Return the most recent active customer, or None if only deleted ones exist
            if active_customers:
                # Sort by creation date, most recent first
                most_recent = max(active_customers, key=lambda c: c.created)
                return {
                    'id': most_recent.id,
                    'email': most_recent.email,
                    'created': most_recent.created,
                    'deleted': False,
                    'total_found': len(active_customers),
                    'has_deleted': len(deleted_customers) > 0
                }
            
            # Only deleted customers found
            return {
                'id': None,
                'email': email,
                'created': None,
                'deleted': True,
                'total_found': 0,
                'has_deleted': len(deleted_customers),
                'latest_deleted_id': deleted_customers[0].id if deleted_customers else None
            }
            
        except stripe.error.StripeError as e:
            self.logger.error(f"❌ Stripe error searching for customer {email}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error searching for customer {email}: {e}")
            return None

    def create_customer(self, email: str, name: str = None) -> Optional[str]:
        """Create a Stripe customer, checking for existing customers first."""
        try:
            # First, check if customer already exists in Stripe
            existing_customer = self.find_existing_stripe_customer(email)
            
            if existing_customer:
                if not existing_customer['deleted']:
                    # Active customer found - return existing ID
                    self.logger.info(f"♻️ Using existing Stripe customer {existing_customer['id']} for {email}")
                    return existing_customer['id']
                else:
                    # Only deleted customers found
                    self.logger.warning(f"⚠️ Found only deleted Stripe customers for {email}. Creating new customer.")
            
            # No existing active customer - create new one
            customer_data = {
                'email': email,
                'metadata': {
                    'app': 'booksaver',
                    'created_via': 'auto_customer_creation'
                }
            }
            
            if name:
                customer_data['name'] = name
            
            # Add note if this email had previous deleted customers
            if existing_customer and existing_customer.get('has_deleted'):
                customer_data['metadata']['previous_deleted_customers'] = 'true'
                customer_data['metadata']['latest_deleted_id'] = existing_customer.get('latest_deleted_id', '')
            
            customer = stripe.Customer.create(**customer_data)
            
            self.logger.info(f"✅ New Stripe customer created: {customer.id} for {email}")
            return customer.id
            
        except stripe.error.InvalidRequestError as e:
            self.logger.error(f"❌ Invalid request creating Stripe customer for {email}: {e}")
            return None
        except stripe.error.AuthenticationError as e:
            self.logger.error(f"❌ Authentication error creating Stripe customer: {e}")
            return None
        except stripe.error.APIConnectionError as e:
            self.logger.error(f"❌ Network error creating Stripe customer for {email}: {e}")
            return None
        except stripe.error.StripeError as e:
            self.logger.error(f"❌ Stripe error creating customer for {email}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error creating Stripe customer for {email}: {e}")
            return None
    
    def create_checkout_session(self, email: str, plan: str, success_url: str, cancel_url: str) -> Optional[Dict[str, Any]]:
        """Create a Stripe checkout session for subscription."""
        try:
            # Get or create customer with enhanced validation
            user_data = self.user_service.get_user(email)
            subscription_data = self.user_service.get_subscription(email)
            
            customer_id = subscription_data.get('stripe_customer_id') if subscription_data else None
            
            # Validate existing customer ID if we have one
            if customer_id:
                try:
                    # Verify customer still exists and is valid
                    existing_customer = stripe.Customer.retrieve(customer_id)
                    if existing_customer.get('deleted', False):
                        self.logger.warning(f"⚠️ Stored customer {customer_id} is deleted for {email}. Will create new customer.")
                        customer_id = None
                    elif existing_customer.get('email', '').lower() != email.lower():
                        self.logger.warning(f"⚠️ Email mismatch for customer {customer_id}: expected {email}, got {existing_customer.get('email')}. Will create new customer.")
                        customer_id = None
                    else:
                        self.logger.info(f"✅ Validated existing customer {customer_id} for {email}")
                except stripe.error.InvalidRequestError:
                    self.logger.warning(f"⚠️ Stored customer ID {customer_id} not found in Stripe for {email}. Will create new customer.")
                    customer_id = None
            
            # Create or find customer if needed
            if not customer_id:
                # First check if customer exists in Stripe with this email
                existing_stripe_customer = self.find_existing_stripe_customer(email)
                
                if existing_stripe_customer and not existing_stripe_customer['deleted']:
                    # Found existing customer - use it
                    customer_id = existing_stripe_customer['id']
                    self.logger.info(f"🔗 Linking local user {email} to existing Stripe customer {customer_id}")
                else:
                    # Create new customer
                    customer_id = self.create_customer(email)
                    if not customer_id:
                        return {'error': 'Failed to create customer account. Please try again.'}
                
                # Update subscription data with customer ID
                self.user_service.update_subscription(email, {
                    'stripe_customer_id': customer_id
                })
            
            # Validate and determine price ID based on plan
            valid_plans = ['monthly', 'yearly']
            if plan not in valid_plans:
                self.logger.error(f"❌ Invalid plan '{plan}' for {email}. Valid plans: {valid_plans}")
                return {'error': f'Invalid plan. Choose from: {", ".join(valid_plans)}'}
            
            if plan == 'monthly':
                price_id = self.monthly_price_id
            elif plan == 'yearly':
                price_id = self.yearly_price_id
            
            if not price_id:
                self.logger.error(f"❌ Price ID not configured for plan '{plan}'. Check STRIPE_MONTHLY_PRICE_ID and STRIPE_YEARLY_PRICE_ID environment variables")
                return {'error': 'Subscription plan not available. Please contact support.'}
            
            # Validate that the price exists in Stripe
            try:
                stripe.Price.retrieve(price_id)
            except stripe.error.InvalidRequestError:
                self.logger.error(f"❌ Price ID '{price_id}' does not exist in Stripe for plan '{plan}'")
                return {'error': 'Subscription plan configuration error. Please contact support.'}
            
            # Create checkout session
            checkout_session = stripe.checkout.Session.create(
                customer=customer_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                success_url=success_url,
                cancel_url=cancel_url,
                metadata={
                    'user_email': email,
                    'plan': plan
                },
                allow_promotion_codes=True,
                billing_address_collection='auto'
            )
            
            self.logger.info(f"✅ Checkout session created: {checkout_session.id} for {email} (plan: {plan})")
            
            return {
                'session_id': checkout_session.id,
                'url': checkout_session.url
            }
            
        except stripe.error.InvalidRequestError as e:
            self.logger.error(f"❌ Invalid request creating checkout session for {email}: {e}")
            return {'error': 'Invalid subscription request. Please try again.'}
        except stripe.error.AuthenticationError as e:
            self.logger.error(f"❌ Authentication error creating checkout session: {e}")
            return {'error': 'Payment system temporarily unavailable. Please try again later.'}
        except stripe.error.APIConnectionError as e:
            self.logger.error(f"❌ Network error creating checkout session for {email}: {e}")
            return {'error': 'Connection error. Please check your internet connection and try again.'}
        except stripe.error.StripeError as e:
            self.logger.error(f"❌ Stripe error creating checkout session for {email}: {e}")
            return {'error': 'Payment processing error. Please try again or contact support.'}
        except Exception as e:
            self.logger.error(f"❌ Unexpected error creating checkout session for {email}: {e}")
            return {'error': 'An unexpected error occurred. Please try again.'}
    
    def create_billing_portal_session(self, email: str, return_url: str) -> Optional[str]:
        """Create a Stripe billing portal session for subscription management."""
        try:
            subscription_data = self.user_service.get_subscription(email)
            if not subscription_data:
                self.logger.warning(f"⚠️ No subscription data found for {email}")
                return None
            
            customer_id = subscription_data.get('stripe_customer_id')
            if not customer_id:
                self.logger.warning(f"⚠️ No Stripe customer ID found for {email}")
                return None
            
            # Verify customer exists in Stripe
            try:
                stripe.Customer.retrieve(customer_id)
            except stripe.error.InvalidRequestError:
                self.logger.error(f"❌ Stripe customer {customer_id} not found for {email}")
                return None
            
            # Create billing portal session
            portal_session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            
            self.logger.info(f"✅ Billing portal session created for {email}")
            return portal_session.url
            
        except stripe.error.InvalidRequestError as e:
            self.logger.error(f"❌ Invalid request creating billing portal for {email}: {e}")
            return None
        except stripe.error.AuthenticationError as e:
            self.logger.error(f"❌ Authentication error creating billing portal: {e}")
            return None
        except stripe.error.StripeError as e:
            self.logger.error(f"❌ Stripe error creating billing portal for {email}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"❌ Unexpected error creating billing portal for {email}: {e}")
            return None
    
    def _is_webhook_processed(self, event_id: str) -> bool:
        """Check if webhook event has already been processed."""
        try:
            # Use Redis to track processed webhooks with 7-day expiry
            return self.user_service.redis.exists(f"webhook:{event_id}")
        except Exception as e:
            self.logger.warning(f"⚠️ Could not check webhook idempotency for {event_id}: {e}")
            return False
    
    def _mark_webhook_processed(self, event_id: str) -> None:
        """Mark webhook event as processed."""
        try:
            # Store for 7 days to prevent duplicate processing
            self.user_service.redis.setex(f"webhook:{event_id}", 604800, "processed")
        except Exception as e:
            self.logger.warning(f"⚠️ Could not mark webhook {event_id} as processed: {e}")
    
    def handle_webhook(self, payload: bytes, sig_header: str) -> bool:
        """Handle Stripe webhook events with idempotency protection."""
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            
            event_id = event['id']
            event_type = event['type']
            
            self.logger.info(f"🎣 Stripe webhook received: {event_type} (ID: {event_id})")
            
            # Check if we've already processed this event (idempotency)
            if self._is_webhook_processed(event_id):
                self.logger.info(f"🔁 Webhook {event_id} already processed, skipping")
                return True
            
            # Handle different event types
            success = False
            if event_type == 'checkout.session.completed':
                success = self._handle_checkout_completed(event['data']['object'])
            
            elif event_type == 'customer.subscription.created':
                success = self._handle_subscription_created(event['data']['object'])
            
            elif event_type == 'customer.subscription.updated':
                success = self._handle_subscription_updated(event['data']['object'])
            
            elif event_type == 'customer.subscription.deleted':
                success = self._handle_subscription_cancelled(event['data']['object'])
            
            elif event_type == 'invoice.payment_succeeded':
                success = self._handle_payment_succeeded(event['data']['object'])
            
            elif event_type == 'invoice.payment_failed':
                success = self._handle_payment_failed(event['data']['object'])
            
            else:
                self.logger.info(f"⚠️ Unhandled webhook event: {event_type}")
                success = True  # Not an error, just unhandled
            
            # Mark webhook as processed if successful
            if success:
                self._mark_webhook_processed(event_id)
            
            return success
            
        except ValueError as e:
            self.logger.error(f"❌ Invalid webhook payload: {e}")
            return False
        except stripe.error.SignatureVerificationError as e:
            self.logger.error(f"❌ Webhook signature verification failed: {e}")
            return False
        except Exception as e:
            self.logger.error(f"❌ Webhook handling error: {e}")
            return False
    
    def _handle_checkout_completed(self, session) -> bool:
        """Handle successful checkout completion."""
        try:
            email = session.get('metadata', {}).get('user_email')
            plan = session.get('metadata', {}).get('plan')
            customer_id = session.get('customer')
            subscription_id = session.get('subscription')
            session_id = session.get('id')
            
            if not email:
                self.logger.error(f"❌ No user email in checkout session {session_id} metadata")
                return False
            
            if not customer_id or not subscription_id:
                self.logger.error(f"❌ Missing customer_id or subscription_id in checkout session {session_id} for {email}")
                return False
            
            # Verify user exists
            user_data = self.user_service.get_user(email)
            if not user_data:
                self.logger.error(f"❌ User {email} not found during checkout completion")
                return False
            
            # Update user subscription
            subscription_update = {
                'tier': 'premium',
                'status': 'active',
                'stripe_customer_id': customer_id,
                'stripe_subscription_id': subscription_id,
                'plan': plan,
                'activated_at': datetime.now(timezone.utc).isoformat()
            }
            
            success = self.user_service.update_subscription(email, subscription_update)
            if success:
                self.logger.info(f"✅ Subscription activated for {email} (session: {session_id}, plan: {plan})")
            else:
                self.logger.error(f"❌ Failed to update subscription for {email} (session: {session_id})")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle checkout completion: {e}")
            return False
    
    def _handle_subscription_created(self, subscription) -> bool:
        """Handle subscription creation."""
        try:
            customer_id = subscription.get('customer')
            subscription_id = subscription.get('id')
            status = subscription.get('status')
            
            # Find user by customer ID
            email = self._find_user_by_customer_id(customer_id)
            if not email:
                return False
            
            subscription_update = {
                'tier': 'premium' if status == 'active' else 'free',
                'status': status,
                'stripe_subscription_id': subscription_id
            }
            
            return self.user_service.update_subscription(email, subscription_update)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle subscription creation: {e}")
            return False
    
    def _handle_subscription_updated(self, subscription) -> bool:
        """Handle subscription updates."""
        try:
            customer_id = subscription.get('customer')
            status = subscription.get('status')
            
            # Find user by customer ID
            email = self._find_user_by_customer_id(customer_id)
            if not email:
                return False
            
            subscription_update = {
                'tier': 'premium' if status == 'active' else 'free',
                'status': status
            }
            
            return self.user_service.update_subscription(email, subscription_update)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle subscription update: {e}")
            return False
    
    def _handle_subscription_cancelled(self, subscription) -> bool:
        """Handle subscription cancellation."""
        try:
            customer_id = subscription.get('customer')
            
            # Find user by customer ID
            email = self._find_user_by_customer_id(customer_id)
            if not email:
                return False
            
            subscription_update = {
                'tier': 'free',
                'status': 'cancelled',
                'cancelled_at': datetime.now(timezone.utc).isoformat()
            }
            
            return self.user_service.update_subscription(email, subscription_update)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle subscription cancellation: {e}")
            return False
    
    def _handle_payment_succeeded(self, invoice) -> bool:
        """Handle successful payment."""
        try:
            customer_id = invoice.get('customer')
            
            # Find user by customer ID
            email = self._find_user_by_customer_id(customer_id)
            if not email:
                return False
            
            # Update subscription status to active
            subscription_update = {
                'status': 'active',
                'last_payment_at': datetime.now(timezone.utc).isoformat()
            }
            
            return self.user_service.update_subscription(email, subscription_update)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle payment success: {e}")
            return False
    
    def _handle_payment_failed(self, invoice) -> bool:
        """Handle failed payment."""
        try:
            customer_id = invoice.get('customer')
            
            # Find user by customer ID
            email = self._find_user_by_customer_id(customer_id)
            if not email:
                return False
            
            # Update subscription status
            subscription_update = {
                'status': 'past_due',
                'last_payment_failure_at': datetime.now(timezone.utc).isoformat()
            }
            
            return self.user_service.update_subscription(email, subscription_update)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to handle payment failure: {e}")
            return False
    
    def _find_user_by_customer_id(self, customer_id: str) -> Optional[str]:
        """Find user email by Stripe customer ID."""
        # This is a simple implementation - in a real app you might want to index this
        try:
            # Get customer from Stripe to get email
            customer = stripe.Customer.retrieve(customer_id)
            email = customer.get('email')
            
            if email:
                # Verify user exists in our system
                user_data = self.user_service.get_user(email)
                if user_data:
                    return email
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to find user by customer ID: {e}")
            return None
    
    def validate_user_subscription_status(self, email: str) -> Dict[str, Any]:
        """
        Validate user's subscription status directly from Stripe backend.
        Returns dict with status info and any discrepancies found.
        """
        try:
            # Get local subscription data
            local_subscription = self.user_service.get_subscription(email)
            
            result = {
                'has_local_subscription': bool(local_subscription),
                'local_tier': local_subscription.get('tier', 'free') if local_subscription else 'free',
                'local_status': local_subscription.get('status', 'none') if local_subscription else 'none',
                'stripe_customer_id': local_subscription.get('stripe_customer_id') if local_subscription else None,
                'stripe_subscription_id': local_subscription.get('stripe_subscription_id') if local_subscription else None,
                'has_active_stripe_subscription': False,
                'stripe_status': None,
                'stripe_tier': 'free',
                'discrepancy_found': False,
                'error': None
            }
            
            # If no local customer ID, user has no Stripe subscription
            if not result['stripe_customer_id']:
                self.logger.info(f"🔍 User {email} has no Stripe customer ID")
                return result
            
            try:
                # First, verify the customer exists and get customer details
                customer = stripe.Customer.retrieve(result['stripe_customer_id'])
                
                # Check if customer is deleted
                if customer.get('deleted', False):
                    result['stripe_customer_deleted'] = True
                    result['discrepancy_found'] = True
                    self.logger.warning(f"⚠️ Stripe customer {result['stripe_customer_id']} is deleted for {email}")
                    return result
                
                # Verify customer email matches (additional validation)
                stripe_email = customer.get('email', '').lower()
                if stripe_email and stripe_email != email.lower():
                    self.logger.warning(f"⚠️ Email mismatch for customer {result['stripe_customer_id']}: Stripe={stripe_email}, Local={email}")
                    result['error'] = f"Customer email mismatch: expected {email}, found {stripe_email}"
                    return result
                
                result['stripe_customer_exists'] = True
                self.logger.info(f"✅ Stripe customer {result['stripe_customer_id']} verified for {email}")
                
                # Get all subscriptions for this customer (not just active ones)
                all_subscriptions = stripe.Subscription.list(
                    customer=result['stripe_customer_id'],
                    limit=20  # Increased limit to catch more subscriptions
                )
                
                # Get only active subscriptions
                active_subscriptions = stripe.Subscription.list(
                    customer=result['stripe_customer_id'],
                    status='active',
                    limit=10
                )
                
                self.logger.info(f"🔍 Customer {result['stripe_customer_id']} has {len(all_subscriptions.data)} total subscriptions, {len(active_subscriptions.data)} active for {email}")
                
                # Check for active subscriptions
                active_subscription = None
                for sub in active_subscriptions.data:
                    if sub.status == 'active':
                        active_subscription = sub
                        self.logger.info(f"✅ Found active subscription {sub.id} for customer {result['stripe_customer_id']}")
                        break
                
                if active_subscription:
                    result['has_active_stripe_subscription'] = True
                    result['stripe_status'] = active_subscription.status
                    result['stripe_tier'] = 'premium'
                    result['stripe_subscription_id_actual'] = active_subscription.id
                    
                    # Check for discrepancies
                    if result['local_tier'] != 'premium' or result['local_status'] != 'active':
                        result['discrepancy_found'] = True
                        self.logger.warning(f"⚠️ Subscription discrepancy for {email}: local={result['local_tier']}/{result['local_status']}, stripe=premium/active")
                    
                    # Check if subscription IDs match
                    if result['stripe_subscription_id'] and result['stripe_subscription_id'] != active_subscription.id:
                        result['discrepancy_found'] = True
                        self.logger.warning(f"⚠️ Subscription ID mismatch for {email}: local={result['stripe_subscription_id']}, stripe={active_subscription.id}")
                else:
                    # No active subscription in Stripe - check if there are any past subscriptions
                    past_subscriptions = [sub for sub in all_subscriptions.data if sub.status in ['canceled', 'incomplete_expired', 'past_due', 'unpaid']]
                    if past_subscriptions:
                        latest_past = max(past_subscriptions, key=lambda s: s.created)
                        self.logger.info(f"📅 Latest past subscription {latest_past.id} status: {latest_past.status} for {email}")
                    
                    # Check for discrepancy with local data
                    if result['local_tier'] == 'premium' and result['local_status'] == 'active':
                        result['discrepancy_found'] = True
                        self.logger.warning(f"⚠️ Subscription discrepancy for {email}: local=premium/active, stripe=no active subscription")
                
            except stripe.error.InvalidRequestError as e:
                # Customer doesn't exist or invalid ID
                result['stripe_customer_exists'] = False
                result['discrepancy_found'] = True
                result['error'] = f"Stripe customer not found: {e}"
                self.logger.error(f"❌ Customer ID {result['stripe_customer_id']} does not exist in Stripe for {email}: {e}")
                
                # If local data shows they have a subscription but customer doesn't exist, it's a major discrepancy
                if result['local_tier'] == 'premium':
                    self.logger.error(f"🚨 Critical discrepancy: {email} shows premium locally but Stripe customer doesn't exist!")
                
            except stripe.error.StripeError as e:
                result['error'] = f"Stripe API error: {e}"
                self.logger.error(f"❌ Stripe API error validating {email}: {e}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error validating subscription for {email}: {e}")
            return {
                'has_local_subscription': False,
                'local_tier': 'free',
                'local_status': 'error',
                'has_active_stripe_subscription': False,
                'stripe_status': None,
                'stripe_tier': 'free',
                'discrepancy_found': False,
                'error': str(e)
            }
    
    def sync_subscription_from_stripe(self, email: str) -> bool:
        """
        Sync local subscription data with Stripe backend.
        Used to fix discrepancies found during validation.
        """
        try:
            validation_result = self.validate_user_subscription_status(email)
            
            # Handle validation errors
            if validation_result['error'] and not validation_result['discrepancy_found']:
                self.logger.error(f"❌ Cannot sync {email} due to validation error: {validation_result['error']}")
                return False
            
            if not validation_result['discrepancy_found']:
                self.logger.info(f"✅ No sync needed for {email} - data is consistent")
                return True
            
            # Handle case where Stripe customer doesn't exist
            if not validation_result.get('stripe_customer_exists', True) or validation_result.get('stripe_customer_deleted', False):
                self.logger.warning(f"🚨 Stripe customer missing/deleted for {email}, resetting to free tier")
                subscription_update = {
                    'tier': 'free',
                    'status': 'cancelled',
                    'stripe_customer_id': None,  # Clear invalid customer ID
                    'stripe_subscription_id': None,  # Clear invalid subscription ID
                    'synced_at': datetime.now(timezone.utc).isoformat(),
                    'sync_note': 'Stripe customer not found or deleted'
                }
                
            # Handle case with active Stripe subscription
            elif validation_result['has_active_stripe_subscription']:
                subscription_update = {
                    'tier': 'premium',
                    'status': 'active',
                    'stripe_customer_id': validation_result['stripe_customer_id'],
                    'stripe_subscription_id': validation_result.get('stripe_subscription_id_actual'),
                    'synced_at': datetime.now(timezone.utc).isoformat(),
                    'sync_note': 'Synced from active Stripe subscription'
                }
                self.logger.info(f"🔄 Syncing {email} to premium/active from Stripe")
                
            # Handle case with no active subscription
            else:
                subscription_update = {
                    'tier': 'free',
                    'status': 'cancelled',
                    'synced_at': datetime.now(timezone.utc).isoformat(),
                    'sync_note': 'No active Stripe subscription found'
                }
                self.logger.info(f"🔄 Syncing {email} to free/cancelled from Stripe")
            
            success = self.user_service.update_subscription(email, subscription_update)
            if success:
                self.logger.info(f"✅ Successfully synced subscription for {email}")
            else:
                self.logger.error(f"❌ Failed to update local subscription for {email}")
            
            return success
            
        except Exception as e:
            self.logger.error(f"❌ Error syncing subscription for {email}: {e}")
            return False


# Global stripe service instance
stripe_service = StripeService()


def get_stripe_service() -> StripeService:
    """Get the Stripe service instance."""
    return stripe_service