"""
Scan History model to store book scan results for Pro users.
"""

from datetime import datetime
from models import db
import json


class ScanHistory(db.Model):
    """Model to store scan history for Pro users."""

    __tablename__ = 'scan_history'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Foreign key to user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    # Scan metadata
    scan_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    books_count = db.Column(db.Integer, default=0)

    # Store books as JSON
    books_json = db.Column(db.Text, nullable=False)  # JSON string of book list

    # Optional: store image URL/path if we save uploaded images
    image_url = db.Column(db.String(500), nullable=True)

    # Search query used (optional) - renamed from 'query' to avoid conflict with SQLAlchemy's query attribute
    search_query = db.Column(db.String(255), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<ScanHistory {self.id} - {self.books_count} books - {self.scan_date}>'

    @property
    def books(self):
        """Get books list from JSON string."""
        try:
            return json.loads(self.books_json)
        except (json.JSONDecodeError, TypeError):
            return []

    @books.setter
    def books(self, books_list):
        """Set books list as JSON string."""
        self.books_json = json.dumps(books_list)
        self.books_count = len(books_list) if books_list else 0

    def get_formatted_date(self):
        """Get human-readable scan date."""
        return self.scan_date.strftime('%B %d, %Y at %I:%M %p')

    def get_relative_date(self):
        """Get relative time (e.g., '2 hours ago')."""
        now = datetime.utcnow()
        delta = now - self.scan_date

        if delta.days > 365:
            years = delta.days // 365
            return f"{years} year{'s' if years > 1 else ''} ago"
        elif delta.days > 30:
            months = delta.days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        elif delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds > 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds > 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"

    @staticmethod
    def get_history_for_user(user_id, limit=50):
        """Get scan history for a user, most recent first."""
        return ScanHistory.query.filter_by(user_id=user_id)\
            .order_by(ScanHistory.scan_date.desc())\
            .limit(limit)\
            .all()

    @staticmethod
    def create_from_scan(user_id, books_list, search_query=None, image_url=None):
        """Create a scan history record from a book scan."""
        history = ScanHistory(
            user_id=user_id,
            search_query=search_query or "Image analysis",
            image_url=image_url
        )
        history.books = books_list  # Uses property setter to convert to JSON

        return history
