"""
Subscription routes for Stripe integration.
"""

import os
from flask import request, render_template, redirect, url_for, session, flash, jsonify, current_app, g

from services.stripe_service import get_stripe_service
from services.user_service import get_user_service


def register_subscription_routes(app, limiter, require_auth):
    """Register subscription routes."""
    
    stripe_service = get_stripe_service()
    user_service = get_user_service()
    
    @app.route('/subscribe')
    @require_auth
    def subscribe():
        """Subscription selection page with Stripe backend validation."""
        try:
            email = session.get('user_email')
            user_data = user_service.get_user(email)
            subscription_data = user_service.get_subscription(email)
            
            # Validate subscription status against Stripe backend
            validation_result = stripe_service.validate_user_subscription_status(email)
            
            # If there's an active Stripe subscription, sync and redirect
            if validation_result['has_active_stripe_subscription']:
                if validation_result['discrepancy_found']:
                    current_app.logger.info(f"\ud83d\udd04 Syncing subscription data for {email} from Stripe")
                    stripe_service.sync_subscription_from_stripe(email)
                
                flash("You already have an active Premium subscription!", "info")
                return redirect(url_for('account_dashboard'))
            
            # If local data shows premium but Stripe doesn't, sync to fix discrepancy
            elif validation_result['discrepancy_found']:
                current_app.logger.info(f"\ud83d\udd04 Fixing subscription discrepancy for {email}")
                stripe_service.sync_subscription_from_stripe(email)
                # Refresh subscription data after sync
                subscription_data = user_service.get_subscription(email)
            
            return render_template('subscription/subscribe.html',
                                 user=user_data,
                                 subscription=subscription_data)
            
        except Exception as e:
            current_app.logger.error(f"❌ Subscribe page error: {e}")
            flash("Error loading subscription page.", "error")
            return redirect(url_for('account_dashboard'))
    
    @app.route('/create-checkout-session', methods=['POST'])
    @limiter.limit("5 per minute")
    @require_auth
    def create_checkout_session():
        """Create Stripe checkout session with improved error handling."""
        try:
            email = session.get('user_email')
            plan = request.form.get('plan')  # 'monthly' or 'yearly'
            
            if not email:
                current_app.logger.error("No user email in session")
                flash("Session expired. Please log in again.", "error")
                return redirect(url_for('login'))
            
            if plan not in ['monthly', 'yearly']:
                flash("Invalid subscription plan selected.", "error")
                return redirect(url_for('subscribe'))
            
            # Validate against Stripe backend before creating checkout
            validation_result = stripe_service.validate_user_subscription_status(email)
            
            # Block checkout if user has active Stripe subscription
            if validation_result['has_active_stripe_subscription']:
                if validation_result['discrepancy_found']:
                    current_app.logger.info(f"\ud83d\udd04 Syncing subscription for {email} before blocking checkout")
                    stripe_service.sync_subscription_from_stripe(email)
                
                flash("You already have an active Premium subscription! Redirecting to your account.", "info")
                return redirect(url_for('account_dashboard'))
            
            # If validation found discrepancies but no active subscription, fix local data
            elif validation_result['discrepancy_found']:
                current_app.logger.info(f"\ud83d\udd04 Fixing subscription data for {email} before checkout")
                stripe_service.sync_subscription_from_stripe(email)
            
            # Additional local check after potential sync
            subscription_data = user_service.get_subscription(email)
            if subscription_data and subscription_data.get('tier') == 'premium' and subscription_data.get('status') == 'active':
                flash("You already have an active Premium subscription!", "info")
                return redirect(url_for('account_dashboard'))
            
            # Create checkout session
            success_url = url_for('subscription_success', _external=True)
            cancel_url = url_for('subscribe', _external=True)
            
            checkout_result = stripe_service.create_checkout_session(
                email=email,
                plan=plan,
                success_url=success_url,
                cancel_url=cancel_url
            )
            
            # Handle different response types
            if isinstance(checkout_result, dict):
                if 'url' in checkout_result:
                    # Success - redirect to Stripe
                    current_app.logger.info(f"\ud83d\udcb3 Redirecting {email} to Stripe checkout for {plan} plan")
                    return redirect(checkout_result['url'])
                elif 'error' in checkout_result:
                    # Specific error message from Stripe service
                    flash(checkout_result['error'], "error")
                    return redirect(url_for('subscribe'))
            
            # Generic failure
            flash("Unable to create checkout session. Please try again.", "error")
            return redirect(url_for('subscribe'))
                
        except Exception as e:
            current_app.logger.error(f"❌ Unexpected checkout session error: {e}")
            flash("An unexpected error occurred. Please try again or contact support.", "error")
            return redirect(url_for('subscribe'))
    
    @app.route('/subscription/success')
    @require_auth
    def subscription_success():
        """Subscription success page."""
        try:
            flash("Welcome to Premium! Your subscription is now active.", "success")
            return render_template('subscription/success.html')
        except Exception as e:
            current_app.logger.error(f"❌ Subscription success page error: {e}")
            return redirect(url_for('account_dashboard'))
    
    @app.route('/manage-subscription')
    @require_auth
    def manage_subscription():
        """Redirect to Stripe billing portal with improved error handling."""
        try:
            email = session.get('user_email')
            
            if not email:
                current_app.logger.error("No user email in session for billing portal")
                flash("Session expired. Please log in again.", "error")
                return redirect(url_for('login'))
            
            # Verify user has subscription
            subscription_data = user_service.get_subscription(email)
            if not subscription_data or not subscription_data.get('stripe_customer_id'):
                flash("No subscription found. Please subscribe first.", "error")
                return redirect(url_for('subscribe'))
            
            return_url = url_for('account_dashboard', _external=True)
            
            portal_url = stripe_service.create_billing_portal_session(email, return_url)
            
            if portal_url:
                current_app.logger.info(f"\ud83c\udfe6 Redirecting {email} to Stripe billing portal")
                return redirect(portal_url)
            else:
                flash("Unable to access subscription management. Please try again or contact support.", "error")
                return redirect(url_for('account_dashboard'))
                
        except Exception as e:
            current_app.logger.error(f"❌ Unexpected billing portal error: {e}")
            flash("An unexpected error occurred accessing subscription management.", "error")
            return redirect(url_for('account_dashboard'))
    
    @app.route('/stripe/webhook', methods=['POST'])
    @limiter.exempt
    def stripe_webhook():
        """Handle Stripe webhook events with improved error handling."""
        try:
            payload = request.get_data()
            sig_header = request.headers.get('Stripe-Signature')
            
            if not payload:
                current_app.logger.error("❌ Empty webhook payload received")
                return 'Empty payload', 400
            
            if not sig_header:
                current_app.logger.error("❌ Missing Stripe signature header")
                return 'Missing signature', 400
            
            current_app.logger.debug(f"\ud83d\udcee Webhook payload size: {len(payload)} bytes")
            
            # Handle webhook
            success = stripe_service.handle_webhook(payload, sig_header)
            
            if success:
                return 'Success', 200
            else:
                current_app.logger.warning("⚠️ Webhook processing failed but returning 200 to prevent retries")
                return 'Webhook processed with issues', 200  # Return 200 to prevent Stripe retries
                
        except Exception as e:
            current_app.logger.error(f"❌ Unexpected webhook error: {e}")
            return 'Internal server error', 500
    
    @app.route('/api/subscription/status')
    @require_auth
    def subscription_status_api():
        """Get current subscription status (API endpoint)."""
        try:
            email = session.get('user_email')
            subscription_data = user_service.get_subscription(email)
            daily_usage = user_service.get_daily_usage(email)
            
            return jsonify({
                'tier': subscription_data.get('tier', 'free'),
                'status': subscription_data.get('status', 'active'),
                'daily_usage': daily_usage,
                'can_scan': user_service.can_scan(email)
            })
            
        except Exception as e:
            current_app.logger.error(f"❌ Subscription status API error: {e}")
            return jsonify({'error': 'Failed to get subscription status'}), 500
    
    @app.route('/api/subscription/validate-and-sync', methods=['POST'])
    @limiter.limit("3 per minute")
    @require_auth
    def validate_and_sync_subscription():
        """Validate subscription against Stripe and sync if needed."""
        try:
            email = session.get('user_email')
            
            if not email:
                return jsonify({'error': 'No user session'}), 401
            
            # Validate against Stripe
            validation_result = stripe_service.validate_user_subscription_status(email)
            
            sync_performed = False
            if validation_result['discrepancy_found']:
                current_app.logger.info(f"🔄 Manual sync requested for {email}")
                sync_success = stripe_service.sync_subscription_from_stripe(email)
                sync_performed = True
                
                if sync_success:
                    # Get updated data after sync
                    updated_subscription = user_service.get_subscription(email)
                    validation_result['sync_success'] = True
                    validation_result['updated_local_tier'] = updated_subscription.get('tier', 'free') if updated_subscription else 'free'
                    validation_result['updated_local_status'] = updated_subscription.get('status', 'none') if updated_subscription else 'none'
                else:
                    validation_result['sync_success'] = False
            
            response_data = {
                'validation_result': validation_result,
                'sync_performed': sync_performed,
                'message': self._get_validation_message(validation_result, sync_performed)
            }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            current_app.logger.error(f"❌ Validation and sync API error: {e}")
            return jsonify({'error': 'Failed to validate and sync subscription'}), 500
    
    def _get_validation_message(self, validation_result, sync_performed):
        """Get human-readable message for validation result."""
        if validation_result.get('error'):
            return f"Error validating subscription: {validation_result['error']}"
        
        # Handle customer existence issues
        if not validation_result.get('stripe_customer_exists', True):
            if sync_performed:
                return "Stripe customer account not found. Local subscription data has been reset to free tier."
            else:
                return "Stripe customer account not found."
        
        if validation_result.get('stripe_customer_deleted', False):
            if sync_performed:
                return "Stripe customer account was deleted. Local subscription data has been reset to free tier."
            else:
                return "Stripe customer account was deleted."
        
        if validation_result['has_active_stripe_subscription']:
            if sync_performed:
                return "Active subscription found in Stripe. Local data has been synchronized."
            else:
                return "Active subscription confirmed in Stripe. No sync needed."
        else:
            if sync_performed:
                return "No active subscription in Stripe. Local data has been updated to free tier."
            else:
                return "No active subscription found in Stripe."
    
    @app.route('/api/subscription/validate', methods=['GET'])
    @limiter.limit("10 per minute")  
    @require_auth
    def validate_subscription_status():
        """Get detailed subscription validation without syncing."""
        try:
            email = session.get('user_email')
            
            if not email:
                return jsonify({'error': 'No user session'}), 401
            
            # Validate against Stripe without syncing
            validation_result = stripe_service.validate_user_subscription_status(email)
            
            # Add human-readable status
            if validation_result.get('error'):
                status = 'error'
                message = f"Validation error: {validation_result['error']}"
            elif not validation_result.get('stripe_customer_exists', True):
                status = 'customer_missing'
                message = "Stripe customer account does not exist"
            elif validation_result.get('stripe_customer_deleted', False):
                status = 'customer_deleted'
                message = "Stripe customer account was deleted"
            elif validation_result['has_active_stripe_subscription']:
                if validation_result['discrepancy_found']:
                    status = 'active_with_discrepancy'
                    message = "Active subscription found but local data needs sync"
                else:
                    status = 'active_synced'
                    message = "Active subscription confirmed and synced"
            else:
                if validation_result['discrepancy_found']:
                    status = 'inactive_with_discrepancy'
                    message = "No active subscription but local data shows premium"
                else:
                    status = 'inactive_synced'
                    message = "No active subscription, data is consistent"
            
            response_data = {
                'status': status,
                'message': message,
                'validation_details': validation_result,
                'requires_sync': validation_result['discrepancy_found']
            }
            
            return jsonify(response_data), 200
            
        except Exception as e:
            current_app.logger.error(f"❌ Subscription validation API error: {e}")
            return jsonify({'error': 'Failed to validate subscription'}), 500
    
    @app.route('/api/stripe/check-email', methods=['POST'])
    @limiter.limit("20 per minute")
    @require_auth
    def check_email_in_stripe():
        """Check if email exists in Stripe customer database."""
        try:
            data = request.get_json()
            if not data or 'email' not in data:
                return jsonify({'error': 'Email is required'}), 400
            
            email = data['email'].lower().strip()
            current_user_email = session.get('user_email')
            
            # Only allow checking own email or admin users could check others (if you have admin)
            if email != current_user_email.lower():
                return jsonify({'error': 'Can only check own email'}), 403
            
            # Search for customer in Stripe
            existing_customer = stripe_service.find_existing_stripe_customer(email)
            
            if not existing_customer:
                return jsonify({
                    'exists': False,
                    'message': f'No Stripe customer found for {email}',
                    'customer_data': None
                }), 200
            
            # Customer found
            response_data = {
                'exists': True,
                'customer_data': {
                    'id': existing_customer['id'],
                    'email': existing_customer['email'],
                    'deleted': existing_customer['deleted'],
                    'total_found': existing_customer['total_found'],
                    'has_deleted': existing_customer['has_deleted']
                }
            }
            
            if existing_customer['deleted']:
                response_data['message'] = f'Found {existing_customer["has_deleted"]} deleted customer(s) for {email}, but no active customers'
                response_data['exists'] = False  # No active customer
            else:
                response_data['message'] = f'Found active Stripe customer for {email}'
                if existing_customer['total_found'] > 1:
                    response_data['message'] += f' ({existing_customer["total_found"]} total customers found)'
            
            return jsonify(response_data), 200
            
        except Exception as e:
            current_app.logger.error(f"❌ Check email API error: {e}")
            return jsonify({'error': 'Failed to check email in Stripe'}), 500