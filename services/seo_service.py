"""
SEO Landing Pages service for managing parasite SEO content.
Now using persistent SQLAlchemy database storage.
"""

import re
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from models import db
from models.genre import Genre
from models.author import Author
from models.popular_book import PopularBook
from models.seo_page import SEOPage

# Simple logger
logger = logging.getLogger(__name__)


class SEOService:
    """Service for managing SEO landing pages and content with database persistence."""

    def __init__(self):
        self.logger = logger
        self.logger.info("🔧 SEO Service using SQLAlchemy database storage")

        # Initialize default data if tables are empty
        self._initialize_default_data()

    def _initialize_default_data(self):
        """Initialize default genres and popular books if database is empty."""
        try:
            # Check if we already have genres
            if Genre.query.count() > 0:
                self.logger.info("✅ SEO data already initialized, skipping seed")
                return

            self.logger.info("🌱 Seeding default SEO data...")

            # Add default genres
            default_genres = [
                "science-fiction", "fantasy", "mystery", "thriller", "romance",
                "literary-fiction", "historical-fiction", "horror", "young-adult",
                "non-fiction", "biography", "self-help", "business", "psychology"
            ]

            for genre_slug in default_genres:
                display_name = genre_slug.replace('-', ' ').title()
                self.add_genre(genre_slug, display_name)

            # Add some popular books for "books like" pages
            popular_books = [
                {"slug": "fourth-wing", "title": "Fourth Wing", "author": "Rebecca Yarros"},
                {"slug": "project-hail-mary", "title": "Project Hail Mary", "author": "Andy Weir"},
                {"slug": "atomic-habits", "title": "Atomic Habits", "author": "James Clear"},
                {"slug": "where-crawdads-sing", "title": "Where the Crawdads Sing", "author": "Delia Owens"},
                {"slug": "dune", "title": "Dune", "author": "Frank Herbert"}
            ]

            for book in popular_books:
                self.add_popular_book(book["slug"], book["title"], book["author"])

            self.logger.info("✅ Default SEO data seeded successfully")

        except Exception as e:
            self.logger.error(f"❌ Error initializing default data: {e}")

    def slugify(self, text: str) -> str:
        """Convert text to URL-safe slug."""
        # Convert to lowercase and replace spaces/special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', text.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')

    # Genre Management
    def add_genre(self, slug: str, display_name: str) -> bool:
        """Add a new genre."""
        try:
            # Check if genre already exists
            existing = Genre.find_by_slug(slug)
            if existing:
                self.logger.info(f"ℹ️  Genre already exists: {display_name} ({slug})")
                return True

            genre = Genre(
                slug=slug,
                display_name=display_name
            )

            db.session.add(genre)
            db.session.commit()

            self.logger.info(f"✅ Added genre: {display_name} ({slug})")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to add genre {slug}: {e}")
            db.session.rollback()
            return False

    def get_genre(self, slug: str) -> Optional[Dict[str, str]]:
        """Get genre data by slug."""
        try:
            genre = Genre.find_by_slug(slug)
            if not genre:
                return None

            return {
                'slug': genre.slug,
                'display_name': genre.display_name,
                'created_at': genre.created_at.isoformat() if genre.created_at else None
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to get genre {slug}: {e}")
            return None

    def get_all_genres(self) -> List[Dict[str, str]]:
        """Get all genres."""
        try:
            genres = Genre.get_all()
            return [
                {
                    'slug': g.slug,
                    'display_name': g.display_name,
                    'created_at': g.created_at.isoformat() if g.created_at else None
                }
                for g in genres
            ]

        except Exception as e:
            self.logger.error(f"❌ Failed to get all genres: {e}")
            return []

    # Popular Books Management
    def add_popular_book(self, slug: str, title: str, author: str, description: str = "") -> bool:
        """Add a popular book for 'books like' pages."""
        try:
            # Check if book already exists
            existing = PopularBook.find_by_slug(slug)
            if existing:
                self.logger.info(f"ℹ️  Popular book already exists: {title}")
                return True

            book = PopularBook(
                slug=slug,
                title=title,
                author=author,
                description=description
            )

            db.session.add(book)
            db.session.commit()

            self.logger.info(f"✅ Added popular book: {title} by {author}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to add popular book {slug}: {e}")
            db.session.rollback()
            return False

    def get_popular_book(self, slug: str) -> Optional[Dict[str, str]]:
        """Get popular book data by slug."""
        try:
            book = PopularBook.find_by_slug(slug)
            if not book:
                return None

            return {
                'slug': book.slug,
                'title': book.title,
                'author': book.author,
                'description': book.description or '',
                'created_at': book.created_at.isoformat() if book.created_at else None
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to get popular book {slug}: {e}")
            return None

    def get_all_popular_books(self) -> List[Dict[str, str]]:
        """Get all popular books."""
        try:
            books = PopularBook.get_all()
            return [
                {
                    'slug': b.slug,
                    'title': b.title,
                    'author': b.author,
                    'description': b.description or '',
                    'created_at': b.created_at.isoformat() if b.created_at else None
                }
                for b in books
            ]

        except Exception as e:
            self.logger.error(f"❌ Failed to get all popular books: {e}")
            return []

    # Author Management
    def add_author(self, slug: str, name: str, bio: str = "", image_url: str = "") -> bool:
        """Add an author for author recommendation pages."""
        try:
            # Check if author already exists
            existing = Author.find_by_slug(slug)
            if existing:
                self.logger.info(f"ℹ️  Author already exists: {name}")
                return True

            author = Author(
                slug=slug,
                name=name,
                bio=bio,
                image_url=image_url
            )

            db.session.add(author)
            db.session.commit()

            self.logger.info(f"✅ Added author: {name}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to add author {slug}: {e}")
            db.session.rollback()
            return False

    def get_author(self, slug: str) -> Optional[Dict[str, str]]:
        """Get author data by slug."""
        try:
            author = Author.find_by_slug(slug)
            if not author:
                return None

            return {
                'slug': author.slug,
                'name': author.name,
                'bio': author.bio or '',
                'image_url': author.image_url or '',
                'created_at': author.created_at.isoformat() if author.created_at else None
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to get author {slug}: {e}")
            return None

    # SEO Page Management
    def create_seo_page(self, page_type: str, slug: str, title: str,
                       meta_description: str, content_data: Dict[str, Any]) -> bool:
        """Create an SEO landing page."""
        try:
            # Check if page already exists
            existing = SEOPage.find_by_type_and_slug(page_type, slug)
            if existing:
                # Update existing page
                existing.title = title
                existing.meta_description = meta_description
                existing.content_data = content_data
                existing.updated_at = datetime.utcnow()
                db.session.commit()
                self.logger.info(f"✅ Updated SEO page: {page_type}/{slug}")
                return True

            page = SEOPage(
                page_type=page_type,
                slug=slug,
                title=title,
                meta_description=meta_description,
                content_data=content_data
            )

            db.session.add(page)
            db.session.commit()

            self.logger.info(f"✅ Created SEO page: {page_type}/{slug}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Failed to create SEO page {page_type}/{slug}: {e}")
            db.session.rollback()
            return False

    def get_seo_page(self, page_type: str, slug: str) -> Optional[Dict[str, Any]]:
        """Get SEO page data."""
        try:
            page = SEOPage.find_by_type_and_slug(page_type, slug)
            if not page:
                return None

            return {
                'page_type': page.page_type,
                'slug': page.slug,
                'title': page.title,
                'meta_description': page.meta_description,
                'content_data': page.content_data or {},
                'created_at': page.created_at.isoformat() if page.created_at else None,
                'updated_at': page.updated_at.isoformat() if page.updated_at else None
            }

        except Exception as e:
            self.logger.error(f"❌ Failed to get SEO page {page_type}/{slug}: {e}")
            return None

    def get_seo_pages_by_type(self, page_type: str) -> List[Dict[str, Any]]:
        """Get all SEO pages of a specific type."""
        try:
            pages = SEOPage.get_by_type(page_type)
            return [
                {
                    'page_type': p.page_type,
                    'slug': p.slug,
                    'title': p.title,
                    'meta_description': p.meta_description,
                    'content_data': p.content_data or {},
                    'created_at': p.created_at.isoformat() if p.created_at else None,
                    'updated_at': p.updated_at.isoformat() if p.updated_at else None
                }
                for p in pages
            ]

        except Exception as e:
            self.logger.error(f"❌ Failed to get SEO pages of type {page_type}: {e}")
            return []

    # URL Generation
    def generate_genre_url(self, genre_slug: str, year: str = "2025") -> str:
        """Generate URL for best genre books page."""
        return f"/best-books/{genre_slug}/{year}/"

    def generate_author_url(self, author_slug: str) -> str:
        """Generate URL for author recommendations page."""
        return f"/authors/{author_slug}/recommendations/"

    def generate_books_like_url(self, book_slug: str) -> str:
        """Generate URL for books like page."""
        return f"/books-like/{book_slug}/"

    # Analytics and Stats
    def get_seo_stats(self) -> Dict[str, int]:
        """Get SEO pages statistics."""
        try:
            stats = {
                "total_genres": Genre.query.count(),
                "total_authors": Author.query.count(),
                "total_popular_books": PopularBook.query.count(),
                "total_seo_pages": SEOPage.query.count(),
                "genre_pages": SEOPage.query.filter_by(page_type='genre').count(),
                "author_pages": SEOPage.query.filter_by(page_type='author').count(),
                "books_like_pages": SEOPage.query.filter_by(page_type='books_like').count()
            }
            return stats

        except Exception as e:
            self.logger.error(f"❌ Failed to get SEO stats: {e}")
            return {}


# Global instance
_seo_service = None

def get_seo_service() -> SEOService:
    """Get the global SEO service instance."""
    global _seo_service
    if _seo_service is None:
        _seo_service = SEOService()
    return _seo_service
