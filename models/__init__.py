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
from models.genre import Genre
from models.author import Author
from models.popular_book import PopularBook
from models.seo_page import SEOPage
from models.book_collection import BookCollection
from models.reading_goal import ReadingGoal
from models.ai_recommendation import AIRecommendation

__all__ = ['db', 'login_manager', 'User', 'Subscription', 'ScanHistory', 'Genre', 'Author', 'PopularBook', 'SEOPage', 'BookCollection', 'ReadingGoal', 'AIRecommendation']
