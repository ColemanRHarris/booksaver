"""
Consolidated book filtering and search system for BookSaver.
Includes quality filtering, language detection, fuzzy search, and Google Books integration.
"""

import re
import time
import requests
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
from fuzzywuzzy import fuzz, process
from langdetect import detect, LangDetectException
from services.books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links


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
        filtered_books = []
        
        for book in books:
            score = self._calculate_quality_score(book)
            if score > 0:  # Only include books with positive quality scores
                book_copy = book.copy()
                book_copy['quality_score'] = score
                book_copy['quality_reasons'] = self._get_quality_reasons(book)
                filtered_books.append(book_copy)
        
        # Sort by quality score (highest first)
        filtered_books.sort(key=lambda x: x.get('quality_score', 0), reverse=True)
        
        # Limit to top results to avoid overwhelming users
        return filtered_books[:10]
    
    def _calculate_quality_score(self, book: Dict[str, Any]) -> float:
        """Calculate quality score for a book (0-100 scale)"""
        score = 50  # Base score
        
        # Check publisher quality
        publisher = book.get('publisher', '').lower()
        if any(pub in publisher for pub in self.major_publishers):
            score += 20
        
        # Check for quality red flags
        description = f"{book.get('description', '')} {publisher}".lower()
        if any(flag in description for flag in self.quality_red_flags):
            score -= 30
        
        # Genre popularity (BookTok relevance)
        categories = ' '.join(book.get('categories', [])).lower()
        genre_matches = sum(1 for genre in self.booktok_genres if genre in categories)
        score += min(genre_matches * 5, 15)  # Max 15 points for genres
        
        # Popularity keywords in title/description
        text = f"{book.get('title', '')} {description}".lower()
        keyword_matches = sum(1 for keyword in self.popularity_keywords if keyword in text)
        score += min(keyword_matches * 3, 12)  # Max 12 points for keywords
        
        # Publication recency (favor recent books for TikTok trends)
        pub_date = book.get('published_date', '')
        if pub_date:
            try:
                pub_year = int(pub_date[:4])
                years_old = self.current_year - pub_year
                if years_old <= 2:
                    score += 10  # Very recent
                elif years_old <= 5:
                    score += 5   # Recent
                elif years_old > 20:
                    score -= 5   # Older books less likely to trend
            except (ValueError, IndexError):
                pass  # Invalid date format
        
        # Rating boost
        rating = book.get('average_rating', 0)
        if rating >= 4.5:
            score += 8
        elif rating >= 4.0:
            score += 5
        elif rating >= 3.5:
            score += 2
        elif rating < 3.0 and rating > 0:
            score -= 5
        
        # Review count (popularity indicator)
        review_count = book.get('ratings_count', 0)
        if review_count >= 10000:
            score += 8
        elif review_count >= 1000:
            score += 5
        elif review_count >= 100:
            score += 2
        elif review_count < 10:
            score -= 3
        
        return max(0, score)  # Don't allow negative scores
    
    def _get_quality_reasons(self, book: Dict[str, Any]) -> List[str]:
        """Get human-readable reasons for quality score"""
        reasons = []
        
        publisher = book.get('publisher', '').lower()
        if any(pub in publisher for pub in self.major_publishers):
            reasons.append("Major publisher")
        
        categories = ' '.join(book.get('categories', [])).lower()
        if any(genre in categories for genre in self.booktok_genres):
            reasons.append("Popular genre")
        
        rating = book.get('average_rating', 0)
        if rating >= 4.0:
            reasons.append(f"High rating ({rating}/5)")
        
        review_count = book.get('ratings_count', 0)
        if review_count >= 1000:
            reasons.append(f"Many reviews ({review_count:,})")
        
        pub_date = book.get('published_date', '')
        if pub_date:
            try:
                pub_year = int(pub_date[:4])
                if self.current_year - pub_year <= 2:
                    reasons.append("Recently published")
            except (ValueError, IndexError):
                pass
        
        return reasons


class LanguageFilter:
    """Filter books by language preference and detect book languages"""
    
    def __init__(self, preferred_languages: List[str] = None):
        # Default to English if no preferences specified
        self.preferred_languages = preferred_languages or ['en', 'english']
        
        # Language code mappings
        self.language_codes = {
            'en': 'english', 'es': 'spanish', 'fr': 'french', 'de': 'german',
            'it': 'italian', 'pt': 'portuguese', 'ru': 'russian', 'ja': 'japanese',
            'ko': 'korean', 'zh': 'chinese', 'ar': 'arabic', 'hi': 'hindi'
        }
        
        # Reverse mapping for language names to codes
        self.language_names = {v: k for k, v in self.language_codes.items()}
        
        # Common non-English words/patterns that might appear in titles
        self.language_patterns = {
            'spanish': ['de', 'el', 'la', 'los', 'las', 'del', 'y', 'en', 'con', 'para'],
            'french': ['de', 'le', 'la', 'les', 'du', 'des', 'et', 'en', 'avec', 'pour'],
            'german': ['der', 'die', 'das', 'den', 'dem', 'des', 'und', 'mit', 'für'],
            'italian': ['il', 'la', 'lo', 'gli', 'le', 'del', 'della', 'e', 'con', 'per'],
            'portuguese': ['o', 'a', 'os', 'as', 'do', 'da', 'dos', 'das', 'e', 'com']
        }
    
    def filter_books(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter books by language preference"""
        filtered_books = []
        
        for book in books:
            # Detect book language
            language = self._detect_book_language(book)
            
            # Add detected language to book metadata
            if language:
                book_copy = book.copy()
                book_copy['detected_language'] = language
                
                # Check if book matches preferred languages
                if self._matches_language_preference(language):
                    book_copy['language_match'] = True
                    filtered_books.append(book_copy)
                else:
                    book_copy['language_match'] = False
                    # Still include but mark as non-preferred (user might want it)
                    filtered_books.append(book_copy)
            else:
                # Unknown language - include with warning
                book_copy = book.copy()
                book_copy['detected_language'] = 'unknown'
                book_copy['language_match'] = False
                filtered_books.append(book_copy)
        
        # Sort by language preference (preferred languages first)
        filtered_books.sort(key=lambda x: x.get('language_match', False), reverse=True)
        
        return filtered_books
    
    def _detect_book_language(self, book: Dict[str, Any]) -> str:
        """Detect the language of a book using multiple methods"""
        # First check explicit language field from Google Books
        if 'language' in book and book['language']:
            lang_code = book['language'].lower()
            return self.language_codes.get(lang_code, lang_code)
        
        # Extract text for language detection
        text_samples = []
        
        # Use title
        if 'title' in book and book['title']:
            text_samples.append(book['title'])
        
        # Use subtitle if available
        if 'subtitle' in book and book['subtitle']:
            text_samples.append(book['subtitle'])
        
        # Use description snippet
        if 'description' in book and book['description']:
            # Use first 200 characters of description
            text_samples.append(book['description'][:200])
        
        # Combine text samples
        combined_text = ' '.join(text_samples)
        
        if not combined_text.strip():
            return None
        
        # Try automatic language detection
        try:
            detected_lang = detect(combined_text)
            return self.language_codes.get(detected_lang, detected_lang)
        except LangDetectException:
            pass
        
        # Fallback: pattern-based detection for common languages
        combined_lower = combined_text.lower()
        for language, patterns in self.language_patterns.items():
            pattern_matches = sum(1 for pattern in patterns if f' {pattern} ' in f' {combined_lower} ')
            if pattern_matches >= 2:  # Need at least 2 pattern matches
                return language
        
        # Default to English if no detection works
        return 'english'
    
    def _matches_language_preference(self, detected_language: str) -> bool:
        """Check if detected language matches user preferences"""
        if not detected_language:
            return False
        
        detected_lower = detected_language.lower()
        
        for pref_lang in self.preferred_languages:
            pref_lower = pref_lang.lower()
            
            # Direct match
            if detected_lower == pref_lower:
                return True
            
            # Code to name conversion
            if detected_lower in self.language_codes and self.language_codes[detected_lower] == pref_lower:
                return True
            
            # Name to code conversion
            if pref_lower in self.language_names and self.language_names[pref_lower] == detected_lower:
                return True
        
        return False
    
    def get_language_confidence(self, book: Dict[str, Any], detected_lang: str) -> float:
        """Calculate confidence score for language detection (0-100)"""
        confidence = 50  # Base confidence
        
        # Higher confidence if explicit language field exists
        if 'language' in book and book['language']:
            confidence += 30
        
        # Check pattern matches for additional confidence
        text = f"{book.get('title', '')} {book.get('description', '')[:100]}".lower()
        
        if detected_lang in self.language_patterns:
            patterns = self.language_patterns[detected_lang]
            matches = sum(1 for pattern in patterns if f' {pattern} ' in f' {text} ')
            confidence += min(matches * 5, 20)  # Up to 20 points for pattern matches
        
        return min(100, confidence)


class GoogleBooksFilter:
    """Advanced filtering using Google Books API data"""
    
    def __init__(self):
        # Initialize thresholds
        self.min_rating = 3.5
        self.min_reviews = 50
        self.recent_years = 15  # Books from last 15 years get boost
        
        # Genre preferences (can be customized)
        self.preferred_genres = {
            'fiction', 'mystery', 'romance', 'fantasy', 'science fiction',
            'thriller', 'young adult', 'historical fiction', 'contemporary',
            'literary fiction', 'horror', 'adventure'
        }
        
        # Subject filters to exclude
        self.exclude_subjects = {
            'textbook', 'academic', 'technical', 'manual', 'reference',
            'dictionary', 'encyclopedia', 'cookbook', 'children\'s books',
            'juvenile', 'educational', 'workbook', 'study guide'
        }
    
    def filter_books(self, books: List[Dict[str, Any]], user_preferences: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Filter books based on Google Books metadata and user preferences"""
        if not books:
            return []
        
        filtered_books = []
        user_prefs = user_preferences or {}
        
        for book in books:
            # Calculate comprehensive score
            score = self._calculate_book_score(book, user_prefs)
            
            if score > 0:  # Only include books with positive scores
                book_copy = book.copy()
                book_copy['google_score'] = score
                book_copy['filter_reasons'] = self._get_filter_reasons(book, user_prefs)
                filtered_books.append(book_copy)
        
        # Sort by score
        filtered_books.sort(key=lambda x: x.get('google_score', 0), reverse=True)
        
        # Apply final filters
        return self._apply_final_filters(filtered_books)
    
    def _calculate_book_score(self, book: Dict[str, Any], user_prefs: Dict[str, Any]) -> float:
        """Calculate comprehensive book score using Google Books data"""
        score = 0
        
        # Rating score (0-25 points)
        rating = book.get('average_rating', 0)
        if rating:
            if rating >= 4.5:
                score += 25
            elif rating >= 4.0:
                score += 20
            elif rating >= 3.5:
                score += 15
            elif rating >= 3.0:
                score += 10
            else:
                score += 5
        
        # Reviews count score (0-20 points)
        reviews = book.get('ratings_count', 0)
        if reviews:
            if reviews >= 10000:
                score += 20
            elif reviews >= 5000:
                score += 15
            elif reviews >= 1000:
                score += 12
            elif reviews >= 500:
                score += 8
            elif reviews >= 100:
                score += 5
            elif reviews >= 50:
                score += 3
        
        # Publication date score (0-15 points)
        pub_date = book.get('published_date')
        if pub_date:
            try:
                pub_year = int(pub_date.split('-')[0])
                current_year = datetime.now().year
                years_ago = current_year - pub_year
                
                if years_ago <= 2:
                    score += 15  # Very recent
                elif years_ago <= 5:
                    score += 12  # Recent
                elif years_ago <= 10:
                    score += 8   # Moderately recent
                elif years_ago <= self.recent_years:
                    score += 5   # Still relevant
                elif years_ago > 30:
                    score -= 5   # Very old might be less relevant
            except (ValueError, IndexError):
                pass
        
        # Genre/category score (0-20 points)
        categories = book.get('categories', [])
        category_text = ' '.join(categories).lower()
        
        genre_matches = 0
        for genre in self.preferred_genres:
            if genre in category_text:
                genre_matches += 1
        
        score += min(genre_matches * 4, 20)
        
        # Exclude certain subjects (-50 points, effectively filtering out)
        for exclude in self.exclude_subjects:
            if exclude in category_text:
                score -= 50
                break
        
        # Page count score (favor substantial books, -10 to +10 points)
        page_count = book.get('page_count', 0)
        if page_count:
            if 200 <= page_count <= 500:
                score += 10  # Ideal length
            elif 100 <= page_count < 200 or 500 < page_count <= 800:
                score += 5   # Acceptable length
            elif page_count < 50:
                score -= 10  # Too short, might be low quality
            elif page_count > 1000:
                score -= 5   # Very long, might be academic
        
        # Publisher reputation (0-10 points)
        publisher = book.get('publisher', '').lower()
        major_publishers = {
            'penguin', 'random house', 'harper', 'macmillan', 'simon & schuster',
            'hachette', 'scholastic', 'vintage', 'doubleday', 'crown'
        }
        if any(pub in publisher for pub in major_publishers):
            score += 10
        
        return max(0, score)  # Don't allow negative total scores
    
    def _get_filter_reasons(self, book: Dict[str, Any], user_prefs: Dict[str, Any]) -> List[str]:
        """Get human-readable reasons for filtering decisions"""
        reasons = []
        
        # Rating reasons
        rating = book.get('average_rating', 0)
        if rating >= 4.0:
            reasons.append(f"High rating: {rating}/5")
        
        # Review count reasons
        reviews = book.get('ratings_count', 0)
        if reviews >= 1000:
            reasons.append(f"Popular: {reviews:,} reviews")
        
        # Publication date reasons
        pub_date = book.get('published_date')
        if pub_date:
            try:
                pub_year = int(pub_date.split('-')[0])
                current_year = datetime.now().year
                if current_year - pub_year <= 5:
                    reasons.append("Recently published")
            except (ValueError, IndexError):
                pass
        
        # Genre reasons
        categories = book.get('categories', [])
        category_text = ' '.join(categories).lower()
        matching_genres = [genre for genre in self.preferred_genres if genre in category_text]
        if matching_genres:
            reasons.append(f"Popular genres: {', '.join(matching_genres[:2])}")
        
        return reasons
    
    def _apply_final_filters(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply final filtering rules"""
        # Remove duplicates based on title similarity
        unique_books = []
        seen_titles = set()
        
        for book in books:
            title = book.get('title', '').lower().strip()
            # Simple deduplication - could be enhanced with fuzzy matching
            if title and title not in seen_titles:
                seen_titles.add(title)
                unique_books.append(book)
        
        # Limit results
        return unique_books[:15]


class FuzzyBookSearcher:
    """Enhanced book searcher with fuzzy matching capabilities"""
    
    def __init__(self, books_client: GoogleBooksClient):
        self.books_client = books_client
        # Cache of common OCR corrections
        self.ocr_corrections = {
            # Common letter substitutions
            '0': 'O', '1': 'l', '5': 'S', '6': 'G', '8': 'B',
            # Common word corrections
            'ond': 'and', 'tha': 'the', 'wlth': 'with', 'trom': 'from',
            # Publishing terms
            'nov': 'novel', 'bk': 'book', 'storles': 'stories'
        }
        
        # Common author name patterns that OCR might mangle
        self.author_patterns = [
            r'by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)',  # "by John Smith"
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*$',   # "John Smith" at end
        ]
    
    def search_with_fuzzy_matching(self, raw_text: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Search for books using fuzzy matching on potentially corrupted OCR text"""
        if not raw_text or len(raw_text.strip()) < 3:
            return []
        
        # Clean and prepare the text
        cleaned_text = self._preprocess_ocr_text(raw_text)
        
        # Extract potential titles and authors
        candidates = self._extract_book_candidates(cleaned_text)
        
        search_results = []
        seen_isbns = set()
        
        for candidate in candidates[:10]:  # Limit candidates to avoid too many API calls
            try:
                # Try direct search first
                books = self.books_client.search_books(candidate, max_results=3)
                
                # If no direct matches, try fuzzy variations
                if not books:
                    variations = self._generate_search_variations(candidate)
                    for variation in variations[:3]:  # Limit variations
                        books = self.books_client.search_books(variation, max_results=2)
                        if books:
                            break
                
                # Add unique books to results
                for book in books:
                    isbn = book.get('isbn_13') or book.get('isbn_10') or book.get('id')
                    if isbn and isbn not in seen_isbns:
                        seen_isbns.add(isbn)
                        # Add fuzzy match score
                        book['fuzzy_match_score'] = self._calculate_match_score(raw_text, book)
                        book['search_candidate'] = candidate
                        search_results.append(book)
                
                # Rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                print(f"Search error for '{candidate}': {e}")
                continue
        
        # Sort by fuzzy match score and return top results
        search_results.sort(key=lambda x: x.get('fuzzy_match_score', 0), reverse=True)
        return search_results[:max_results]
    
    def _preprocess_ocr_text(self, text: str) -> str:
        """Clean and preprocess OCR text"""
        # Basic cleaning
        text = re.sub(r'[^\w\s\-\']', ' ', text)  # Keep only alphanumeric, spaces, hyphens, apostrophes
        text = ' '.join(text.split())  # Normalize whitespace
        
        # Apply OCR corrections
        for error, correction in self.ocr_corrections.items():
            text = text.replace(error, correction)
        
        return text.strip()
    
    def _extract_book_candidates(self, text: str) -> List[str]:
        """Extract potential book title and author combinations"""
        candidates = []
        words = text.split()
        
        # Full text as candidate
        if len(text) >= 10:
            candidates.append(text)
        
        # Try different word combinations
        for i in range(len(words)):
            for j in range(i + 2, min(i + 8, len(words) + 1)):  # 2-7 word phrases
                phrase = ' '.join(words[i:j])
                if len(phrase) >= 6:  # Minimum reasonable book title length
                    candidates.append(phrase)
        
        # Try to extract author patterns
        for pattern in self.author_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if len(match) >= 6:  # Reasonable author name length
                    candidates.append(match)
        
        # Remove very short or very long candidates
        candidates = [c for c in candidates if 6 <= len(c) <= 100]
        
        # Sort by length (prefer moderate-length titles)
        candidates.sort(key=lambda x: abs(len(x) - 25))  # Prefer ~25 character titles
        
        return candidates[:15]  # Return top candidates
    
    def _generate_search_variations(self, text: str) -> List[str]:
        """Generate fuzzy search variations of the text"""
        variations = [text]
        
        # Try removing common OCR artifacts
        clean_text = re.sub(r'\b[0-9]+\b', '', text)  # Remove standalone numbers
        clean_text = re.sub(r'\s+', ' ', clean_text).strip()
        if clean_text != text and len(clean_text) >= 6:
            variations.append(clean_text)
        
        # Try title case
        title_case = text.title()
        if title_case != text:
            variations.append(title_case)
        
        # Try removing articles and common words
        words = text.split()
        if len(words) > 3:
            filtered_words = [w for w in words if w.lower() not in {'the', 'a', 'an', 'of', 'in', 'on', 'at', 'to', 'for', 'by'}]
            if len(filtered_words) >= 2:
                variations.append(' '.join(filtered_words))
        
        return variations[:5]  # Limit variations
    
    def _calculate_match_score(self, original_text: str, book: Dict[str, Any]) -> float:
        """Calculate fuzzy match score between original text and book metadata"""
        title = book.get('title', '')
        authors = book.get('authors', [])
        
        # Calculate similarity scores
        title_score = fuzz.partial_ratio(original_text.lower(), title.lower())
        
        author_score = 0
        if authors:
            author_text = ' '.join(authors)
            author_score = fuzz.partial_ratio(original_text.lower(), author_text.lower())
        
        # Combine scores (title is more important)
        combined_score = (title_score * 0.7) + (author_score * 0.3)
        
        return combined_score


class TrendingBookDetector:
    """Detect viral/trending books based on various signals"""
    
    def __init__(self):
        # Known viral books and authors (updated periodically)
        self.viral_books = {
            'fourth wing', 'iron flame', 'it ends with us', 'it starts with us',
            'the seven husbands of evelyn hugo', 'book lovers', 'beach read',
            'people we meet on vacation', 'the atlas six', 'the midnight library',
            'where the crawdads sing', 'educated', 'becoming', 'atomic habits'
        }
        
        self.viral_authors = {
            'colleen hoover', 'emily henry', 'taylor jenkins reid', 'rebecca ross',
            'olivie blake', 'sally rooney', 'madeline miller', 'leigh bardugo',
            'victoria aveyard', 'sarah j. maas', 'jennifer l. armentrout'
        }
        
        # TikTok/BookTok trending keywords
        self.trending_keywords = {
            'booktok', 'tiktok famous', 'viral', 'trending', 'everyone is reading',
            'must read', 'obsessed', 'emotional damage', 'crying', 'sobbing',
            'enemies to lovers', 'found family', 'dark academia', 'fantasy romance',
            'morally gray', 'love triangle', 'chosen one', 'dystopian'
        }
    
    def detect_trending_books(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Detect and boost trending/viral books"""
        processed_books = []
        
        for book in books:
            book_copy = book.copy()
            
            # Calculate trending score
            trending_score = self._calculate_trending_score(book)
            book_copy['trending_score'] = trending_score
            
            # Add trending boost to existing scores
            if trending_score > 50:  # High trending score
                if 'quality_score' in book_copy:
                    book_copy['quality_score'] += 15
                if 'google_score' in book_copy:
                    book_copy['google_score'] += 10
                
                book_copy['trending_boost'] = True
                book_copy['trending_reasons'] = self._get_trending_reasons(book)
            else:
                book_copy['trending_boost'] = False
            
            processed_books.append(book_copy)
        
        return processed_books
    
    def _calculate_trending_score(self, book: Dict[str, Any]) -> float:
        """Calculate trending score based on various signals"""
        score = 0
        
        title = book.get('title', '').lower()
        authors = [author.lower() for author in book.get('authors', [])]
        description = book.get('description', '').lower()
        
        # Check for viral books
        if any(viral_title in title for viral_title in self.viral_books):
            score += 50
        
        # Check for viral authors
        if any(any(viral_author in author for author in authors) for viral_author in self.viral_authors):
            score += 40
        
        # Check for trending keywords
        combined_text = f"{title} {description}"
        keyword_matches = sum(1 for keyword in self.trending_keywords if keyword in combined_text)
        score += min(keyword_matches * 5, 30)
        
        # Recent high ratings suggest trending
        rating = book.get('average_rating', 0)
        review_count = book.get('ratings_count', 0)
        if rating >= 4.0 and review_count >= 5000:
            score += 20
        
        # Recent publication + high engagement = potentially viral
        pub_date = book.get('published_date', '')
        if pub_date:
            try:
                pub_year = int(pub_date[:4])
                current_year = datetime.now().year
                if current_year - pub_year <= 3 and review_count >= 1000:
                    score += 15
            except (ValueError, IndexError):
                pass
        
        return min(100, score)
    
    def _get_trending_reasons(self, book: Dict[str, Any]) -> List[str]:
        """Get reasons why book is considered trending"""
        reasons = []
        
        title = book.get('title', '').lower()
        authors = [author.lower() for author in book.get('authors', [])]
        
        # Check specific matches
        if any(viral_title in title for viral_title in self.viral_books):
            reasons.append("Viral book")
        
        if any(any(viral_author in author for author in authors) for viral_author in self.viral_authors):
            reasons.append("Trending author")
        
        rating = book.get('average_rating', 0)
        review_count = book.get('ratings_count', 0)
        if rating >= 4.0 and review_count >= 5000:
            reasons.append("High engagement")
        
        return reasons


# Factory functions for easy instantiation
def create_book_filter() -> BookQualityFilter:
    """Create a book quality filter instance"""
    return BookQualityFilter()


def create_language_filter(preferred_languages: List[str] = None) -> LanguageFilter:
    """Create a language filter instance"""
    return LanguageFilter(preferred_languages)


def create_google_books_filter() -> GoogleBooksFilter:
    """Create a Google Books filter instance"""
    return GoogleBooksFilter()


def create_fuzzy_searcher(books_client: GoogleBooksClient) -> FuzzyBookSearcher:
    """Create a fuzzy book searcher instance"""
    return FuzzyBookSearcher(books_client)


def create_trending_detector() -> TrendingBookDetector:
    """Create a trending book detector instance"""
    return TrendingBookDetector()