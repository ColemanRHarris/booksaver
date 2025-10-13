"""
Configuration for BookSaver application.
"""

import os
from pathlib import Path

basedir = Path(__file__).parent


class Config:
    """Base configuration with SQLite database."""

    # Flask
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

    # SQLite Database Configuration
    # Use persistent disk path in production, local instance/ in development
    db_path = os.getenv('DATABASE_PATH', str(basedir / 'instance' / 'booksaver.db'))
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'

    # SQLite optimization for better concurrent access
    SQLALCHEMY_ENGINE_OPTIONS = {
        'connect_args': {
            'timeout': 15,  # Prevents "database locked" errors
            'check_same_thread': False  # Allow SQLite to be used across threads
        }
    }

    # Disable modification tracking (better performance)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Echo SQL queries in development
    SQLALCHEMY_ECHO = os.getenv('FLASK_ENV') != 'production'

    # Flask-Login
    LOGIN_VIEW = 'auth.send_magic_link'

    # Magic Link Configuration
    MAGIC_LINK_EXPIRATION_MINUTES = 15
    MAGIC_LINK_SECRET = os.getenv('MAGIC_LINK_SECRET', SECRET_KEY)

    # Email Configuration (SendGrid or Mailgun)
    MAIL_FROM_EMAIL = os.getenv('MAIL_FROM_EMAIL', 'noreply@booksaver.com')
    MAIL_FROM_NAME = os.getenv('MAIL_FROM_NAME', 'BookSaver')

    # SendGrid
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')

    # Mailgun (alternative)
    MAILGUN_API_KEY = os.getenv('MAILGUN_API_KEY')
    MAILGUN_DOMAIN = os.getenv('MAILGUN_DOMAIN')

    # Stripe Configuration
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

    # Stripe Price IDs (set these after creating products in Stripe)
    STRIPE_PRICE_MONTHLY = os.getenv('STRIPE_PRICE_MONTHLY')  # $2.99/month
    STRIPE_PRICE_ANNUAL = os.getenv('STRIPE_PRICE_ANNUAL')    # $30/year
    STRIPE_PRICE_PER_SCAN = os.getenv('STRIPE_PRICE_PER_SCAN')  # $0.99 per scan

    # Application URLs
    APP_URL = os.getenv('APP_URL', 'http://localhost:5000')


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    TESTING = False

    # Force HTTPS in production
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Get configuration based on FLASK_ENV."""
    env = os.getenv('FLASK_ENV', 'development')
    return config.get(env, config['default'])
