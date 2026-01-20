"""
Book Collection model to store user's organized books for Pro users.
"""

from datetime import datetime, date
from models import db
import json


class BookCollection(db.Model):
    """Model to store books that users have added to their collections."""

    __tablename__ = 'book_collections'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Foreign key to user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Book identification (denormalized for simplicity)
    title = db.Column(db.String(500), nullable=False)
    authors_json = db.Column(db.Text, nullable=False)  # JSON array of authors
    isbn = db.Column(db.String(20), nullable=True, index=True)
    thumbnail = db.Column(db.String(500), nullable=True)
    published_date = db.Column(db.String(50), nullable=True)

    # Collection/shelf info
    shelf = db.Column(db.String(100), default='want_to_read', nullable=False, index=True)
    # Options: 'want_to_read', 'currently_reading', 'read'

    # Custom tags (JSON array)
    tags_json = db.Column(db.Text, nullable=True)  # JSON: ["fantasy", "series"]

    # Read status
    read_status = db.Column(db.String(50), default='unread', nullable=False, index=True)
    # Options: 'unread', 'reading', 'read'
    date_read = db.Column(db.Date, nullable=True)  # When marked as 'read'

    # Genres (from Google Books API - JSON array)
    genres_json = db.Column(db.Text, nullable=True)  # JSON: ["Fiction", "Fantasy"]

    # Timestamps
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Composite indexes for performance
    __table_args__ = (
        db.Index('idx_user_shelf', 'user_id', 'shelf'),
        db.Index('idx_user_read_status', 'user_id', 'read_status'),
    )

    def __repr__(self):
        return f'<BookCollection {self.id} - {self.title} ({self.shelf})>'

    @property
    def authors(self):
        """Get authors list from JSON string."""
        try:
            return json.loads(self.authors_json) if self.authors_json else []
        except (json.JSONDecodeError, TypeError):
            return []

    @authors.setter
    def authors(self, authors_list):
        """Set authors list as JSON string."""
        self.authors_json = json.dumps(authors_list if authors_list else [])

    @property
    def tags(self):
        """Get tags list from JSON string."""
        try:
            return json.loads(self.tags_json) if self.tags_json else []
        except (json.JSONDecodeError, TypeError):
            return []

    @tags.setter
    def tags(self, tags_list):
        """Set tags list as JSON string."""
        self.tags_json = json.dumps(tags_list if tags_list else [])

    @property
    def genres(self):
        """Get genres list from JSON string."""
        try:
            return json.loads(self.genres_json) if self.genres_json else []
        except (json.JSONDecodeError, TypeError):
            return []

    @genres.setter
    def genres(self, genres_list):
        """Set genres list as JSON string."""
        self.genres_json = json.dumps(genres_list if genres_list else [])

    def get_authors_display(self):
        """Get authors as comma-separated string."""
        authors = self.authors
        if not authors:
            return "Unknown Author"
        return ", ".join(authors)

    def get_tags_display(self):
        """Get tags as comma-separated string."""
        tags = self.tags
        return ", ".join(tags) if tags else ""

    def get_genres_display(self):
        """Get genres as comma-separated string."""
        genres = self.genres
        return ", ".join(genres) if genres else ""

    @staticmethod
    def get_books_by_shelf(user_id, shelf):
        """Get all books on a specific shelf for a user."""
        return BookCollection.query.filter_by(user_id=user_id, shelf=shelf)\
            .order_by(BookCollection.added_at.desc())\
            .all()

    @staticmethod
    def get_all_books_for_user(user_id):
        """Get all books in collection for a user."""
        return BookCollection.query.filter_by(user_id=user_id)\
            .order_by(BookCollection.added_at.desc())\
            .all()

    @staticmethod
    def find_by_isbn(user_id, isbn):
        """Find a book in user's collection by ISBN (for deduplication)."""
        if not isbn:
            return None
        return BookCollection.query.filter_by(user_id=user_id, isbn=isbn).first()

    @staticmethod
    def find_by_title_author(user_id, title, authors):
        """Find a book in user's collection by title and first author."""
        # Get first author for comparison
        first_author = authors[0] if authors else ""
        if not title or not first_author:
            return None

        # Query all books for user and check in Python (since authors is JSON)
        books = BookCollection.query.filter_by(user_id=user_id, title=title).all()
        for book in books:
            book_authors = book.authors
            if book_authors and book_authors[0] == first_author:
                return book
        return None

    @staticmethod
    def create_from_book_data(user_id, book_data, shelf='want_to_read'):
        """
        Create a book collection entry from book data dict.

        Args:
            user_id: User ID
            book_data: Dict with keys: title, authors, isbn, thumbnail, published_date, categories
            shelf: Shelf to add to (default: want_to_read)

        Returns:
            BookCollection instance
        """
        collection = BookCollection(
            user_id=user_id,
            title=book_data.get('title', 'Unknown Title'),
            isbn=book_data.get('isbn'),
            thumbnail=book_data.get('thumbnail'),
            published_date=book_data.get('published_date'),
            shelf=shelf,
            read_status='unread'
        )

        # Use property setters for JSON fields
        collection.authors = book_data.get('authors', [])
        collection.genres = book_data.get('categories', [])
        collection.tags = []  # Empty tags initially

        return collection
