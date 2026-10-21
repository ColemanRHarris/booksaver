"""
Pytest configuration and fixtures for Booksaver tests.
"""

import pytest
import os
import sys
from datetime import datetime, date

# Add parent directory to path for imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask

from config import Config
from models import db, login_manager, User
from models.subscription import Subscription
from models.book_collection import BookCollection
from models.reading_goal import ReadingGoal
from models.ai_recommendation import AIRecommendation

# Import blueprints
from routes.auth import auth_bp
from routes.billing import billing_bp
from routes.collections import collections_bp
from routes.goals import goals_bp
from routes.dashboard import dashboard_bp


class TestConfig(Config):
    """Test configuration with in-memory database."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_ECHO = False
    WTF_CSRF_ENABLED = False  # Disable CSRF for testing
    SECRET_KEY = 'test-secret-key'
    MAGIC_LINK_SECRET = 'test-magic-link-secret'

    # Disable rate limiting in tests
    RATELIMIT_ENABLED = False

    # Test API keys
    STRIPE_SECRET_KEY = 'sk_test_123'
    STRIPE_PUBLISHABLE_KEY = 'pk_test_123'
    GEMINI_API_KEY = 'test_gemini_key'


@pytest.fixture(scope='function')
def app():
    """Create Flask app with test configuration."""
    # Create app with template folder from parent directory
    import os
    template_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates')
    static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static')

    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    app.config.from_object(TestConfig)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)

    # Configure Flask-Login user_loader
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(billing_bp)
    app.register_blueprint(collections_bp)
    app.register_blueprint(goals_bp)
    app.register_blueprint(dashboard_bp)

    # Register main routes (from main app.py)
    from flask import render_template, redirect, url_for, flash
    from flask_login import login_required, current_user

    @app.route('/')
    def index():
        """Main landing page."""
        return render_template('index.html')

    @app.route('/terms')
    def terms():
        """Terms of service page."""
        return render_template('terms.html')

    @app.route('/privacy')
    def privacy():
        """Privacy policy page."""
        return render_template('privacy.html')

    @app.route('/account')
    @login_required
    def account():
        """User account page with subscription management."""
        from models.subscription import Subscription
        from services.goals_service import GoalsService

        subscription = Subscription.get_active_for_user(current_user.id)
        goal_progress = None
        if current_user.is_pro():
            goal_progress = GoalsService.get_progress(current_user.id)

        return render_template('account.html',
                             user=current_user,
                             subscription=subscription,
                             goal_progress=goal_progress)

    @app.route('/history')
    @login_required
    def history():
        """View scan history (Pro users only)."""
        from models.scan_history import ScanHistory

        if not current_user.is_pro():
            flash('Scan history is only available for Pro subscribers.', 'warning')
            return redirect(url_for('billing.upgrade'))

        scans = ScanHistory.get_history_for_user(current_user.id, limit=50)
        return render_template('history.html', scans=scans)

    # Create tables
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture(scope='function')
def client(app):
    """Create test client."""
    return app.test_client()


@pytest.fixture(scope='function')
def free_user(app):
    """Create a free (non-Pro) user for testing."""
    user = User(
        email='free@example.com',
        subscription_status='free'
    )
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)
    return user


@pytest.fixture(scope='function')
def pro_user(app):
    """Create a Pro user with active subscription for testing."""
    user = User(
        email='pro@example.com',
        subscription_status='active',
        stripe_customer_id='cus_test_pro123'
    )
    db.session.add(user)
    db.session.commit()
    db.session.refresh(user)

    # Create active subscription
    subscription = Subscription(
        user_id=user.id,
        stripe_subscription_id='sub_test_pro123',
        stripe_price_id='price_test_monthly',
        status='active',
        plan='monthly',
        current_period_start=datetime.now(),
        current_period_end=datetime.now()
    )
    db.session.add(subscription)
    db.session.commit()

    return user


@pytest.fixture(scope='function')
def auth_client(client, pro_user):
    """Create authenticated test client (logged in as Pro user)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(pro_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture(scope='function')
def free_auth_client(client, free_user):
    """Create authenticated test client (logged in as free user)."""
    with client.session_transaction() as sess:
        sess['_user_id'] = str(free_user.id)
        sess['_fresh'] = True
    return client


@pytest.fixture(scope='function')
def sample_book_data():
    """Sample book data for testing."""
    return {
        'title': 'Project Hail Mary',
        'authors': ['Andy Weir'],
        'isbn': '9780062839649',
        'thumbnail': 'https://example.com/cover.jpg',
        'published_date': '2021',
        'categories': ['Science Fiction', 'Fiction']
    }


@pytest.fixture(scope='function')
def sample_book_data_2():
    """Second sample book for testing duplicates."""
    return {
        'title': 'The Martian',
        'authors': ['Andy Weir'],
        'isbn': '9780553418026',
        'thumbnail': 'https://example.com/martian.jpg',
        'published_date': '2014',
        'categories': ['Science Fiction', 'Fiction', 'Adventure']
    }


@pytest.fixture(scope='function')
def create_collection_book(app, pro_user):
    """Factory fixture to create books in collection."""
    def _create_book(title='Test Book', authors=None, isbn=None, shelf='want_to_read', read_status='unread', date_read=None, genres=None):
        book = BookCollection(
            user_id=pro_user.id,
            title=title,
            isbn=isbn,
            shelf=shelf,
            read_status=read_status,
            date_read=date_read
        )
        book.authors = authors or ['Test Author']
        book.genres = genres or []

        db.session.add(book)
        db.session.commit()
        db.session.refresh(book)
        return book

    return _create_book


@pytest.fixture(scope='function')
def create_reading_goal(app, pro_user):
    """Factory fixture to create reading goals."""
    def _create_goal(year=2026, target_count=24):
        goal = ReadingGoal(
            user_id=pro_user.id,
            year=year,
            target_count=target_count
        )
        db.session.add(goal)
        db.session.commit()
        db.session.refresh(goal)
        return goal

    return _create_goal
