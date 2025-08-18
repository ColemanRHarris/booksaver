"""
Language filtering for English and Spanish books only
"""

import re
from typing import List, Dict, Any, Optional
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException

class LanguageFilter:
    """Filter books to include only English and Spanish language books"""
    
    def __init__(self):
        # Supported languages
        self.supported_languages = {'en', 'es'}  # English and Spanish
        
        # Common words in each language for manual detection
        self.english_indicators = {
            'the', 'and', 'of', 'to', 'a', 'in', 'for', 'is', 'on', 'that', 'by', 'this', 
            'with', 'i', 'you', 'it', 'not', 'or', 'be', 'are', 'from', 'at', 'as', 'your',
            'all', 'any', 'can', 'had', 'her', 'was', 'one', 'our', 'out', 'day', 'get',
            'has', 'him', 'his', 'how', 'man', 'new', 'now', 'old', 'see', 'two', 'way',
            'who', 'boy', 'did', 'its', 'let', 'put', 'say', 'she', 'too', 'use'
        }
        
        self.spanish_indicators = {
            'el', 'la', 'de', 'que', 'y', 'a', 'en', 'un', 'es', 'se', 'no', 'te', 'lo',
            'le', 'da', 'su', 'por', 'son', 'con', 'para', 'al', 'una', 'del', 'los',
            'las', 'me', 'mi', 'tu', 'si', 'como', 'yo', 'pero', 'sus', 'le', 'ya',
            'o', 'porque', 'cuando', 'muy', 'sin', 'sobre', 'también', 'me', 'hasta',
            'donde', 'quien', 'desde', 'todos', 'durante', 'todos', 'otro', 'mucho',
            'tiempo', 'vida', 'días', 'hombre', 'años', 'casa', 'mismo', 'amor'
        }
        
        # Publishers that typically publish in specific languages
        self.english_publishers = {
            'penguin', 'random house', 'harper', 'macmillan', 'simon & schuster',
            'hachette', 'scholastic', 'bantam', 'dell', 'anchor', 'vintage',
            'ballantine', 'berkley', 'crown', 'doubleday', 'dutton', 'gallery',
            'grand central', 'henry holt', 'knopf', 'little brown', 'tor',
            'st. martin', 'william morrow', 'atria', 'avon', 'scribner',
            'bloomsbury', 'harpercollins', 'oxford', 'cambridge'
        }
        
        self.spanish_publishers = {
            'planeta', 'santillana', 'alfaguara', 'anagrama', 'seix barral',
            'tusquets', 'destino', 'crítica', 'lumen', 'grijalbo', 'mondadori',
            'roca editorial', 'suma', 'espasa', 'debate', 'taurus', 'aguilar',
            'ediciones b', 'maeva', 'salamandra', 'errata naturae', 'sexto piso'
        }
    
    def filter_books_by_language(self, books: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter books to include only English and Spanish language books"""
        if not books:
            return books
        
        print(f"🌐 Filtering {len(books)} books for English/Spanish language...")
        
        filtered_books = []
        for book in books:
            language = self._detect_book_language(book)
            
            if language in self.supported_languages:
                book_copy = book.copy()
                book_copy['detected_language'] = language
                book_copy['language_confidence'] = self._get_language_confidence(book, language)
                filtered_books.append(book_copy)
            else:
                title = book.get('title', 'Unknown')[:40]
                print(f"❌ Filtered out '{title}' (detected: {language})")
        
        print(f"✅ Kept {len(filtered_books)} books in English/Spanish")
        return filtered_books
    
    def _detect_book_language(self, book: Dict[str, Any]) -> str:
        """Detect the language of a book using multiple methods"""
        title = book.get('title', '')
        description = book.get('description', '')
        authors = book.get('authors', [])
        publisher = book.get('publisher', '')
        
        # Method 1: Google Books language field (if available) - HIGHEST PRIORITY
        if 'language' in book:
            lang = book['language'].lower()
            if lang in ['en', 'english']:
                return 'en'
            elif lang in ['es', 'spanish', 'español', 'spa']:
                return 'es'
            elif lang in ['de', 'german', 'deutsch', 'ger']:
                return 'de'  # German - will be filtered out
            elif lang in ['fr', 'french', 'français', 'fra']:
                return 'fr'  # French - will be filtered out
            else:
                # Unknown language from explicit field - filter out
                return lang
        
        # Method 2: Publisher-based detection
        publisher_lang = self._detect_language_by_publisher(publisher)
        if publisher_lang:
            return publisher_lang
        
        # Method 3: Content-based language detection
        content_text = f"{title} {description}".strip()
        if len(content_text) > 10:  # Need sufficient text for detection
            
            # First try manual word-based detection (more reliable for our use case)
            manual_lang = self._detect_language_manually(content_text)
            if manual_lang != 'unknown':
                return manual_lang
            
            # Fallback to automatic language detection
            auto_lang = self._detect_language_automatically(content_text)
            if auto_lang != 'unknown':
                return auto_lang
        
        # Method 4: Author name patterns (rough heuristic)
        author_lang = self._detect_language_by_author_names(authors)
        if author_lang in self.supported_languages:
            return author_lang
        
        # Default: assume English if unsure (most TikTok books are English)
        return 'en'
    
    def _detect_language_by_publisher(self, publisher: str) -> Optional[str]:
        """Detect language based on publisher"""
        if not publisher:
            return None
        
        publisher_lower = publisher.lower()
        
        # Check English publishers
        for eng_pub in self.english_publishers:
            if eng_pub in publisher_lower:
                return 'en'
        
        # Check Spanish publishers
        for esp_pub in self.spanish_publishers:
            if esp_pub in publisher_lower:
                return 'es'
        
        return None
    
    def _detect_language_automatically(self, text: str) -> str:
        """Use automatic language detection library"""
        try:
            # Clean text for better detection
            clean_text = re.sub(r'[^\w\s]', ' ', text)
            clean_text = re.sub(r'\s+', ' ', clean_text).strip()
            
            if len(clean_text) < 20:  # Too short for reliable detection
                return 'unknown'
            
            detected_lang = detect(clean_text)
            return detected_lang if detected_lang in self.supported_languages else 'unknown'
            
        except (LangDetectException, Exception):
            return 'unknown'
    
    def _detect_language_manually(self, text: str) -> str:
        """Manual language detection using common words"""
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)
        
        if len(words) < 5:  # Too few words
            return 'unknown'
        
        english_score = 0
        spanish_score = 0
        
        for word in words:
            if word in self.english_indicators:
                english_score += 1
            elif word in self.spanish_indicators:
                spanish_score += 1
        
        # Need at least 2 indicator words for confidence
        if english_score >= 2 and english_score > spanish_score:
            return 'en'
        elif spanish_score >= 2 and spanish_score > english_score:
            return 'es'
        
        return 'unknown'
    
    def _detect_language_by_author_names(self, authors: List[str]) -> str:
        """Rough language detection based on author name patterns"""
        if not authors:
            return 'unknown'
        
        full_names = ' '.join(authors).lower()
        
        # Spanish name indicators (very rough heuristics)
        spanish_patterns = [
            r'\b(garcía|gonzalez|rodriguez|martinez|lopez|hernandez|perez|sanchez|ramirez|torres)\b',
            r'\b(josé|maría|carlos|juan|antonio|francisco|manuel|david|daniel|pablo)\b',
            r'\b(ana|carmen|elena|isabel|cristina|patricia|laura|marta|sandra|beatriz)\b',
            r'\b(de la|del |mc|mac)\b',  # Spanish particles
        ]
        
        spanish_matches = sum(1 for pattern in spanish_patterns if re.search(pattern, full_names))
        
        # If multiple Spanish indicators, probably Spanish
        if spanish_matches >= 2:
            return 'es'
        
        # Otherwise assume English (most common on TikTok)
        return 'en'
    
    def _get_language_confidence(self, book: Dict[str, Any], detected_lang: str) -> float:
        """Get confidence score for language detection"""
        confidence = 0.5  # Base confidence
        
        # Boost confidence if publisher matches detected language
        publisher = book.get('publisher', '').lower()
        if detected_lang == 'en' and any(pub in publisher for pub in self.english_publishers):
            confidence += 0.3
        elif detected_lang == 'es' and any(pub in publisher for pub in self.spanish_publishers):
            confidence += 0.3
        
        # Boost confidence if we have explicit language field
        if 'language' in book:
            confidence += 0.2
        
        # Boost confidence for longer descriptions (more text to analyze)
        description = book.get('description', '')
        if len(description) > 100:
            confidence += 0.2
        elif len(description) > 50:
            confidence += 0.1
        
        return min(1.0, confidence)

class GoogleBooksLanguageFilter:
    """Enhanced Google Books API usage with language parameters"""
    
    def __init__(self, books_client):
        self.books_client = books_client
        
    def search_books_with_language(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search books with language preference for English and Spanish"""
        results = []
        
        # Try English search first (more common on TikTok)
        try:
            # Modify the query to prefer English books
            english_results = self.books_client.search_books(
                f"{query} lang:en", max_results=max(1, max_results // 2)
            )
            results.extend(english_results)
        except Exception as e:
            print(f"English search failed: {e}")
        
        # Try Spanish search if we have room for more results
        if len(results) < max_results:
            try:
                remaining_slots = max_results - len(results)
                spanish_results = self.books_client.search_books(
                    f"{query} lang:es", max_results=remaining_slots
                )
                results.extend(spanish_results)
            except Exception as e:
                print(f"Spanish search failed: {e}")
        
        # If language-specific searches fail, fall back to regular search
        if not results:
            try:
                results = self.books_client.search_books(query, max_results)
            except Exception as e:
                print(f"Fallback search failed: {e}")
        
        return results

def create_language_filter() -> LanguageFilter:
    """Create a language filter instance"""
    return LanguageFilter()