"""
User model for authentication and subscription management.
"""

from datetime import datetime, timedelta
from flask_login import UserMixin
from models import db
import secrets


class User(UserMixin, db.Model):
    """User model with magic link authentication and subscription tracking."""

    __tablename__ = 'users'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Authentication
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    magic_link_token = db.Column(db.String(255), unique=True, nullable=True)
    token_expires = db.Column(db.DateTime, nullable=True)

    # Subscription info
    stripe_customer_id = db.Column(db.String(255), unique=True, nullable=True)
    subscription_status = db.Column(db.String(50), default='free')  # free, active, cancelled, past_due
    subscription_plan = db.Column(db.String(50), nullable=True)  # monthly, annual

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    last_login = db.Column(db.DateTime, nullable=True)

    # Relationship to subscriptions
    subscriptions = db.relationship('Subscription', backref='user', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<User {self.email}>'

    def generate_magic_link_token(self, expiration_minutes=15):
        """Generate a secure magic link token that expires after specified minutes."""
        self.magic_link_token = secrets.token_urlsafe(32)
        self.token_expires = datetime.utcnow() + timedelta(minutes=expiration_minutes)
        return self.magic_link_token

    def verify_magic_link_token(self, token):
        """Verify that the magic link token is valid and not expired."""
        if not self.magic_link_token or not self.token_expires:
            return False

        if self.magic_link_token != token:
            return False

        if datetime.utcnow() > self.token_expires:
            return False

        return True

    def clear_magic_link_token(self):
        """Clear the magic link token after successful login."""
        self.magic_link_token = None
        self.token_expires = None
        self.last_login = datetime.utcnow()

    def can_process_image(self):
        """Check if user can process an image based on their subscription status."""
        # Pro users have unlimited access
        if self.subscription_status == 'active':
            return True, None

        # Free users need to pay per scan
        return False, "Pay $0.99 to scan this image, or upgrade to Pro for unlimited scans!"

    def get_usage_status(self):
        """Get human-readable usage status."""
        if self.subscription_status == 'active':
            plan_display = "Monthly" if self.subscription_plan == 'monthly' else "Annual"
            return f"Unlimited ({plan_display})"

        return "Pay-per-scan"

    def is_pro(self):
        """Check if user is a pro subscriber."""
        return self.subscription_status == 'active'

    @staticmethod
    def find_by_email(email):
        """Find user by email address."""
        return User.query.filter_by(email=email.lower().strip()).first()

    @staticmethod
    def find_by_token(token):
        """Find user by magic link token."""
        return User.query.filter_by(magic_link_token=token).first()
