"""
Author model for SEO landing pages.
"""

from datetime import datetime
from models import db


class Author(db.Model):
    """Author model for SEO author recommendation pages."""

    __tablename__ = 'authors'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Author data
    slug = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    image_url = db.Column(db.String(500), nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Author {self.name}>'

    @staticmethod
    def find_by_slug(slug):
        """Find author by slug."""
        return Author.query.filter_by(slug=slug).first()

    @staticmethod
    def get_all():
        """Get all authors sorted by name."""
        return Author.query.order_by(Author.name).all()
