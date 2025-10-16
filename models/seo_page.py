"""
SEO Page model for dynamic SEO landing pages.
"""

from datetime import datetime
from models import db


class SEOPage(db.Model):
    """SEO Page model for storing dynamic SEO landing page content."""

    __tablename__ = 'seo_pages'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Page identification
    page_type = db.Column(db.String(50), nullable=False, index=True)  # 'genre', 'author', 'books_like'
    slug = db.Column(db.String(200), nullable=False, index=True)

    # SEO metadata
    title = db.Column(db.String(300), nullable=False)
    meta_description = db.Column(db.Text, nullable=False)

    # Page content (stored as JSON)
    content_data = db.Column(db.JSON, nullable=True)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Composite unique constraint on page_type + slug
    __table_args__ = (
        db.UniqueConstraint('page_type', 'slug', name='uq_seo_page_type_slug'),
        db.Index('idx_page_type_slug', 'page_type', 'slug'),
    )

    def __repr__(self):
        return f'<SEOPage {self.page_type}/{self.slug}>'

    @staticmethod
    def find_by_type_and_slug(page_type, slug):
        """Find SEO page by type and slug."""
        return SEOPage.query.filter_by(page_type=page_type, slug=slug).first()

    @staticmethod
    def get_by_type(page_type):
        """Get all SEO pages of a specific type."""
        return SEOPage.query.filter_by(page_type=page_type).order_by(SEOPage.created_at).all()

    @staticmethod
    def get_all():
        """Get all SEO pages."""
        return SEOPage.query.order_by(SEOPage.page_type, SEOPage.created_at).all()
