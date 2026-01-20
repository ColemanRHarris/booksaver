"""
Analytics Service - Business logic for generating reading statistics and insights.
"""

from models import db, ScanHistory, BookCollection
from sqlalchemy import func, extract
from datetime import datetime
from typing import Dict, List
import json
from collections import Counter


class AnalyticsService:
    """Service for generating analytics and statistics."""

    @staticmethod
    def get_total_stats(user_id: int) -> Dict:
        """
        Get total statistics across scans and collections.

        Args:
            user_id: User ID

        Returns:
            Dict with total counts
        """
        # Get total scans
        total_scans = ScanHistory.query.filter_by(user_id=user_id).count()

        # Get total books from all scans
        scans = ScanHistory.query.filter_by(user_id=user_id).all()
        total_books_scanned = sum(scan.books_count for scan in scans)

        # Get collection stats
        collection_books = BookCollection.query.filter_by(user_id=user_id).all()
        total_in_collection = len(collection_books)
        books_read = sum(1 for book in collection_books if book.read_status == 'read')

        # Extract unique authors from collections
        all_authors = []
        for book in collection_books:
            all_authors.extend(book.authors)
        unique_authors = len(set(all_authors))

        return {
            'total_scans': total_scans,
            'total_books_scanned': total_books_scanned,
            'total_in_collection': total_in_collection,
            'books_read': books_read,
            'unique_authors': unique_authors
        }

    @staticmethod
    def get_scans_over_time(user_id: int) -> List[Dict]:
        """
        Get scan activity over time (by month).

        Args:
            user_id: User ID

        Returns:
            List of dicts with month and count
            [{'month': 'Jan 2026', 'year': 2026, 'month_num': 1, 'count': 5}, ...]
        """
        # Query scans grouped by month
        scans_by_month = db.session.query(
            extract('year', ScanHistory.scan_date).label('year'),
            extract('month', ScanHistory.scan_date).label('month'),
            func.count(ScanHistory.id).label('count')
        ).filter(
            ScanHistory.user_id == user_id
        ).group_by(
            'year', 'month'
        ).order_by(
            'year', 'month'
        ).all()

        # Format for display
        month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                      'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        result = []
        for year, month, count in scans_by_month:
            month_name = month_names[int(month) - 1]
            result.append({
                'month': f"{month_name} {int(year)}",
                'year': int(year),
                'month_num': int(month),
                'count': count
            })

        return result

    @staticmethod
    def get_genre_distribution(user_id: int) -> List[Dict]:
        """
        Get genre distribution from user's collection.

        Args:
            user_id: User ID

        Returns:
            List of dicts with genre and count
            [{'genre': 'Fiction', 'count': 15}, ...]
        """
        # Get all books in collection
        collection_books = BookCollection.query.filter_by(user_id=user_id).all()

        # Extract all genres
        all_genres = []
        for book in collection_books:
            genres = book.genres
            if genres:
                all_genres.extend(genres)

        # Count occurrences
        genre_counts = Counter(all_genres)

        # Format as list of dicts, sorted by count
        result = [
            {'genre': genre, 'count': count}
            for genre, count in genre_counts.most_common()
        ]

        return result

    @staticmethod
    def get_top_authors(user_id: int, limit: int = 10) -> List[Dict]:
        """
        Get most frequently occurring authors in collection.

        Args:
            user_id: User ID
            limit: Maximum number of authors to return

        Returns:
            List of dicts with author and count
            [{'author': 'Andy Weir', 'count': 5}, ...]
        """
        # Get all books in collection
        collection_books = BookCollection.query.filter_by(user_id=user_id).all()

        # Extract all authors
        all_authors = []
        for book in collection_books:
            authors = book.authors
            if authors:
                # Count each author separately (not as a group)
                all_authors.extend(authors)

        # Count occurrences
        author_counts = Counter(all_authors)

        # Format as list of dicts, sorted by count
        result = [
            {'author': author, 'count': count}
            for author, count in author_counts.most_common(limit)
        ]

        return result

    @staticmethod
    def get_reading_pace(user_id: int, year: int = None) -> Dict:
        """
        Calculate reading pace (books per month).

        Args:
            user_id: User ID
            year: Year to analyze (defaults to current year)

        Returns:
            Dict with pace statistics
        """
        if not year:
            year = datetime.now().year

        # Get books read in the specified year
        books_read = db.session.query(BookCollection).filter(
            BookCollection.user_id == user_id,
            BookCollection.read_status == 'read',
            BookCollection.date_read.isnot(None),
            extract('year', BookCollection.date_read) == year
        ).all()

        total_books = len(books_read)

        # Calculate months elapsed based on reading dates
        if total_books == 0:
            months_elapsed = 1  # Avoid division by zero
        else:
            # Get earliest and latest reading dates
            reading_dates = [book.date_read for book in books_read if book.date_read]
            if reading_dates:
                earliest = min(reading_dates)
                latest = max(reading_dates)

                # Calculate months between earliest and latest (inclusive)
                months_elapsed = (latest.year - earliest.year) * 12 + (latest.month - earliest.month) + 1
            else:
                months_elapsed = 1

        # Calculate pace
        books_per_month = total_books / months_elapsed if months_elapsed > 0 else 0

        # Group by month
        books_by_month = {}
        for book in books_read:
            if book.date_read:
                month_key = book.date_read.strftime('%b %Y')
                books_by_month[month_key] = books_by_month.get(month_key, 0) + 1

        return {
            'year': year,
            'total_books': total_books,
            'months_elapsed': months_elapsed,
            'books_per_month': round(books_per_month, 1),
            'books_by_month': books_by_month
        }

    @staticmethod
    def get_collection_breakdown(user_id: int) -> Dict:
        """
        Get breakdown of collection by shelf and read status.

        Args:
            user_id: User ID

        Returns:
            Dict with counts by shelf and status
        """
        collection_books = BookCollection.query.filter_by(user_id=user_id).all()

        shelves = {'want_to_read': 0, 'currently_reading': 0, 'read': 0}
        statuses = {'unread': 0, 'reading': 0, 'read': 0}

        for book in collection_books:
            shelves[book.shelf] = shelves.get(book.shelf, 0) + 1
            statuses[book.read_status] = statuses.get(book.read_status, 0) + 1

        return {
            'total': len(collection_books),
            'by_shelf': shelves,
            'by_status': statuses
        }

    @staticmethod
    def get_recent_activity(user_id: int, limit: int = 5) -> Dict:
        """
        Get recent reading activity.

        Args:
            user_id: User ID
            limit: Number of recent items to return

        Returns:
            Dict with recent scans and recent reads
        """
        # Recent scans
        recent_scans = ScanHistory.query.filter_by(user_id=user_id)\
            .order_by(ScanHistory.scan_date.desc())\
            .limit(limit)\
            .all()

        # Recent books marked as read
        recent_reads = BookCollection.query.filter(
            BookCollection.user_id == user_id,
            BookCollection.read_status == 'read',
            BookCollection.date_read.isnot(None)
        ).order_by(BookCollection.date_read.desc())\
            .limit(limit)\
            .all()

        return {
            'recent_scans': [
                {
                    'date': scan.scan_date,
                    'books_count': scan.books_count,
                    'relative_date': scan.get_relative_date()
                }
                for scan in recent_scans
            ],
            'recent_reads': [
                {
                    'title': book.title,
                    'authors': book.get_authors_display(),
                    'date_read': book.date_read,
                    'thumbnail': book.thumbnail
                }
                for book in recent_reads
            ]
        }
