"""
Enhanced Google Books search filtering to prevent weird/irrelevant results
"""

import re
from typing import List, Dict, Any, Optional
from datetime import datetime

class GoogleBooksFilter:
    """Filter Google Books results to remove weird, irrelevant, or low-quality results"""
    
    def __init__(self):
        # Categories of books that are NOT suitable for TikTok book discovery
        self.excluded_categories = {
            # Academic/Educational
            'academic', 'textbook', 'reference', 'study guide', 'workbook',
            'coursework', 'curriculum', 'educational', 'scholarly', 'thesis',
            'dissertation', 'journal', 'proceedings', 'conference', 'symposium',
            
            # Technical/Professional
            'manual', 'handbook', 'documentation', 'technical', 'programming',
            'software', 'computer science', 'engineering', 'medical', 'legal',
            'business', 'finance', 'accounting', 'law', 'medicine', 'science',
            
            # Government/Official
            'government', 'policy', 'regulation', 'statute', 'code', 'act',
            'bill', 'congress', 'senate', 'house', 'federal', 'state', 'municipal',
            'public documents', 'census', 'statistics', 'data', 'report',
            
            # Religious/Philosophical (unless mainstream)
            'theology', 'doctrine', 'scripture', 'sermon', 'liturgy', 'prayer',
            'catechism', 'philosophy', 'metaphysics', 'epistemology',
            
            # Outdated/Historical Documents
            'historical documents', 'archive', 'manuscript', 'facsimile',
            'reprint', 'reproduction', 'transactions', 'annals', 'chronicle'
        }
        
        # Red flag titles/descriptions - MINIMAL filtering for obvious junk only
        self.red_flag_patterns = [
            # Only block obvious summaries
            r'\bsummary\s+of\s+.+\bby\b', r'\bplot\s+summary\s+of\b',
            
            # Only block obvious study materials
            r'\bstudy\s+guide\s+for\b', r'\bworkbook\b',
            
            # Only block obvious government documents
            r'\bfederal\s+register\b', r'\bcongressional\s+record\b',
            r'\bpublic\s+law\s+\d+\b', r'\bstatute\s+\d+\b'
        ]
        
        # Publishers that often have weird/irrelevant results - MINIMAL list
        self.problematic_publishers = {
            # Only obvious government/document publishers
            'government printing office', 'u.s. government printing office',
            'federal register', 'congressional printing office',
            
            # Only obvious academic document publishers
            'university microfilms', 'dissertation abstracts'
        }
        
        # Minimum standards for book quality
        self.min_title_length = 2  # Allow short titles like "It" by Stephen King
        self.min_description_length = 10  # Relax description requirement
        self.max_title_length = 200  # Titles shouldn't be essays
        
    def filter_google_books_results(self, books: List[Dict[str, Any]], 
                                   original_query: str = "") -> List[Dict[str, Any]]:
        """Filter Google Books results to remove weird/irrelevant books"""
        if not books:
            return books
        
        print(f"🔍 Pre-filtering {len(books)} Google Books results...")
        
        filtered_books = []
        for book in books:
            if self._is_book_acceptable(book, original_query):
                filtered_books.append(book)
            else:
                title = book.get('title', 'Unknown')[:50]
                reason = self._get_rejection_reason(book)
                print(f"❌ Rejected: '{title}' ({reason})")
        
        print(f"✅ Kept {len(filtered_books)} acceptable books after pre-filtering")
        return filtered_books
    
    def _is_book_acceptable(self, book: Dict[str, Any], original_query: str = "") -> bool:
        """Check if a book meets basic quality standards for TikTok discovery"""
        
        title = book.get('title', '').lower()
        description = book.get('description', '').lower()
        authors = [a.lower() for a in book.get('authors', [])]
        publisher = book.get('publisher', '').lower()
        published_date = book.get('published_date', '')
        
        # 1. Basic data quality checks
        if not self._has_basic_quality(book):
            return False
        
        # 2. Check for red flag patterns in title/description
        if self._has_red_flag_patterns(title, description):
            return False
        
        # 3. Check for problematic publishers
        if self._is_problematic_publisher(publisher):
            return False
        
        # 4. Check for academic/technical categories
        if self._is_academic_or_technical(title, description, publisher):
            return False
        
        # 5. Check for government/official documents
        if self._is_government_document(title, description, publisher):
            return False
        
        # 6. Check publication date (avoid very old or weird dates)
        if not self._has_reasonable_publication_date(published_date):
            return False
        
        # 7. Check if title is reasonable for a consumer book
        if not self._is_consumer_book_title(title):
            return False
        
        return True
    
    def _has_basic_quality(self, book: Dict[str, Any]) -> bool:
        """Check basic data quality requirements"""
        title = book.get('title', '')
        description = book.get('description', '')
        authors = book.get('authors', [])
        
        # Must have title
        if not title or len(title.strip()) < self.min_title_length:
            return False
        
        # Title shouldn't be absurdly long
        if len(title) > self.max_title_length:
            return False
        
        # Should have authors (most legitimate books do)
        if not authors:
            return False
        
        # Description should exist and be reasonable
        if description and len(description) < self.min_description_length:
            # Very short descriptions are often low quality
            return False
        
        return True
    
    def _has_red_flag_patterns(self, title: str, description: str) -> bool:
        """Check for red flag patterns that indicate weird results"""
        content = f"{title} {description}"
        
        for pattern in self.red_flag_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        
        return False
    
    def _is_problematic_publisher(self, publisher: str) -> bool:
        """Check if publisher is known to have weird results"""
        for problematic in self.problematic_publishers:
            if problematic in publisher:
                return True
        return False
    
    def _is_academic_or_technical(self, title: str, description: str, publisher: str) -> bool:
        """Check if this is an academic or technical publication - MUCH more selective"""
        content = f"{title} {description} {publisher}"
        
        # Only block clearly academic indicators - be much more selective
        strict_academic_indicators = [
            'university press', 'academic press', 'textbook',
            'coursework', 'curriculum', 'syllabus', 'peer review',
            'proceedings of', 'conference proceedings', 'journal of'
        ]
        
        # Don't block books just because they have "scholarly" or general terms
        for indicator in strict_academic_indicators:
            if indicator in content:
                return True
        
        return False
    
    def _is_government_document(self, title: str, description: str, publisher: str) -> bool:
        """Check if this is a government or official document"""
        content = f"{title} {description} {publisher}"
        
        # Government indicators
        gov_indicators = [
            'government printing', 'federal register', 'congressional',
            'house of representatives', 'senate', 'department of',
            'bureau of', 'office of', 'public law', 'statute',
            'regulation', 'code of federal', 'municipal code'
        ]
        
        for indicator in gov_indicators:
            if indicator in content:
                return True
        
        return False
    
    def _has_reasonable_publication_date(self, published_date: str) -> bool:
        """Check if publication date is reasonable for consumer books"""
        if not published_date:
            return True  # Missing date is okay
        
        try:
            # Extract year
            year_match = re.search(r'\d{4}', published_date)
            if not year_match:
                return True  # Can't parse, allow it
            
            year = int(year_match.group())
            current_year = datetime.now().year
            
            # Reasonable range: 1900 to current year + 2
            if year < 1900 or year > current_year + 2:
                return False
            
            return True
            
        except (ValueError, AttributeError):
            return True  # If we can't parse, allow it
    
    def _is_consumer_book_title(self, title: str) -> bool:
        """Check if title looks like a consumer book rather than academic/technical"""
        
        # Titles that are clearly not consumer books
        non_consumer_patterns = [
            r'^proceedings of', r'^transactions of', r'^journal of',
            r'^handbook of', r'^manual of', r'^guide to',
            r'^introduction to', r'^fundamentals of', r'^principles of',
            r'^code of', r'^regulations of', r'^laws of',
            r'^report on', r'^study of', r'^analysis of',
            r'^annual report', r'^quarterly report', r'^monthly report'
        ]
        
        for pattern in non_consumer_patterns:
            if re.match(pattern, title, re.IGNORECASE):
                return False
        
        # Titles with too many numbers/codes (likely technical)
        number_matches = len(re.findall(r'\b\d+\b', title))
        if number_matches > 3:  # Too many numbers
            return False
        
        # Very technical abbreviations
        if re.search(r'\b[A-Z]{4,}\b', title):  # 4+ consecutive caps
            tech_count = len(re.findall(r'\b[A-Z]{4,}\b', title))
            if tech_count > 2:  # Too many technical abbreviations
                return False
        
        return True
    
    def _get_rejection_reason(self, book: Dict[str, Any]) -> str:
        """Get human-readable reason why book was rejected"""
        title = book.get('title', '').lower()
        description = book.get('description', '').lower()
        publisher = book.get('publisher', '').lower()
        
        # Check reasons in order of likelihood
        if not book.get('title') or len(book.get('title', '').strip()) < 3:
            return "no/short title"
        
        if not book.get('authors'):
            return "no authors"
        
        if any(pattern in publisher for pattern in ['government', 'department of', 'bureau of']):
            return "government publisher"
        
        content = f"{title} {description}"
        if re.search(r'\bsummary\s+of\b', content):
            return "summary/study guide"
        
        if re.search(r'\btextbook\b|\bhandbook\b|\bmanual\b', content):
            return "textbook/manual"
        
        if re.search(r'\bproceedings\b|\bjournal\b|\bconference\b', content):
            return "academic publication"
        
        return "quality standards"

def create_google_books_filter() -> GoogleBooksFilter:
    """Create a Google Books filter instance"""
    return GoogleBooksFilter()