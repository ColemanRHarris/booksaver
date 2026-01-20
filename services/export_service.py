"""
Export Service - Generate CSV exports of user's book collection.
"""

import csv
import io
from typing import List, Dict
from models.book_collection import BookCollection
from datetime import datetime


class ExportService:
    """Service for exporting book collections to various formats."""

    @staticmethod
    def generate_goodreads_csv(user_id: int) -> str:
        """
        Generate a Goodreads-compatible CSV export of user's collection.

        Format matches Goodreads export with standard columns:
        - Title, Author, ISBN/ISBN13, My Rating, Date Read, Bookshelves, etc.

        Args:
            user_id: User ID to export collection for

        Returns:
            CSV string ready for download
        """
        # Query all books in user's collection
        books = BookCollection.query.filter_by(user_id=user_id)\
            .order_by(BookCollection.added_at.desc())\
            .all()

        # Deduplicate by ISBN (prefer first occurrence)
        seen_isbns = set()
        seen_titles = set()
        unique_books = []

        for book in books:
            # Dedup by ISBN if available
            if book.isbn:
                if book.isbn in seen_isbns:
                    continue
                seen_isbns.add(book.isbn)
            else:
                # Fallback: dedup by title+first author
                authors_display = book.get_authors_display()
                dedup_key = f"{book.title}|{authors_display}".lower()
                if dedup_key in seen_titles:
                    continue
                seen_titles.add(dedup_key)

            unique_books.append(book)

        # Generate CSV in memory
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header row (Goodreads standard columns)
        writer.writerow([
            'Title',
            'Author',
            'Author l-f',  # Last name, First name format
            'Additional Authors',
            'ISBN',
            'ISBN13',
            'My Rating',
            'Average Rating',
            'Publisher',
            'Binding',
            'Number of Pages',
            'Year Published',
            'Original Publication Year',
            'Date Read',
            'Date Added',
            'Bookshelves',
            'Bookshelves with positions',
            'Exclusive Shelf',
            'My Review',
            'Spoiler',
            'Private Notes',
            'Read Count',
            'Recommended For',
            'Recommended By',
            'Owned Copies',
            'Original Purchase Date',
            'Original Purchase Location',
            'Condition',
            'Condition Description',
            'BCID'
        ])

        # Write data rows
        for book in unique_books:
            # Format authors
            authors = book.authors
            author_main = authors[0] if authors else 'Unknown Author'
            author_lf = ExportService._format_author_last_first(author_main)
            additional_authors = ', '.join(authors[1:]) if len(authors) > 1 else ''

            # Format dates
            date_read = book.date_read.strftime('%Y/%m/%d') if book.date_read else ''
            date_added = book.added_at.strftime('%Y/%m/%d') if book.added_at else ''

            # Format shelf names for Goodreads
            shelf_name = book.shelf.replace('_', '-')  # want_to_read -> want-to-read
            exclusive_shelf = ExportService._map_shelf_to_goodreads(book.shelf)

            # Format year published
            year_published = ''
            if book.published_date:
                try:
                    # Try to extract year from published_date (could be various formats)
                    if isinstance(book.published_date, str):
                        # Try common formats: "2023", "2023-01-15", "January 2023"
                        if book.published_date.isdigit() and len(book.published_date) == 4:
                            year_published = book.published_date
                        elif '-' in book.published_date:
                            year_published = book.published_date.split('-')[0]
                        else:
                            # Try to extract 4-digit year from string
                            import re
                            year_match = re.search(r'\b(19|20)\d{2}\b', book.published_date)
                            if year_match:
                                year_published = year_match.group(0)
                except:
                    pass

            writer.writerow([
                book.title,
                author_main,
                author_lf,
                additional_authors,
                book.isbn or '',
                book.isbn or '',  # Use same ISBN for ISBN13 if available
                '',  # My Rating (not tracked)
                '',  # Average Rating (not available)
                '',  # Publisher (not tracked)
                '',  # Binding (not tracked)
                '',  # Number of Pages (not tracked)
                year_published,
                year_published,  # Use same for both published fields
                date_read,
                date_added,
                shelf_name,
                shelf_name,
                exclusive_shelf,
                '',  # My Review (not tracked)
                '',  # Spoiler
                '',  # Private Notes
                '1' if book.read_status == 'read' else '0',  # Read Count
                '',  # Recommended For
                '',  # Recommended By
                '',  # Owned Copies
                '',  # Original Purchase Date
                '',  # Original Purchase Location
                '',  # Condition
                '',  # Condition Description
                ''   # BCID
            ])

        # Get CSV string
        csv_content = output.getvalue()
        output.close()

        return csv_content

    @staticmethod
    def _format_author_last_first(author: str) -> str:
        """
        Convert author name to 'Last, First' format.

        Args:
            author: Author name in any format

        Returns:
            Author name in 'Last, First' format
        """
        if not author or ',' in author:
            # Already in last, first format or invalid
            return author

        parts = author.strip().split()
        if len(parts) == 0:
            return author
        elif len(parts) == 1:
            return author
        elif len(parts) == 2:
            return f"{parts[1]}, {parts[0]}"
        else:
            # More than 2 parts: assume last name is the final part
            last = parts[-1]
            first = ' '.join(parts[:-1])
            return f"{last}, {first}"

    @staticmethod
    def _map_shelf_to_goodreads(shelf: str) -> str:
        """
        Map internal shelf names to Goodreads exclusive shelf names.

        Args:
            shelf: Internal shelf name (want_to_read, currently_reading, read)

        Returns:
            Goodreads shelf name (to-read, currently-reading, read)
        """
        mapping = {
            'want_to_read': 'to-read',
            'currently_reading': 'currently-reading',
            'read': 'read'
        }
        return mapping.get(shelf, 'to-read')

    @staticmethod
    def get_export_stats(user_id: int) -> Dict:
        """
        Get statistics about what will be exported.

        Args:
            user_id: User ID

        Returns:
            Dict with export statistics
        """
        books = BookCollection.query.filter_by(user_id=user_id).all()

        # Count deduplicated books
        seen_isbns = set()
        seen_titles = set()
        unique_count = 0

        for book in books:
            if book.isbn:
                if book.isbn not in seen_isbns:
                    unique_count += 1
                    seen_isbns.add(book.isbn)
            else:
                authors_display = book.get_authors_display()
                dedup_key = f"{book.title}|{authors_display}".lower()
                if dedup_key not in seen_titles:
                    unique_count += 1
                    seen_titles.add(dedup_key)

        return {
            'total_in_collection': len(books),
            'unique_books': unique_count,
            'duplicates_removed': len(books) - unique_count
        }
