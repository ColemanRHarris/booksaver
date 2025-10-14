"""
Billing routes for Stripe subscription management.
"""

import stripe
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required, current_user
from datetime import datetime
from models import db
from models.subscription import Subscription

billing_bp = Blueprint('billing', __name__, url_prefix='/billing')


@billing_bp.route('/upgrade')
@login_required
def upgrade():
    """Show upgrade page with pricing options."""
    # Check if user already has an active subscription
    active_sub = Subscription.get_active_for_user(current_user.id)
    if active_sub:
        flash('You already have an active subscription.', 'info')
        return redirect(url_for('account'))

    # Get pricing from config
    monthly_price = current_app.config.get('STRIPE_PRICE_MONTHLY')
    annual_price = current_app.config.get('STRIPE_PRICE_ANNUAL')

    return render_template('billing/upgrade.html',
                         monthly_price_id=monthly_price,
                         annual_price_id=annual_price)


@billing_bp.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    """Create a Stripe Checkout session for subscription."""
    try:
        # Initialize Stripe
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']

        # Get the price ID from the request
        price_id = request.form.get('price_id')
        if not price_id:
            flash('Invalid pricing option selected.', 'error')
            return redirect(url_for('billing.upgrade'))

        # Ensure user has a valid Stripe customer ID
        customer_id = current_user.stripe_customer_id

        # Validate existing customer ID or create/reuse customer
        if customer_id:
            try:
                # Verify the customer still exists in Stripe
                stripe.Customer.retrieve(customer_id)
            except stripe.error.InvalidRequestError:
                # Customer was deleted in Stripe, clear the invalid ID
                current_app.logger.warning(f"Customer {customer_id} no longer exists in Stripe, clearing")
                current_user.stripe_customer_id = None
                customer_id = None
                db.session.commit()

        if not customer_id:
            # Check if a Stripe customer already exists with this email
            existing_customers = stripe.Customer.list(email=current_user.email, limit=1)

            if existing_customers.data:
                # Reuse existing customer
                customer = existing_customers.data[0]
                current_user.stripe_customer_id = customer.id
                customer_id = customer.id
                db.session.commit()
                current_app.logger.info(f"Found existing Stripe customer for {current_user.email}: {customer.id}")
            else:
                # Create new customer
                customer = stripe.Customer.create(
                    email=current_user.email,
                    metadata={'user_id': current_user.id}
                )
                current_user.stripe_customer_id = customer.id
                customer_id = customer.id
                db.session.commit()
                current_app.logger.info(f"Created Stripe customer for {current_user.email}: {customer.id}")

        # Create Checkout Session
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('billing.success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('billing.cancel', _external=True),
            allow_promotion_codes=True,
            metadata={
                'user_id': current_user.id
            }
        )

        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        flash('Payment processing error. Please try again.', 'error')
        return redirect(url_for('billing.upgrade'))


@billing_bp.route('/pay-per-scan', methods=['POST'])
@login_required
def pay_per_scan():
    """Create a one-time payment Checkout session for a single scan."""
    try:
        # Initialize Stripe
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']

        # Get the per-scan price ID
        price_id = current_app.config.get('STRIPE_PRICE_PER_SCAN')
        if not price_id:
            flash('Per-scan payment not configured. Please contact support.', 'error')
            return redirect(url_for('index'))

        # Ensure user has a valid Stripe customer ID
        customer_id = current_user.stripe_customer_id

        # Validate existing customer ID or create/reuse customer
        if customer_id:
            try:
                # Verify the customer still exists in Stripe
                stripe.Customer.retrieve(customer_id)
            except stripe.error.InvalidRequestError:
                # Customer was deleted in Stripe, clear the invalid ID
                current_app.logger.warning(f"Customer {customer_id} no longer exists in Stripe, clearing")
                current_user.stripe_customer_id = None
                customer_id = None
                db.session.commit()

        if not customer_id:
            # Check if a Stripe customer already exists with this email
            existing_customers = stripe.Customer.list(email=current_user.email, limit=1)

            if existing_customers.data:
                # Reuse existing customer
                customer = existing_customers.data[0]
                current_user.stripe_customer_id = customer.id
                customer_id = customer.id
                db.session.commit()
                current_app.logger.info(f"Found existing Stripe customer for {current_user.email}: {customer.id}")
            else:
                # Create new customer
                customer = stripe.Customer.create(
                    email=current_user.email,
                    metadata={'user_id': current_user.id}
                )
                current_user.stripe_customer_id = customer.id
                customer_id = customer.id
                db.session.commit()
                current_app.logger.info(f"Created Stripe customer for {current_user.email}: {customer.id}")

        # Create Checkout Session for one-time payment
        session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='payment',  # One-time payment, not subscription
            success_url=url_for('billing.scan_payment_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('index', _external=True),
            metadata={
                'user_id': current_user.id,
                'payment_type': 'per_scan'
            }
        )

        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        current_app.logger.error(f"Stripe error: {e}")
        flash('Payment processing error. Please try again.', 'error')
        return redirect(url_for('index'))


@billing_bp.route('/scan-payment-success')
@login_required
def scan_payment_success():
    """Handle successful per-scan payment and redirect to image upload."""
    session_id = request.args.get('session_id')

    if session_id:
        try:
            stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
            session = stripe.checkout.Session.retrieve(session_id)

            current_app.logger.info(f"Per-scan checkout session retrieved: payment_status={session.payment_status}")

            if session.payment_status == 'paid':
                # Payment successful - allow one scan
                flash('Payment successful! You can now scan your image.', 'success')
                # Store session ID in the flash message to verify on upload
                return render_template('billing/scan_payment_success.html', session_id=session_id)
            else:
                flash('Payment is being processed. Please try again in a moment.', 'info')

        except Exception as e:
            current_app.logger.error(f"Error in scan_payment_success route: {type(e).__name__}: {e}")
            flash('Payment confirmed! You can now scan your image.', 'success')

    return render_template('billing/scan_payment_success.html')


@billing_bp.route('/success')
@login_required
def success():
    """Handle successful payment and immediately update subscription status."""
    session_id = request.args.get('session_id')

    if session_id:
        try:
            stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
            session = stripe.checkout.Session.retrieve(
                session_id,
                expand=['subscription', 'subscription.items', 'subscription.items.data.price']
            )

            current_app.logger.info(f"Checkout session retrieved: payment_status={session.payment_status}")

            if session.payment_status == 'paid' and session.subscription:
                # Get the subscription object
                subscription = session.subscription
                current_app.logger.info(f"Subscription object: {subscription.id}, status={subscription.status}")

                # Determine plan type from price ID
                try:
                    price_id = subscription.items.data[0].price.id
                except (AttributeError, IndexError, KeyError) as e:
                    current_app.logger.error(f"Error extracting price_id: {e}")
                    price_id = None

                if price_id == current_app.config.get('STRIPE_PRICE_MONTHLY'):
                    plan = 'monthly'
                elif price_id == current_app.config.get('STRIPE_PRICE_ANNUAL'):
                    plan = 'annual'
                else:
                    plan = 'unknown'

                # CRITICAL: Update user subscription status immediately (top priority)
                current_user.subscription_status = subscription.status
                current_user.subscription_plan = plan
                db.session.commit()  # Commit this first to ensure it persists

                current_app.logger.info(f"Updated user subscription status: {current_user.subscription_status}, plan: {plan}")

                # BEST EFFORT: Try to create detailed subscription record
                try:
                    existing_sub = Subscription.find_by_stripe_id(subscription.id)
                    if not existing_sub:
                        # Safely extract timestamp fields
                        period_start = None
                        period_end = None
                        cancel_at_period_end = False

                        try:
                            if hasattr(subscription, 'current_period_start') and subscription.current_period_start:
                                period_start = datetime.fromtimestamp(subscription.current_period_start)
                        except Exception as e:
                            current_app.logger.warning(f"Could not parse current_period_start: {e}")

                        try:
                            if hasattr(subscription, 'current_period_end') and subscription.current_period_end:
                                period_end = datetime.fromtimestamp(subscription.current_period_end)
                        except Exception as e:
                            current_app.logger.warning(f"Could not parse current_period_end: {e}")

                        try:
                            cancel_at_period_end = getattr(subscription, 'cancel_at_period_end', False)
                        except Exception as e:
                            current_app.logger.warning(f"Could not read cancel_at_period_end: {e}")

                        new_subscription = Subscription(
                            user_id=current_user.id,
                            stripe_subscription_id=subscription.id,
                            stripe_price_id=price_id or 'unknown',
                            status=subscription.status,
                            plan=plan,
                            current_period_start=period_start,
                            current_period_end=period_end,
                            cancel_at_period_end=cancel_at_period_end
                        )
                        db.session.add(new_subscription)
                        db.session.commit()
                        current_app.logger.info(f"Created subscription record for {subscription.id}")
                except Exception as e:
                    # Don't fail if detailed record creation fails
                    current_app.logger.error(f"Error creating subscription record: {e}")
                    db.session.rollback()

                flash('Subscription activated successfully! Welcome to Pro!', 'success')
            else:
                flash('Payment is being processed. Your subscription will activate shortly.', 'info')

        except Exception as e:
            current_app.logger.error(f"Error in success route: {type(e).__name__}: {e}")
            import traceback
            current_app.logger.error(f"Traceback: {traceback.format_exc()}")
            flash('Subscription confirmed! If you don\'t see Pro status, please refresh the page.', 'success')

    return render_template('billing/success.html')


@billing_bp.route('/cancel')
@login_required
def cancel():
    """Handle cancelled payment."""
    flash('Subscription upgrade was cancelled.', 'info')
    return render_template('billing/cancel.html')


@billing_bp.route('/portal')
@login_required
def customer_portal():
    """Redirect to Stripe Customer Portal for subscription management."""
    try:
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']

        if not current_user.stripe_customer_id:
            flash('No subscription found.', 'error')
            return redirect(url_for('billing.upgrade'))

        # Validate customer exists in Stripe
        try:
            stripe.Customer.retrieve(current_user.stripe_customer_id)
        except stripe.error.InvalidRequestError:
            # Customer was deleted in Stripe
            current_app.logger.warning(f"Customer {current_user.stripe_customer_id} no longer exists")
            current_user.stripe_customer_id = None
            db.session.commit()
            flash('Your subscription data is out of sync. Please subscribe again.', 'error')
            return redirect(url_for('billing.upgrade'))

        # Create portal session
        session = stripe.billing_portal.Session.create(
            customer=current_user.stripe_customer_id,
            return_url=url_for('account', _external=True)
        )

        return redirect(session.url, code=303)

    except stripe.error.StripeError as e:
        current_app.logger.error(f"Portal error: {e}")
        flash('Unable to access subscription management. Please try again.', 'error')
        return redirect(url_for('account'))


@billing_bp.route('/webhook', methods=['POST'])
def webhook():
    """Handle Stripe webhook events."""
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get('Stripe-Signature')

    try:
        stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
        webhook_secret = current_app.config['STRIPE_WEBHOOK_SECRET']

        # Verify webhook signature
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )

        current_app.logger.info(f"Received Stripe webhook: {event['type']}")

        # Handle different event types
        if event['type'] == 'customer.subscription.created':
            handle_subscription_created(event['data']['object'])
        elif event['type'] == 'customer.subscription.updated':
            handle_subscription_updated(event['data']['object'])
        elif event['type'] == 'customer.subscription.deleted':
            handle_subscription_deleted(event['data']['object'])
        elif event['type'] == 'invoice.payment_succeeded':
            handle_payment_succeeded(event['data']['object'])
        elif event['type'] == 'invoice.payment_failed':
            handle_payment_failed(event['data']['object'])

        return jsonify({'status': 'success'}), 200

    except ValueError as e:
        current_app.logger.error(f"Invalid webhook payload: {e}")
        return jsonify({'error': 'Invalid payload'}), 400
    except stripe.error.SignatureVerificationError as e:
        current_app.logger.error(f"Invalid webhook signature: {e}")
        return jsonify({'error': 'Invalid signature'}), 400


def handle_subscription_created(subscription):
    """Handle subscription.created event."""
    customer_id = subscription['customer']
    subscription_id = subscription['id']
    status = subscription['status']

    # Find user by Stripe customer ID
    from models.user import User
    user = User.query.filter_by(stripe_customer_id=customer_id).first()
    if not user:
        current_app.logger.error(f"User not found for customer {customer_id}")
        return

    # Check if subscription already exists (prevents duplicates from success page)
    existing_sub = Subscription.find_by_stripe_id(subscription_id)
    if existing_sub:
        current_app.logger.info(f"Subscription {subscription_id} already exists, updating instead")
        # Update existing subscription
        existing_sub.status = status
        existing_sub.current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
        existing_sub.current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
        existing_sub.cancel_at_period_end = subscription['cancel_at_period_end']
        db.session.commit()
        return

    # Determine plan type
    price_id = subscription['items']['data'][0]['price']['id']
    if price_id == current_app.config.get('STRIPE_PRICE_MONTHLY'):
        plan = 'monthly'
    elif price_id == current_app.config.get('STRIPE_PRICE_ANNUAL'):
        plan = 'annual'
    else:
        plan = 'unknown'

    # Create subscription record
    new_subscription = Subscription(
        user_id=user.id,
        stripe_subscription_id=subscription_id,
        stripe_price_id=price_id,
        status=status,
        plan=plan,
        current_period_start=datetime.fromtimestamp(subscription['current_period_start']),
        current_period_end=datetime.fromtimestamp(subscription['current_period_end']),
        cancel_at_period_end=subscription['cancel_at_period_end']
    )

    # Update user subscription status
    user.subscription_status = status
    user.subscription_plan = plan

    db.session.add(new_subscription)
    db.session.commit()

    current_app.logger.info(f"Subscription created for user {user.email}: {subscription_id}")


def handle_subscription_updated(subscription):
    """Handle subscription.updated event."""
    subscription_id = subscription['id']

    # Find subscription record
    sub_record = Subscription.find_by_stripe_id(subscription_id)
    if not sub_record:
        current_app.logger.error(f"Subscription record not found: {subscription_id}")
        return

    # Update subscription details
    sub_record.status = subscription['status']
    sub_record.current_period_start = datetime.fromtimestamp(subscription['current_period_start'])
    sub_record.current_period_end = datetime.fromtimestamp(subscription['current_period_end'])
    sub_record.cancel_at_period_end = subscription['cancel_at_period_end']

    if subscription.get('canceled_at'):
        sub_record.canceled_at = datetime.fromtimestamp(subscription['canceled_at'])

    # Update user status
    sub_record.user.subscription_status = subscription['status']

    db.session.commit()

    current_app.logger.info(f"Subscription updated: {subscription_id} - status: {subscription['status']}")


def handle_subscription_deleted(subscription):
    """Handle subscription.deleted event."""
    subscription_id = subscription['id']

    # Find subscription record
    sub_record = Subscription.find_by_stripe_id(subscription_id)
    if not sub_record:
        current_app.logger.error(f"Subscription record not found: {subscription_id}")
        return

    # Update status to canceled
    sub_record.status = 'canceled'
    sub_record.canceled_at = datetime.utcnow()

    # Update user status
    sub_record.user.subscription_status = 'free'
    sub_record.user.subscription_plan = None

    db.session.commit()

    current_app.logger.info(f"Subscription deleted: {subscription_id}")


def handle_payment_succeeded(invoice):
    """Handle invoice.payment_succeeded event."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return

    current_app.logger.info(f"Payment succeeded for subscription: {subscription_id}")


def handle_payment_failed(invoice):
    """Handle invoice.payment_failed event."""
    subscription_id = invoice.get('subscription')
    if not subscription_id:
        return

    # Find subscription record
    sub_record = Subscription.find_by_stripe_id(subscription_id)
    if sub_record:
        sub_record.status = 'past_due'
        sub_record.user.subscription_status = 'past_due'
        db.session.commit()

    current_app.logger.warning(f"Payment failed for subscription: {subscription_id}")
