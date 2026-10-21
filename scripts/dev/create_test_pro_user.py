"""
Manual dev script, not part of CI or the pytest suite.
Create a test Pro user account for local testing.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from app import app
from models import db
from models.user import User
from models.subscription import Subscription
from datetime import datetime, timedelta

def create_test_pro_user():
    """Create a test Pro user with active subscription."""
    with app.app_context():
        # Check if test user already exists
        test_email = 'testpro@example.com'
        existing_user = User.query.filter_by(email=test_email).first()

        if existing_user:
            print(f"✓ Test Pro user already exists: {test_email}")
            print(f"  User ID: {existing_user.id}")
            print(f"  Subscription Status: {existing_user.subscription_status}")
            return existing_user

        # Create new Pro user
        user = User(
            email=test_email,
            subscription_status='active',
            stripe_customer_id='cus_test_local_pro'
        )
        db.session.add(user)
        db.session.commit()

        # Create active subscription
        subscription = Subscription(
            user_id=user.id,
            stripe_subscription_id='sub_test_local_pro',
            stripe_price_id='price_test_monthly',
            status='active',
            plan='monthly',
            current_period_start=datetime.now(),
            current_period_end=datetime.now() + timedelta(days=30)
        )
        db.session.add(subscription)
        db.session.commit()

        print(f"✓ Created test Pro user successfully!")
        print(f"  Email: {test_email}")
        print(f"  User ID: {user.id}")
        print(f"  Subscription Status: {user.subscription_status}")
        print(f"\nTo login, request a magic link for: {test_email}")

        return user

if __name__ == '__main__':
    create_test_pro_user()
