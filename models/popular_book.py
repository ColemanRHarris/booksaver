"""
PopularBook model for SEO landing pages.
"""

from datetime import datetime
from models import db


class PopularBook(db.Model):
    """PopularBook model for SEO 'books like' pages."""

    __tablename__ = 'popular_books'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Book data
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    title = db.Column(db.String(300), nullable=False)
    author = db.Column(db.String(300), nullable=False)
    description = db.Column(db.Text, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<PopularBook {self.title} by {self.author}>'

    @staticmethod
    def find_by_slug(slug):
        """Find popular book by slug."""
        return PopularBook.query.filter_by(slug=slug).first()

    @staticmethod
    def get_all():
        """Get all popular books sorted by title."""
        return PopularBook.query.order_by(PopularBook.title).all()
