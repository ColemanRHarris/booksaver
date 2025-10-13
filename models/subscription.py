"""
Subscription model for Stripe subscription data.
"""

from datetime import datetime
from models import db


class Subscription(db.Model):
    """Subscription model to track Stripe subscriptions."""

    __tablename__ = 'subscriptions'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Foreign key to user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Stripe data
    stripe_subscription_id = db.Column(db.String(255), unique=True, nullable=False)
    stripe_price_id = db.Column(db.String(255), nullable=False)  # Store the specific price ID
    status = db.Column(db.String(50), nullable=False)  # active, canceled, past_due, etc.
    plan = db.Column(db.String(50), nullable=False)  # monthly, annual

    # Subscription period
    current_period_start = db.Column(db.DateTime, nullable=True)
    current_period_end = db.Column(db.DateTime, nullable=True)

    # Cancellation info
    cancel_at_period_end = db.Column(db.Boolean, default=False)
    canceled_at = db.Column(db.DateTime, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Subscription {self.stripe_subscription_id} - {self.status}>'

    def is_active(self):
        """Check if subscription is currently active."""
        return self.status in ['active', 'trialing']

    def is_cancelled(self):
        """Check if subscription is cancelled or will be cancelled."""
        return self.status == 'canceled' or self.cancel_at_period_end

    def get_plan_display(self):
        """Get human-readable plan name."""
        if self.plan == 'monthly':
            return 'Pro Monthly ($2.99/month)'
        elif self.plan == 'annual':
            return 'Pro Annual ($30/year)'
        return 'Unknown Plan'

    def get_status_display(self):
        """Get human-readable status."""
        status_map = {
            'active': 'Active',
            'trialing': 'Trial',
            'canceled': 'Cancelled',
            'past_due': 'Past Due',
            'unpaid': 'Unpaid',
            'incomplete': 'Incomplete',
            'incomplete_expired': 'Expired'
        }
        return status_map.get(self.status, self.status.capitalize())

    def days_until_renewal(self):
        """Calculate days until next renewal."""
        if not self.current_period_end:
            return None

        delta = self.current_period_end - datetime.utcnow()
        return max(0, delta.days)

    @staticmethod
    def find_by_stripe_id(stripe_subscription_id):
        """Find subscription by Stripe subscription ID."""
        return Subscription.query.filter_by(stripe_subscription_id=stripe_subscription_id).first()

    @staticmethod
    def get_active_for_user(user_id):
        """Get active subscription for a user."""
        return Subscription.query.filter_by(
            user_id=user_id,
            status='active'
        ).first()
