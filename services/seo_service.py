"""
SEO Landing Pages service for managing parasite SEO content.
Handles creation, management, and serving of SEO-optimized landing pages
for book recommendations, author pages, and genre-specific content.
"""

import os
import json
import redis
import hashlib
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from urllib.parse import quote, unquote
from core.logging_utils import get_safe_logger
from core.redis_utils import configure_redis_for_service


class InMemoryRedis:
    """Simple in-memory Redis-like storage for local development."""
    
    def __init__(self):
        self._data = {}
        self._sets = {}
    
    def hset(self, key: str, field: str = None, value: str = None, mapping: Dict[str, str] = None) -> int:
        """Set hash fields."""
        if key not in self._data:
            self._data[key] = {}
        
        if mapping:
            self._data[key].update(mapping)
            return len(mapping)
        elif field is not None and value is not None:
            self._data[key][field] = value
            return 1
        else:
            raise TypeError("Must provide either field/value or mapping")
    
    def hgetall(self, key: str) -> Dict[str, str]:
        """Get all hash fields."""
        return self._data.get(key, {}).copy()
    
    def hget(self, key: str, field: str) -> Optional[str]:
        """Get specific hash field."""
        return self._data.get(key, {}).get(field)
    
    def exists(self, key: str) -> bool:
        """Check if key exists."""
        return key in self._data
    
    def sadd(self, key: str, *values) -> int:
        """Add values to set."""
        if key not in self._sets:
            self._sets[key] = set()
        
        count = 0
        for value in values:
            if value not in self._sets[key]:
                self._sets[key].add(value)
                count += 1
        return count
    
    def smembers(self, key: str) -> set:
        """Get all members of set."""
        return self._sets.get(key, set()).copy()
    
    def srem(self, key: str, *values) -> int:
        """Remove values from set."""
        if key not in self._sets:
            return 0
        
        count = 0
        for value in values:
            if value in self._sets[key]:
                self._sets[key].remove(value)
                count += 1
        return count


class SEOService:
    """Service for managing SEO landing pages and content."""
    
    def __init__(self, redis_client=None):
        self.logger = get_safe_logger(__name__)
        
        if redis_client:
            self.redis = redis_client
            self.logger.info("✅ SEOService using provided Redis client")
        else:
            # Use centralized Redis configuration
            self.redis, using_redis = configure_redis_for_service(
                "SEOService", decode_responses=True
            )
            
            # If Redis not available, use in-memory storage
            if not using_redis:
                self.redis = InMemoryRedis()
        
        # Initialize default genres and popular books
        self._initialize_default_data()
    
    def _initialize_default_data(self):
        """Initialize default genres and popular books if not exists."""
        default_genres = [
            "science-fiction", "fantasy", "mystery", "thriller", "romance",
            "literary-fiction", "historical-fiction", "horror", "young-adult",
            "non-fiction", "biography", "self-help", "business", "psychology"
        ]
        
        for genre in default_genres:
            self.add_genre(genre, genre.replace('-', ' ').title())
        
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
            genre_data = {
                "slug": slug,
                "display_name": display_name,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            self.redis.hset(f"genre:{slug}", mapping=genre_data)
            self.redis.sadd("genres", slug)
            
            self.logger.info(f"✅ Added genre: {display_name} ({slug})")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to add genre {slug}: {e}")
            return False
    
    def get_genre(self, slug: str) -> Optional[Dict[str, str]]:
        """Get genre data by slug."""
        try:
            return self.redis.hgetall(f"genre:{slug}")
        except Exception as e:
            self.logger.error(f"❌ Failed to get genre {slug}: {e}")
            return None
    
    def get_all_genres(self) -> List[Dict[str, str]]:
        """Get all genres."""
        try:
            genre_slugs = self.redis.smembers("genres")
            genres = []
            
            for slug in genre_slugs:
                genre_data = self.get_genre(slug)
                if genre_data:
                    genres.append(genre_data)
            
            return sorted(genres, key=lambda x: x.get('display_name', ''))
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get all genres: {e}")
            return []
    
    # Popular Books Management
    def add_popular_book(self, slug: str, title: str, author: str, description: str = "") -> bool:
        """Add a popular book for 'books like' pages."""
        try:
            book_data = {
                "slug": slug,
                "title": title,
                "author": author,
                "description": description,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            self.redis.hset(f"popular_book:{slug}", mapping=book_data)
            self.redis.sadd("popular_books", slug)
            
            self.logger.info(f"✅ Added popular book: {title} by {author}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to add popular book {slug}: {e}")
            return False
    
    def get_popular_book(self, slug: str) -> Optional[Dict[str, str]]:
        """Get popular book data by slug."""
        try:
            return self.redis.hgetall(f"popular_book:{slug}")
        except Exception as e:
            self.logger.error(f"❌ Failed to get popular book {slug}: {e}")
            return None
    
    def get_all_popular_books(self) -> List[Dict[str, str]]:
        """Get all popular books."""
        try:
            book_slugs = self.redis.smembers("popular_books")
            books = []
            
            for slug in book_slugs:
                book_data = self.get_popular_book(slug)
                if book_data:
                    books.append(book_data)
            
            return sorted(books, key=lambda x: x.get('title', ''))
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get all popular books: {e}")
            return []
    
    # Author Management
    def add_author(self, slug: str, name: str, bio: str = "", image_url: str = "") -> bool:
        """Add an author for author recommendation pages."""
        try:
            author_data = {
                "slug": slug,
                "name": name,
                "bio": bio,
                "image_url": image_url,
                "created_at": datetime.now(timezone.utc).isoformat()
            }
            
            self.redis.hset(f"author:{slug}", mapping=author_data)
            self.redis.sadd("authors", slug)
            
            self.logger.info(f"✅ Added author: {name}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to add author {slug}: {e}")
            return False
    
    def get_author(self, slug: str) -> Optional[Dict[str, str]]:
        """Get author data by slug."""
        try:
            return self.redis.hgetall(f"author:{slug}")
        except Exception as e:
            self.logger.error(f"❌ Failed to get author {slug}: {e}")
            return None
    
    # SEO Page Management
    def create_seo_page(self, page_type: str, slug: str, title: str, 
                       meta_description: str, content_data: Dict[str, Any]) -> bool:
        """Create an SEO landing page."""
        try:
            page_data = {
                "page_type": page_type,  # 'genre', 'author', 'books_like'
                "slug": slug,
                "title": title,
                "meta_description": meta_description,
                "content_data": json.dumps(content_data),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
            
            self.redis.hset(f"seo_page:{page_type}:{slug}", mapping=page_data)
            self.redis.sadd(f"seo_pages:{page_type}", slug)
            self.redis.sadd("all_seo_pages", f"{page_type}:{slug}")
            
            self.logger.info(f"✅ Created SEO page: {page_type}/{slug}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create SEO page {page_type}/{slug}: {e}")
            return False
    
    def get_seo_page(self, page_type: str, slug: str) -> Optional[Dict[str, Any]]:
        """Get SEO page data."""
        try:
            page_data = self.redis.hgetall(f"seo_page:{page_type}:{slug}")
            if page_data and 'content_data' in page_data:
                page_data['content_data'] = json.loads(page_data['content_data'])
            return page_data if page_data else None
            
        except Exception as e:
            self.logger.error(f"❌ Failed to get SEO page {page_type}/{slug}: {e}")
            return None
    
    def get_seo_pages_by_type(self, page_type: str) -> List[Dict[str, Any]]:
        """Get all SEO pages of a specific type."""
        try:
            page_slugs = self.redis.smembers(f"seo_pages:{page_type}")
            pages = []
            
            for slug in page_slugs:
                page_data = self.get_seo_page(page_type, slug)
                if page_data:
                    pages.append(page_data)
            
            return sorted(pages, key=lambda x: x.get('created_at', ''))
            
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
                "total_genres": len(self.redis.smembers("genres")),
                "total_authors": len(self.redis.smembers("authors")),
                "total_popular_books": len(self.redis.smembers("popular_books")),
                "total_seo_pages": len(self.redis.smembers("all_seo_pages")),
                "genre_pages": len(self.redis.smembers("seo_pages:genre")),
                "author_pages": len(self.redis.smembers("seo_pages:author")),
                "books_like_pages": len(self.redis.smembers("seo_pages:books_like"))
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

def initialize_seo_service_with_app(app):
    """Initialize SEO service with Flask app context for Redis consistency."""
    global _seo_service
    
    # Use centralized Redis configuration
    try:
        from core.redis_utils import get_redis_client
        redis_client, using_redis = get_redis_client(decode_responses=True)
        
        if using_redis and redis_client:
            _seo_service = SEOService(redis_client=redis_client)
            app.logger.info("✅ SEO Service initialized with Redis")
        else:
            _seo_service = SEOService()
            app.logger.info("🔧 SEO Service using in-memory storage")
        
    except Exception as e:
        app.logger.warning(f"⚠️ SEO Service fallback to in-memory storage: {e}")
        _seo_service = SEOService()