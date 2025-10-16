"""
Genre model for SEO landing pages.
"""

from datetime import datetime
from models import db


class Genre(db.Model):
    """Genre model for SEO best books pages."""

    __tablename__ = 'genres'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Genre data
    slug = db.Column(db.String(100), unique=True, nullable=False, index=True)
    display_name = db.Column(db.String(200), nullable=False)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<Genre {self.display_name}>'

    @staticmethod
    def find_by_slug(slug):
        """Find genre by slug."""
        return Genre.query.filter_by(slug=slug).first()

    @staticmethod
    def get_all():
        """Get all genres sorted by display name."""
        return Genre.query.order_by(Genre.display_name).all()
