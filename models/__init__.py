"""
Database models initialization.
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# Initialize extensions
db = SQLAlchemy()
login_manager = LoginManager()

# Import models after db is defined to avoid circular imports
from models.user import User
from models.subscription import Subscription
from models.scan_history import ScanHistory

__all__ = ['db', 'login_manager', 'User', 'Subscription', 'ScanHistory']
