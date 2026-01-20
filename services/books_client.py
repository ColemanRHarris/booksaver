import requests
import os
import time
import random
from typing import List, Dict, Optional
# Filters imported dynamically to avoid circular imports

class GoogleBooksClient:
    def __init__(self):
        # Use public API by default to avoid quota issues
        self.api_key = None  # Disabled API key to use public access
        self.base_url = "https://www.googleapis.com/books/v1/volumes"
        self.last_request_time = 0
        self.min_request_interval = 0.5  # 500ms between requests for public API
        self.max_retries = 3
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = 300  # 5 minutes
        print("📚 Using Google Books public API (no key) to avoid quota limits")
    
    def _rate_limit_delay(self):
        """Implement rate limiting between requests"""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            sleep_time = self.min_request_interval - time_since_last
            time.sleep(sleep_time)
        
        self.last_request_time = time.time()

    def _make_request_with_retry(self, params: dict) -> requests.Response:
        """Make API request with exponential backoff retry logic"""
        for attempt in range(self.max_retries):
            try:
                # Rate limiting
                self._rate_limit_delay()
                
                # Make the request
                response = requests.get(self.base_url, params=params, timeout=15)
                
                # Handle rate limiting
                if response.status_code == 429:
                    if attempt < self.max_retries - 1:
                        # Exponential backoff with jitter
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                        print(f"Rate limited, waiting {wait_time:.1f}s before retry {attempt + 1}/{self.max_retries}")
                        time.sleep(wait_time)
                        continue
                    else:
                        print("Max retries reached for rate limiting")
                        raise requests.exceptions.RequestException("Rate limit exceeded after retries")
                
                # Handle 403 errors (should be rare with public access)
                if response.status_code == 403:
                    print("Access denied (403) - may need to reduce request rate")
                    if attempt < self.max_retries - 1:
                        wait_time = (2 ** attempt) + 2  # Extra delay for 403s
                        print(f"Waiting {wait_time}s before retry...")
                        time.sleep(wait_time)
                        continue
                    else:
                        print("Max retries reached for 403 errors")
                        raise requests.exceptions.RequestException("Access denied after retries")
                
                # Raise for other HTTP errors
                response.raise_for_status()
                return response
                
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt)
                    print(f"Timeout, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise
            except requests.exceptions.RequestException as e:
                if attempt < self.max_retries - 1:
                    wait_time = (2 ** attempt)
                    print(f"Request error: {e}, retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise

    def _fallback_public_request(self, original_params: dict) -> requests.Response:
        """Fallback method - same as main request since we're already using public API"""
        # This method is kept for compatibility but should not be needed
        public_params = {k: v for k, v in original_params.items() if k != 'key'}
        
        # Rate limit for public access
        self._rate_limit_delay()
        
        response = requests.get(self.base_url, params=public_params, timeout=15)
        response.raise_for_status()
        return response

    def _get_cache_key(self, query: str, max_results: int) -> str:
        """Generate cache key for query"""
        return f"{query.lower().strip()}:{max_results}"

    def _is_cache_valid(self, timestamp: float) -> bool:
        """Check if cache entry is still valid"""
        return time.time() - timestamp < self.cache_ttl

    def search_books(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search for books using Google Books API with rate limiting and retry logic"""
        if not query or not query.strip():
            return []
        
        # Check cache first
        cache_key = self._get_cache_key(query, max_results)
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if self._is_cache_valid(timestamp):
                print(f"📋 Using cached result for: '{query}'")
                return cached_data
            else:
                # Remove expired cache entry
                del self.cache[cache_key]
        
        # Allow more results for better filtering downstream
        max_results = min(max_results, 20)
        
        params = {
            "q": query.strip(),
            "maxResults": max_results,
            "printType": "books",  # Only books, not magazines
            "orderBy": "relevance",  # Most relevant first
            "langRestrict": "en|es"  # Prefer English/Spanish
        }
        
        # Note: Not using API key to avoid quota issues with public access
        
        try:
            print(f"🔍 Searching Google Books for: '{query}' (max: {max_results})")
            
            response = self._make_request_with_retry(params)
            data = response.json()
            
            books = []
            items = data.get('items', [])
            
            print(f"📚 Google Books returned {len(items)} results")
            
            for item in items:
                volume_info = item.get('volumeInfo', {})
                access_info = item.get('accessInfo', {})
                
                # Get thumbnail and upgrade to HTTPS if needed
                thumbnail_url = volume_info.get('imageLinks', {}).get('thumbnail', '')
                if thumbnail_url and thumbnail_url.startswith('http://'):
                    thumbnail_url = thumbnail_url.replace('http://', 'https://')

                book = {
                    'title': volume_info.get('title', 'Unknown Title'),
                    'authors': volume_info.get('authors', ['Unknown Author']),
                    'description': volume_info.get('description', ''),
                    'published_date': volume_info.get('publishedDate', ''),
                    'isbn': self._extract_isbn(volume_info.get('industryIdentifiers', [])),
                    'thumbnail': thumbnail_url,
                    'categories': volume_info.get('categories', []),
                    'preview_link': volume_info.get('previewLink', ''),
                    'info_link': volume_info.get('infoLink', ''),
                    'canonical_link': volume_info.get('canonicalVolumeLink', ''),
                    'web_reader_link': access_info.get('webReaderLink', '')
                }
                books.append(book)
            
            # Apply Google Books result filtering to remove weird results
            try:
                from core.filters import create_google_books_filter
                books_filter = create_google_books_filter()
                filtered_books = books_filter.filter_books(books, {'query': query})
            except Exception as e:
                print(f"Warning: Google Books filtering failed: {e}")
                filtered_books = books  # Fallback to unfiltered results
            
            # Cache the filtered results
            self.cache[cache_key] = (filtered_books, time.time())
            
            return filtered_books
            
        except requests.RequestException as e:
            print(f"❌ Error fetching books for '{query}': {e}")
            return []
        except Exception as e:
            print(f"❌ Unexpected error searching for '{query}': {e}")
            return []
    
    def _extract_isbn(self, identifiers: List[Dict]) -> Optional[str]:
        """Extract ISBN from industry identifiers"""
        for identifier in identifiers:
            if identifier.get('type') in ['ISBN_13', 'ISBN_10']:
                return identifier.get('identifier')
        return None

def build_purchase_links(book: Dict) -> Dict[str, str]:
    """Build purchase links for multiple retailers"""
    title = book.get('title', '')
    authors = book.get('authors', [])
    author = authors[0] if authors else ''
    isbn = book.get('isbn', '')
    
    # Clean up title (remove subtitle after colon for better matching)
    clean_title = title.split(':')[0].strip()
    search_term = f"{clean_title} {author}".strip()
    encoded_term = search_term.replace(' ', '+')
    
    links = {}
    
    if search_term:
        # Amazon - use book-specific search with title + author
        links['amazon'] = f"https://www.amazon.com/s?k={encoded_term}&i=stripbooks"
        
        # Audible - audiobook search
        links['audible'] = f"https://www.audible.com/search?keywords={encoded_term}"
        
        # Barnes & Noble
        links['barnes_noble'] = f"https://www.barnesandnoble.com/s/{encoded_term}"
        
        # Google Books - use direct link if available, otherwise search
        if book.get('canonical_link'):
            links['google_books'] = book['canonical_link']
        elif book.get('info_link'):
            links['google_books'] = book['info_link']
        else:
            links['google_books'] = f"https://books.google.com/books?q={encoded_term}"
        
        # Bookshop.org (supports independent bookstores)
        links['bookshop'] = f"https://bookshop.org/search?keywords={encoded_term}&affiliate=117660"
    
    return links

def build_reader_app_links(book: Dict) -> Dict[str, str]:
    """Build links for popular reader apps"""
    title = book.get('title', '')
    authors = book.get('authors', [])
    author = authors[0] if authors else ''
    isbn = book.get('isbn', '')
    
    # Clean up title for search
    clean_title = title.split(':')[0].strip()
    search_term = f"{clean_title} {author}".strip()
    encoded_term = search_term.replace(' ', '+')
    
    links = {}
    
    if search_term:
        # Goodreads - try ISBN first, fallback to search
        if isbn:
            # Goodreads has predictable ISBN-based URLs
            links['goodreads'] = f"https://www.goodreads.com/book/isbn/{isbn}"
        else:
            links['goodreads'] = f"https://www.goodreads.com/search?q={encoded_term}"
        
        # OverDrive (library system) - search only
        links['overdrive'] = f"https://www.overdrive.com/search?q={encoded_term}"
        
        # StoryGraph - search only
        links['storygraph'] = f"https://app.thestorygraph.com/browse?search_term={encoded_term}"
        
        # LibraryThing - search only
        links['librarything'] = f"https://www.librarything.com/search.php?searchtype=work&search={encoded_term}"
    
    return links

def build_amazon_link(book: Dict) -> str:
    """Build Amazon search link for backward compatibility"""
    links = build_purchase_links(book)
    return links.get('amazon', 'https://www.amazon.com/books')
