import requests
import os
from typing import List, Dict, Optional

class GoogleBooksClient:
    def __init__(self):
        self.api_key = os.getenv('GOOGLE_BOOKS_KEY')
        self.base_url = "https://www.googleapis.com/books/v1/volumes"
    
    def search_books(self, query: str, max_results: int = 10) -> List[Dict]:
        """Search for books using Google Books API"""
        if not self.api_key:
            raise ValueError("Google Books API key not found in environment variables")
        
        params = {
            "q": f"intitle:{query}",
            "maxResults": max_results,
            "key": self.api_key
        }
        
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            
            # If API key fails (403), fallback to public access
            if response.status_code == 403:
                print("API key access failed, falling back to public access")
                params_public = {
                    "q": f"intitle:{query}",
                    "maxResults": max_results
                }
                response = requests.get(self.base_url, params=params_public, timeout=10)
                response.raise_for_status()
            else:
                response.raise_for_status()
            
            data = response.json()
            
            books = []
            items = data.get('items', [])
            
            for item in items:
                volume_info = item.get('volumeInfo', {})
                
                book = {
                    'title': volume_info.get('title', 'Unknown Title'),
                    'authors': volume_info.get('authors', ['Unknown Author']),
                    'description': volume_info.get('description', ''),
                    'published_date': volume_info.get('publishedDate', ''),
                    'isbn': self._extract_isbn(volume_info.get('industryIdentifiers', [])),
                    'thumbnail': volume_info.get('imageLinks', {}).get('thumbnail', ''),
                    'preview_link': volume_info.get('previewLink', ''),
                    'info_link': volume_info.get('infoLink', '')
                }
                books.append(book)
            
            return books
            
        except requests.RequestException as e:
            print(f"Error fetching books: {e}")
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
        
        # Barnes & Noble
        links['barnes_noble'] = f"https://www.barnesandnoble.com/s/{encoded_term}"
        
        # Google Books (for purchasing)
        links['google_books'] = f"https://books.google.com/books?q={encoded_term}"
        
        # Bookshop.org (supports independent bookstores)
        links['bookshop'] = f"https://bookshop.org/search?keywords={encoded_term}"
    
    return links

def build_amazon_link(book: Dict) -> str:
    """Build Amazon search link for backward compatibility"""
    links = build_purchase_links(book)
    return links.get('amazon', 'https://www.amazon.com/books')