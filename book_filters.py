"""
Book quality and popularity filtering for TikTok trending books
"""

import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from fuzzywuzzy import fuzz

class BookQualityFilter:
    """Filter books based on popularity, quality, and TikTok trending indicators"""
    
    def __init__(self):
        # Popular publishers that indicate mainstream/popular books
        self.major_publishers = {
            'penguin', 'random house', 'harper', 'macmillan', 'simon & schuster',
            'hachette', 'scholastic', 'bantam', 'dell', 'anchor', 'vintage',
            'ballantine', 'berkley', 'crown', 'doubleday', 'dutton', 'gallery',
            'grand central', 'henry holt', 'knopf', 'little brown', 'tor',
            'st. martin', 'william morrow', 'atria', 'avon', 'scribner'
        }
        
        # Genres popular on TikTok (BookTok)
        self.booktok_genres = {
            'fiction', 'romance', 'fantasy', 'young adult', 'ya', 'teen',
            'contemporary', 'historical fiction', 'mystery', 'thriller',
            'science fiction', 'dystopian', 'paranormal', 'urban fantasy',
            'dark academia', 'enemies to lovers', 'friends to lovers'
        }
        
        # Keywords that indicate popular/trending books
        self.popularity_keywords = {
            'bestseller', 'best seller', 'award', 'winner', 'novel', 'series',
            'trilogy', 'saga', 'book club', 'adaptation', 'movie', 'netflix',
            'tiktok', 'booktok', 'viral', 'trending', 'popular', 'hit'
        }
        
        # Red flags for low-quality or non-mainstream books
        self.quality_red_flags = {
            'self-published', 'createspace', 'kindle direct', 'draft2digital',
            'independently published', 'author house', 'xlibris', 'trafford',
            'iuniverse', 'outskirts press', 'lulu', 'blurb', 'smashwords',
            'print on demand', 'pod', 'vanity press'
        }
        
        # Publication recency for trending books (TikTok favors newer books)
        self.current_year = datetime.now().year
        
    def filter_books(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter and rank books by quality and popularity indicators"""
        if not books:
            return books
        
        print(f"🔍 Filtering {len(books)} books for quality and popularity...")
        
        # Score each book
        scored_books = []
        for book in books:
            score = self._calculate_book_score(book)
            if score > 0.3:  # Minimum quality threshold
                book_copy = book.copy()
                book_copy['popularity_score'] = score
                book_copy['filter_reasons'] = self._get_score_breakdown(book)
                scored_books.append(book_copy)
        
        # Sort by score (highest first)
        scored_books.sort(key=lambda b: b['popularity_score'], reverse=True)
        
        # Limit to top results
        max_results = min(len(scored_books), 8)  # Focus on best results
        filtered_books = scored_books[:max_results]
        
        print(f"✅ Filtered to {len(filtered_books)} high-quality books")
        if filtered_books:
            scores = [f"{b['popularity_score']:.2f}" for b in filtered_books[:3]]
            print(f"📊 Top scores: {scores}")
        
        return filtered_books
    
    def _calculate_book_score(self, book: Dict[str, Any]) -> float:
        """Calculate popularity/quality score for a book"""
        score = 0.0
        
        title = book.get('title', '').lower()
        authors = [a.lower() for a in book.get('authors', [])]
        description = book.get('description', '').lower()
        published_date = book.get('published_date', '')
        
        # 1. Publication recency (TikTok loves newer books)
        recency_score = self._score_publication_recency(published_date)
        score += recency_score * 0.2
        
        # 2. Publisher quality (major publishers = more popular)
        publisher_score = self._score_publisher_quality(book)
        score += publisher_score * 0.25
        
        # 3. Title/description popularity indicators
        content_score = self._score_content_popularity(title, description)
        score += content_score * 0.2
        
        # 4. BookTok genre alignment
        genre_score = self._score_booktok_genres(title, description, authors)
        score += genre_score * 0.15
        
        # 5. Author popularity indicators
        author_score = self._score_author_popularity(authors, description)
        score += author_score * 0.1
        
        # 6. Red flag penalties (self-published, vanity press, etc.)
        penalty = self._calculate_quality_penalties(book, description)
        score -= penalty
        
        # 7. Bonus for complete metadata (popular books have good data)
        metadata_bonus = self._score_metadata_completeness(book)
        score += metadata_bonus * 0.1
        
        return max(0.0, min(1.0, score))  # Clamp to [0, 1]
    
    def _score_publication_recency(self, published_date: str) -> float:
        """Score based on publication recency (newer = higher score)"""
        if not published_date:
            return 0.3  # Neutral for missing date
        
        try:
            # Extract year from various date formats
            year_match = re.search(r'\d{4}', published_date)
            if not year_match:
                return 0.3
            
            pub_year = int(year_match.group())
            
            # Score based on how recent the book is
            years_ago = self.current_year - pub_year
            
            if years_ago <= 2:  # Very recent (2022+)
                return 1.0
            elif years_ago <= 5:  # Recent (2019+) 
                return 0.8
            elif years_ago <= 10:  # Moderately recent (2014+)
                return 0.6
            elif years_ago <= 20:  # Older but could be trendy (2004+)
                return 0.4
            else:  # Very old
                return 0.2
                
        except (ValueError, AttributeError):
            return 0.3
    
    def _score_publisher_quality(self, book: Dict[str, Any]) -> float:
        """Score based on publisher reputation"""
        publisher = book.get('publisher', '').lower()
        if not publisher:
            return 0.3  # Neutral for missing publisher
        
        # Check for major publishers
        for major_pub in self.major_publishers:
            if major_pub in publisher:
                return 1.0
        
        # Check for red flag publishers
        for red_flag in self.quality_red_flags:
            if red_flag in publisher:
                return 0.1
        
        # Unknown publisher - neutral score
        return 0.5
    
    def _score_content_popularity(self, title: str, description: str) -> float:
        """Score based on popularity keywords in title/description"""
        content = f"{title} {description}"
        score = 0.0
        
        for keyword in self.popularity_keywords:
            if keyword in content:
                if keyword in ['bestseller', 'best seller', 'award', 'winner']:
                    score += 0.3  # High value keywords
                elif keyword in ['novel', 'series', 'trilogy']:
                    score += 0.2  # Medium value keywords
                else:
                    score += 0.1  # Lower value keywords
        
        return min(1.0, score)
    
    def _score_booktok_genres(self, title: str, description: str, authors: List[str]) -> float:
        """Score based on BookTok-popular genres"""
        content = f"{title} {description} {' '.join(authors)}"
        score = 0.0
        
        for genre in self.booktok_genres:
            if genre in content:
                if genre in ['young adult', 'ya', 'romance', 'fantasy']:
                    score += 0.3  # Very popular on BookTok
                elif genre in ['contemporary', 'fiction', 'mystery']:
                    score += 0.2  # Popular on BookTok
                else:
                    score += 0.1  # Somewhat popular
        
        return min(1.0, score)
    
    def _score_author_popularity(self, authors: List[str], description: str) -> float:
        """Score based on author popularity indicators"""
        if not authors:
            return 0.3
        
        score = 0.0
        content = f"{' '.join(authors)} {description}".lower()
        
        # Check for multi-book authors (usually more popular)
        author_indicators = ['author of', 'wrote', 'written by', 'bestselling']
        for indicator in author_indicators:
            if indicator in content:
                score += 0.2
        
        # Check for award-winning authors
        award_indicators = ['award', 'winner', 'prize', 'nominee']
        for indicator in award_indicators:
            if indicator in content:
                score += 0.3
        
        return min(1.0, score)
    
    def _calculate_quality_penalties(self, book: Dict[str, Any], description: str) -> float:
        """Calculate penalties for quality red flags"""
        penalty = 0.0
        
        publisher = book.get('publisher', '').lower()
        content = f"{publisher} {description}".lower()
        
        # Check for self-publishing red flags
        for red_flag in self.quality_red_flags:
            if red_flag in content:
                penalty += 0.4  # Heavy penalty
        
        # Missing critical metadata penalty
        if not book.get('description'):
            penalty += 0.1
        if not book.get('authors'):
            penalty += 0.1
        if not book.get('published_date'):
            penalty += 0.05
        
        return penalty
    
    def _score_metadata_completeness(self, book: Dict[str, Any]) -> float:
        """Bonus for complete book metadata (popular books have good data)"""
        score = 0.0
        
        # Check for presence of various metadata fields
        metadata_fields = [
            'title', 'authors', 'description', 'published_date', 
            'thumbnail', 'publisher', 'isbn'
        ]
        
        present_fields = sum(1 for field in metadata_fields if book.get(field))
        completeness_ratio = present_fields / len(metadata_fields)
        
        score += completeness_ratio * 0.5
        
        # Bonus for rich description
        description = book.get('description', '')
        if len(description) > 100:
            score += 0.3
        elif len(description) > 50:
            score += 0.2
        
        return min(1.0, score)
    
    def _get_score_breakdown(self, book: Dict[str, Any]) -> Dict[str, float]:
        """Get detailed score breakdown for debugging"""
        title = book.get('title', '').lower()
        authors = [a.lower() for a in book.get('authors', [])]
        description = book.get('description', '').lower()
        published_date = book.get('published_date', '')
        
        breakdown = {
            'recency': self._score_publication_recency(published_date),
            'publisher': self._score_publisher_quality(book),
            'content_popularity': self._score_content_popularity(title, description),
            'booktok_genre': self._score_booktok_genres(title, description, authors),
            'author_popularity': self._score_author_popularity(authors, description),
            'metadata_completeness': self._score_metadata_completeness(book),
            'quality_penalty': self._calculate_quality_penalties(book, description)
        }
        
        return breakdown

class TrendingBookDetector:
    """Additional logic to identify books that are likely trending on TikTok"""
    
    def __init__(self):
        # Authors popular on BookTok
        self.booktok_authors = {
            'colleen hoover', 'taylor jenkins reid', 'emily henry', 'ali hazelwood',
            'casey mcquiston', 'madeline miller', 'leigh bardugo', 'sarah j. maas',
            'jennifer l. armentrout', 'rebecca yarros', 'ana huang', 'elle kennedy',
            'christina lauren', 'tessa bailey', 'mariana zapata', 'vi keeland',
            'penelope douglas', 'l.j. shen', 'tillie cole', 'sam mariano'
        }
        
        # Books that have been viral on TikTok
        self.viral_books = {
            'it ends with us', 'book lovers', 'november 9', 'ugly love',
            'the seven husbands of evelyn hugo', 'beach read', 'people we meet on vacation',
            'red queen', 'six of crows', 'a court of thorns and roses', 'throne of glass',
            'from blood and ash', 'fourth wing', 'iron flame', 'twisted love',
            'the song of achilles', 'circe', 'the invisible life of addie larue'
        }
    
    def boost_trending_books(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply additional scoring boost for known trending books/authors"""
        
        for book in books:
            title = book.get('title', '').lower()
            authors = [a.lower() for a in book.get('authors', [])]
            
            # Boost for BookTok authors
            for author in authors:
                for booktok_author in self.booktok_authors:
                    if fuzz.ratio(author, booktok_author) > 85:
                        book['popularity_score'] = min(1.0, book.get('popularity_score', 0) + 0.2)
                        book['trending_boost'] = 'popular_author'
                        break
            
            # Boost for viral books
            for viral_book in self.viral_books:
                if fuzz.ratio(title, viral_book) > 80:
                    book['popularity_score'] = min(1.0, book.get('popularity_score', 0) + 0.3)
                    book['trending_boost'] = 'viral_book'
                    break
        
        return books

def create_book_filter() -> BookQualityFilter:
    """Create a book quality filter instance"""
    return BookQualityFilter()

def create_trending_detector() -> TrendingBookDetector:
    """Create a trending book detector instance"""
    return TrendingBookDetector()