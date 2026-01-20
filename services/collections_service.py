"""
Collections Service - Business logic for managing user book collections.
"""

from models import db, BookCollection
from datetime import date
from typing import List, Dict, Optional


class CollectionsService:
    """Service for managing user book collections."""

    VALID_SHELVES = ['want_to_read', 'currently_reading', 'read']
    VALID_READ_STATUSES = ['unread', 'reading', 'read']

    @staticmethod
    def add_book_to_collection(user_id: int, book_data: Dict, shelf: str = 'want_to_read') -> Optional[BookCollection]:
        """
        Add a book to user's collection with deduplication.

        Args:
            user_id: User ID
            book_data: Dict with keys: title, authors, isbn, thumbnail, published_date, categories
            shelf: Shelf to add to (default: want_to_read)

        Returns:
            BookCollection instance if added, None if already exists
        """
        # Validate shelf
        if shelf not in CollectionsService.VALID_SHELVES:
            shelf = 'want_to_read'

        # Check for duplicates
        existing = None

        # Try ISBN deduplication first (most reliable)
        isbn = book_data.get('isbn')
        if isbn:
            existing = BookCollection.find_by_isbn(user_id, isbn)

        # Fallback to title+author deduplication
        if not existing:
            title = book_data.get('title', '').strip()
            authors = book_data.get('authors', [])
            if title and authors:
                existing = BookCollection.find_by_title_author(user_id, title, authors)

        # If book already exists, don't add duplicate
        if existing:
            print(f"📚 Book already in collection: {existing.title}")
            return None

        # Create new collection entry
        collection = BookCollection.create_from_book_data(user_id, book_data, shelf)
        db.session.add(collection)
        db.session.commit()

        print(f"✅ Added to collection: {collection.title} (Shelf: {shelf})")
        return collection

    @staticmethod
    def get_books_by_shelf(user_id: int, shelf: str) -> List[BookCollection]:
        """
        Get all books on a specific shelf for a user.

        Args:
            user_id: User ID
            shelf: Shelf name (want_to_read, currently_reading, read)

        Returns:
            List of BookCollection instances
        """
        if shelf not in CollectionsService.VALID_SHELVES:
            return []

        return BookCollection.get_books_by_shelf(user_id, shelf)

    @staticmethod
    def get_all_books(user_id: int) -> List[BookCollection]:
        """
        Get all books in user's collection.

        Args:
            user_id: User ID

        Returns:
            List of BookCollection instances
        """
        return BookCollection.get_all_books_for_user(user_id)

    @staticmethod
    def get_collection_stats(user_id: int) -> Dict:
        """
        Get statistics about user's collection.

        Args:
            user_id: User ID

        Returns:
            Dict with counts for each shelf and read status
        """
        all_books = CollectionsService.get_all_books(user_id)

        stats = {
            'total': len(all_books),
            'shelves': {
                'want_to_read': 0,
                'currently_reading': 0,
                'read': 0
            },
            'read_status': {
                'unread': 0,
                'reading': 0,
                'read': 0
            }
        }

        for book in all_books:
            stats['shelves'][book.shelf] = stats['shelves'].get(book.shelf, 0) + 1
            stats['read_status'][book.read_status] = stats['read_status'].get(book.read_status, 0) + 1

        return stats

    @staticmethod
    def move_book(collection_id: int, new_shelf: str) -> bool:
        """
        Move a book to a different shelf.

        Args:
            collection_id: BookCollection ID
            new_shelf: New shelf name

        Returns:
            True if successful, False otherwise
        """
        if new_shelf not in CollectionsService.VALID_SHELVES:
            print(f"❌ Invalid shelf: {new_shelf}")
            return False

        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        old_shelf = collection.shelf
        collection.shelf = new_shelf
        db.session.commit()

        print(f"📦 Moved '{collection.title}' from {old_shelf} to {new_shelf}")
        return True

    @staticmethod
    def update_tags(collection_id: int, tags_list: List[str]) -> bool:
        """
        Update tags for a book.

        Args:
            collection_id: BookCollection ID
            tags_list: List of tag strings

        Returns:
            True if successful, False otherwise
        """
        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        # Clean and validate tags
        cleaned_tags = [tag.strip() for tag in tags_list if tag.strip()]
        collection.tags = cleaned_tags
        db.session.commit()

        print(f"🏷️ Updated tags for '{collection.title}': {', '.join(cleaned_tags) if cleaned_tags else 'No tags'}")
        return True

    @staticmethod
    def mark_as_read(collection_id: int, date_read: Optional[date] = None) -> bool:
        """
        Mark a book as read.

        Args:
            collection_id: BookCollection ID
            date_read: Date when book was read (defaults to today)

        Returns:
            True if successful, False otherwise
        """
        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        collection.read_status = 'read'
        collection.date_read = date_read or date.today()

        # Automatically move to 'read' shelf
        collection.shelf = 'read'

        db.session.commit()

        print(f"✓ Marked as read: '{collection.title}' on {collection.date_read}")
        return True

    @staticmethod
    def mark_as_reading(collection_id: int) -> bool:
        """
        Mark a book as currently reading.

        Args:
            collection_id: BookCollection ID

        Returns:
            True if successful, False otherwise
        """
        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        collection.read_status = 'reading'

        # Automatically move to 'currently_reading' shelf
        collection.shelf = 'currently_reading'

        db.session.commit()

        print(f"📖 Marked as reading: '{collection.title}'")
        return True

    @staticmethod
    def mark_as_unread(collection_id: int) -> bool:
        """
        Mark a book as unread.

        Args:
            collection_id: BookCollection ID

        Returns:
            True if successful, False otherwise
        """
        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        collection.read_status = 'unread'
        collection.date_read = None

        # Automatically move to 'want_to_read' shelf if currently on 'read' shelf
        if collection.shelf == 'read':
            collection.shelf = 'want_to_read'

        db.session.commit()

        print(f"📚 Marked as unread: '{collection.title}'")
        return True

    @staticmethod
    def remove_book(collection_id: int) -> bool:
        """
        Remove a book from collection.

        Args:
            collection_id: BookCollection ID

        Returns:
            True if successful, False otherwise
        """
        collection = BookCollection.query.get(collection_id)
        if not collection:
            print(f"❌ Collection entry not found: {collection_id}")
            return False

        title = collection.title
        db.session.delete(collection)
        db.session.commit()

        print(f"🗑️ Removed from collection: '{title}'")
        return True

    @staticmethod
    def get_unread_books(user_id: int) -> List[BookCollection]:
        """
        Get all unread books in user's collection (for AI recommendations).

        Args:
            user_id: User ID

        Returns:
            List of BookCollection instances with read_status='unread' or 'reading'
        """
        return BookCollection.query.filter(
            BookCollection.user_id == user_id,
            BookCollection.read_status.in_(['unread', 'reading'])
        ).order_by(BookCollection.added_at.desc()).all()

    @staticmethod
    def get_books_read_this_year(user_id: int, year: int) -> List[BookCollection]:
        """
        Get all books read in a specific year (for reading goals).

        Args:
            user_id: User ID
            year: Year to filter by

        Returns:
            List of BookCollection instances read in that year
        """
        from sqlalchemy import extract

        return BookCollection.query.filter(
            BookCollection.user_id == user_id,
            BookCollection.read_status == 'read',
            BookCollection.date_read.isnot(None),
            extract('year', BookCollection.date_read) == year
        ).order_by(BookCollection.date_read.desc()).all()
