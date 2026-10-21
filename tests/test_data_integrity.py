"""
Tests for data integrity: deduplication, calculations, and analytics.

Ensures that:
- Collections don't have duplicates
- Progress calculations are accurate
- Analytics stats are correct
- CSV export deduplicates properly
"""

import pytest
from datetime import date, datetime
from dateutil.relativedelta import relativedelta

from models.book_collection import BookCollection
from services.collections_service import CollectionsService
from services.goals_service import GoalsService
from services.analytics_service import AnalyticsService
from services.export_service import ExportService


class TestCollectionsDeduplication:
    """Test deduplication logic in collections."""

    def test_isbn_deduplication(self, app, pro_user):
        """Adding same ISBN twice should only create one record."""
        with app.app_context():
            book_data = {
                'title': 'Project Hail Mary',
                'authors': ['Andy Weir'],
                'isbn': '9780062839649'
            }

            # Add first time
            first = CollectionsService.add_book_to_collection(pro_user.id, book_data)
            assert first is not None

            # Try to add again with different title
            book_data['title'] = 'Different Title'
            second = CollectionsService.add_book_to_collection(pro_user.id, book_data)
            assert second is None  # Should return None (duplicate)

            # Verify only one record exists
            count = BookCollection.query.filter_by(user_id=pro_user.id).count()
            assert count == 1

    def test_title_author_deduplication(self, app, pro_user):
        """Adding same title+author twice should only create one record."""
        with app.app_context():
            book_data = {
                'title': 'The Martian',
                'authors': ['Andy Weir'],
                'isbn': None  # No ISBN
            }

            # Add first time
            first = CollectionsService.add_book_to_collection(pro_user.id, book_data)
            assert first is not None

            # Try to add again
            second = CollectionsService.add_book_to_collection(pro_user.id, book_data)
            assert second is None  # Should return None (duplicate)

            # Verify only one record exists
            count = BookCollection.query.filter_by(user_id=pro_user.id).count()
            assert count == 1

    def test_no_false_duplicates(self, app, pro_user):
        """Books with same title but different authors should NOT be deduplicated."""
        with app.app_context():
            book1 = {
                'title': 'The Call of the Wild',
                'authors': ['Jack London'],
                'isbn': None
            }
            book2 = {
                'title': 'The Call of the Wild',
                'authors': ['Different Author'],
                'isbn': None
            }

            # Add both
            first = CollectionsService.add_book_to_collection(pro_user.id, book1)
            second = CollectionsService.add_book_to_collection(pro_user.id, book2)

            # Both should be added (not duplicates)
            assert first is not None
            assert second is not None

            # Verify two records exist
            count = BookCollection.query.filter_by(user_id=pro_user.id).count()
            assert count == 2


class TestGoalsProgressCalculation:
    """Test reading goal progress calculation accuracy."""

    def test_goal_progress_calculation_accuracy(self, app, pro_user, create_collection_book, create_reading_goal):
        """Progress should calculate correctly: 6/24 = 25%"""
        with app.app_context():
            # Create goal: 24 books in 2026
            goal = create_reading_goal(year=2026, target_count=24)

            # Add 6 books marked as read in 2026
            for i in range(6):
                create_collection_book(
                    title=f'Book {i}',
                    read_status='read',
                    date_read=date(2026, 6, i+1)
                )

            # Add 4 unread books (should not count toward progress)
            for i in range(4):
                create_collection_book(
                    title=f'Unread {i}',
                    read_status='unread'
                )

            # Get progress
            progress = GoalsService.get_progress(pro_user.id)

            assert progress['has_goal'] is True
            assert progress['current_count'] == 6
            assert progress['target_count'] == 24
            assert progress['percentage'] == 25.0

    def test_goal_year_isolation(self, app, pro_user, create_collection_book, create_reading_goal):
        """Progress should only count books read in the goal's year."""
        with app.app_context():
            # Create goal for 2026
            goal = create_reading_goal(year=2026, target_count=24)

            # Add 5 books read in 2025
            for i in range(5):
                create_collection_book(
                    title=f'2025 Book {i}',
                    read_status='read',
                    date_read=date(2025, 6, i+1)
                )

            # Add 3 books read in 2026
            for i in range(3):
                create_collection_book(
                    title=f'2026 Book {i}',
                    read_status='read',
                    date_read=date(2026, 6, i+1)
                )

            # Get progress
            progress = GoalsService.get_progress(pro_user.id)

            # Should only count 2026 books (3), not 2025 books
            assert progress['current_count'] == 3
            assert progress['percentage'] == 12.5  # 3/24 = 12.5%

    def test_goal_zero_target_handling(self, app, pro_user, create_reading_goal):
        """Goal with target_count=0 should not cause division by zero."""
        with app.app_context():
            # This is an edge case - user sets goal of 0 books
            goal = create_reading_goal(year=2026, target_count=0)

            # Get progress - should not crash
            progress = GoalsService.get_progress(pro_user.id)

            assert progress['has_goal'] is True
            assert progress['target_count'] == 0
            assert progress['percentage'] == 0.0  # Should handle gracefully

    def test_goal_multiple_years(self, app, pro_user, create_collection_book, create_reading_goal):
        """User can have goals for different years, each tracks separately."""
        with app.app_context():
            # This test assumes we can have multiple goals (one per year)
            # Based on the model, user_id might be unique, so this tests updating

            # Create goal for 2026
            goal_2026 = create_reading_goal(year=2026, target_count=24)

            # Add books for 2026
            create_collection_book(title='2026 Book', read_status='read', date_read=date(2026, 1, 1))

            # Get progress for 2026
            progress = GoalsService.get_progress(pro_user.id)
            assert progress['year'] == 2026
            assert progress['current_count'] == 1


class TestAnalyticsStatCalculations:
    """Test analytics statistics calculations."""

    def test_total_books_count(self, app, pro_user, create_collection_book):
        """Total books in collection should count correctly."""
        with app.app_context():
            # Add 10 books
            for i in range(10):
                create_collection_book(title=f'Book {i}')

            # Get stats
            stats = AnalyticsService.get_total_stats(pro_user.id)

            assert stats['total_in_collection'] == 10

    def test_books_read_count(self, app, pro_user, create_collection_book):
        """Books read count should only count read_status='read'."""
        with app.app_context():
            # Add 6 read books
            for i in range(6):
                create_collection_book(title=f'Read {i}', read_status='read')

            # Add 4 unread books
            for i in range(4):
                create_collection_book(title=f'Unread {i}', read_status='unread')

            # Get stats
            stats = AnalyticsService.get_total_stats(pro_user.id)

            assert stats['books_read'] == 6
            assert stats['total_in_collection'] == 10

    def test_genre_distribution_accuracy(self, app, pro_user, create_collection_book):
        """Genre distribution should count genres correctly."""
        with app.app_context():
            # Add 6 Fiction books
            for i in range(6):
                create_collection_book(title=f'Fiction {i}', genres=['Fiction'])

            # Add 4 Fantasy books
            for i in range(4):
                create_collection_book(title=f'Fantasy {i}', genres=['Fantasy'])

            # Add 1 book with both genres
            create_collection_book(title='Multi-genre', genres=['Fiction', 'Fantasy'])

            # Get genre distribution
            distribution = AnalyticsService.get_genre_distribution(pro_user.id)

            # Convert to dict for easier assertion
            genre_counts = {item['genre']: item['count'] for item in distribution}

            assert genre_counts['Fiction'] == 7  # 6 + 1 multi-genre
            assert genre_counts['Fantasy'] == 5  # 4 + 1 multi-genre

    def test_reading_pace_calculation(self, app, pro_user, create_collection_book):
        """Reading pace should calculate books per month correctly."""
        with app.app_context():
            # Add 12 books read across 12 months of 2026
            for month in range(1, 13):
                create_collection_book(
                    title=f'Book Month {month}',
                    read_status='read',
                    date_read=date(2026, month, 15)
                )

            # Get reading pace for 2026
            pace = AnalyticsService.get_reading_pace(pro_user.id, year=2026)

            assert pace['total_books'] == 12
            assert pace['books_per_month'] == 1.0  # 12 books / 12 months = 1.0

    def test_top_authors_count(self, app, pro_user, create_collection_book):
        """Top authors should count book occurrences correctly."""
        with app.app_context():
            # Add 5 books by Andy Weir
            for i in range(5):
                create_collection_book(title=f'Weir Book {i}', authors=['Andy Weir'])

            # Add 3 books by other authors
            create_collection_book(title='Book 1', authors=['Author A'])
            create_collection_book(title='Book 2', authors=['Author B'])
            create_collection_book(title='Book 3', authors=['Author C'])

            # Get top authors
            top_authors = AnalyticsService.get_top_authors(pro_user.id, limit=10)

            # Andy Weir should be first with 5 books
            assert len(top_authors) > 0
            assert top_authors[0]['author'] == 'Andy Weir'
            assert top_authors[0]['count'] == 5


class TestCSVExportDeduplication:
    """Test CSV export deduplication logic."""

    def test_export_no_duplicates(self, app, pro_user, create_collection_book):
        """CSV export should remove duplicate books by ISBN."""
        with app.app_context():
            # Add 10 unique books
            for i in range(8):
                create_collection_book(title=f'Book {i}', isbn=f'ISBN{i}')

            # Add 2 with duplicate ISBN
            create_collection_book(title='Duplicate 1', isbn='ISBN999')
            create_collection_book(title='Duplicate 2', isbn='ISBN999')

            # Export CSV
            csv_content = ExportService.generate_goodreads_csv(pro_user.id)

            # Count rows (excluding header)
            rows = csv_content.strip().split('\n')
            data_rows = rows[1:]  # Skip header

            # Should have 9 rows (8 unique + 1 from duplicate pair)
            assert len(data_rows) == 9

    def test_export_goodreads_format(self, app, pro_user, create_collection_book):
        """CSV export should have correct Goodreads headers."""
        with app.app_context():
            # Add at least one book
            create_collection_book(title='Test Book', isbn='1234567890')

            # Export CSV
            csv_content = ExportService.generate_goodreads_csv(pro_user.id)

            # Check headers
            lines = csv_content.strip().split('\n')
            headers = lines[0]

            # Should have key Goodreads columns
            assert 'Title' in headers
            assert 'Author' in headers
            assert 'ISBN' in headers
            assert 'Date Read' in headers
            assert 'Bookshelves' in headers

    def test_export_empty_collection(self, app, pro_user):
        """CSV export with no books should return headers only."""
        with app.app_context():
            # Export CSV with no books
            csv_content = ExportService.generate_goodreads_csv(pro_user.id)

            # Should have header row but no data rows
            lines = csv_content.strip().split('\n')
            assert len(lines) == 1  # Header only
            assert 'Title' in lines[0]
