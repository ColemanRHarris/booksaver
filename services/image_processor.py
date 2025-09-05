"""
Simplified image processing service for BookSaver.
Processes images directly without Celery task queuing.
"""

import os
import ast
import time
import logging
from typing import Dict, List, Any
from google import genai

from services.image_storage import get_image_storage_service
from services.books_client import GoogleBooksClient, build_purchase_links, build_reader_app_links
from services.recommendation_engine import get_recommendation_engine
from core.filters import create_fuzzy_searcher, create_book_filter, create_trending_detector, create_language_filter

# Configure logging
logger = logging.getLogger(__name__)

# Configuration constants
MAX_IMAGE_SIZE_MB = 10
MAX_IMAGE_SIZE_BYTES = MAX_IMAGE_SIZE_MB * 1024 * 1024


def check_file_size(file_path: str) -> bool:
    """Check if file size is within limits."""
    try:
        file_size = os.path.getsize(file_path)
        return file_size <= MAX_IMAGE_SIZE_BYTES
    except OSError:
        return False


class ImageProcessor:
    """Service for processing book images and extracting book information."""
    
    def __init__(self):
        self.image_storage = get_image_storage_service()
        self.recommendation_engine = get_recommendation_engine()
        
        # Verify Gemini API key
        self.api_key = os.getenv('GEMINI_API_KEY')
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        self.genai_client = genai.Client(api_key=self.api_key)
        logger.info("✅ Image processor initialized with Gemini API")
    
    def process_image(self, image_id: str) -> Dict[str, Any]:
        """
        Process an image and extract book information.
        
        Args:
            image_id: Unique identifier for the stored image
            
        Returns:
            Dictionary with processing results
        """
        logger.info(f"🚀 Starting image processing for: {image_id}")
        
        # Check cache first
        cached_result = self.recommendation_engine.get_cached_results(image_id)
        if cached_result:
            logger.info(f"🎉 Cache hit! Returning cached results for: {image_id}")
            return cached_result
        
        temp_image_path = None
        
        try:
            # Get image file path
            temp_image_path = self.image_storage.create_temp_file(image_id)
            if not temp_image_path:
                raise Exception(f"Image not found or expired: {image_id}")
            
            logger.info(f"✅ Image file ready: {temp_image_path}")
            
            # Verify file exists and check size
            if not os.path.exists(temp_image_path):
                raise Exception(f"Image file not found: {temp_image_path}")
            
            if not check_file_size(temp_image_path):
                raise Exception(f"Image file exceeds {MAX_IMAGE_SIZE_MB}MB size limit")
            
            # Process with Gemini AI
            logger.info("📤 Uploading image to Gemini AI...")
            gen_file = self.genai_client.files.upload(file=temp_image_path)
            
            # Wait for processing
            logger.info("⏳ Waiting for Gemini processing...")
            while gen_file.state.name == "PROCESSING":
                time.sleep(1)
                gen_file = self.genai_client.files.get(name=gen_file.name)
            
            if gen_file.state.name == "FAILED":
                raise ValueError(f"Gemini processing failed: {gen_file.state.name}")
            
            # Generate book identification prompt
            prompt = """
            Please review this image and identify what books, if any, are present in the image. Look for book covers, spines, or any visible book titles and authors.
            Please provide results formatted as a Python list, with the following format:
            ["TITLE by AUTHOR"]
            If there are no books visible in the image, please return an empty list.
            Do NOT return in a code chunk and do NOT return with any additional text.
            """
            
            logger.info("🤖 Generating book identification...")
            response = self.genai_client.models.generate_content(
                model="gemini-2.0-flash-lite", 
                contents=[gen_file, prompt]
            )
            
            # Parse response
            book_texts = ast.literal_eval(response.text)
            logger.info(f"📚 Found {len(book_texts)} potential book references")
            
            # Search for books
            logger.info("🔍 Searching for book details...")
            books = self._search_books_from_text(book_texts)
            logger.info(f"✅ Book search completed: {len(books)} books found")
            
            result = {
                'status': 'success',
                'books': books,
                'total_texts': len(book_texts)
            }
            
            # Cache the result
            self.recommendation_engine.cache_results(image_id, 'image', result)
            
            # Clean up stored image
            self.image_storage.delete_image(image_id)
            logger.info(f"🧹 Cleaned up stored image: {image_id}")
            
            logger.info(f"🎉 Processing completed successfully! Found {len(books)} books")
            return result
            
        except Exception as e:
            error_message = self._get_user_friendly_error(str(e))
            logger.error(f"❌ Image processing failed: {e}")
            
            # Cleanup on error
            try:
                if temp_image_path and os.path.exists(temp_image_path):
                    # Note: For file-based storage, temp_image_path is the actual stored file
                    # so we don't need to delete it separately since delete_image will handle it
                    pass
                
                self.image_storage.delete_image(image_id)
                logger.info(f"🧹 Cleaned up stored image: {image_id}")
            except Exception as cleanup_error:
                logger.warning(f"⚠️ Cleanup failed: {cleanup_error}")
            
            return {
                'status': 'error',
                'error': error_message
            }
    
    def _search_books_from_text(self, texts: List[str]) -> List[Dict]:
        """Search for books using extracted text with fuzzy matching."""
        logger.info(f"📚 Starting fuzzy book search with {len(texts)} text extractions")
        
        # Create fuzzy searcher
        books_client = GoogleBooksClient()
        fuzzy_searcher = create_fuzzy_searcher(books_client)
        found_books = []
        seen_titles = set()
        
        for i, text in enumerate(texts):
            if not text or len(text.strip()) < 3:
                continue
            
            logger.info(f"🔍 Searching for: {text[:50]}...")
            try:
                # Use fuzzy search to find books
                search_results = fuzzy_searcher.search_with_fuzzy_matching(text, max_results=3)
                
                for book in search_results:
                    title = book.get('title', '')
                    if title and title not in seen_titles:
                        # Add purchase and reader app links
                        book['purchase_links'] = build_purchase_links(book)
                        book['reader_app_links'] = build_reader_app_links(book)
                        
                        seen_titles.add(title)
                        found_books.append(book)
                        logger.info(f"✅ Found: {title}")
                
                # Rate limiting
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"⚠️ Search error for '{text[:30]}...': {e}")
                continue
        
        # Apply filters to improve results
        if found_books:
            logger.info("🔧 Applying quality filters...")
            try:
                # Create filters
                quality_filter = create_book_filter()
                language_filter = create_language_filter()
                trending_detector = create_trending_detector()
                
                # Apply filtering
                filtered_books = quality_filter.filter_books(found_books)
                filtered_books = language_filter.filter_books(filtered_books)
                
                # Add trending scores
                for book in filtered_books:
                    trending_score = trending_detector.calculate_trending_score(book)
                    book['trending_score'] = trending_score
                
                # Sort by relevance (fuzzy score + trending score)
                filtered_books.sort(
                    key=lambda x: (x.get('fuzzy_match_score', 0) + x.get('trending_score', 0)), 
                    reverse=True
                )
                
                logger.info(f"✅ Filtering completed: {len(filtered_books)} quality books")
                return filtered_books[:10]  # Return top 10 results
                
            except Exception as e:
                logger.warning(f"⚠️ Filtering failed, returning unfiltered results: {e}")
                return found_books[:10]
        
        return found_books
    
    def _get_user_friendly_error(self, error_message: str) -> str:
        """Convert technical error messages to user-friendly ones."""
        if "Image not found" in error_message or "expired" in error_message:
            return "Image data expired or not found. Please try uploading again."
        elif "Image file not found" in error_message:
            return "Image file not found. Please try uploading again."
        elif "Image file exceeds" in error_message:
            return "Image file is too large. Please use an image smaller than 10MB."
        elif "No books" in error_message or "empty list" in error_message:
            return "No books were detected in this image. Try with a clearer photo showing book covers or spines."
        elif "Invalid image format" in error_message:
            return "Invalid image format. Please use JPG or PNG files."
        elif "GEMINI_API_KEY" in error_message:
            return "Service configuration error. Please try again later."
        elif "Gemini processing failed" in error_message:
            return "AI processing failed. Please try with a different image."
        else:
            return "Processing failed. Please try again with a clearer image."


# Global instance
_image_processor = None


def get_image_processor() -> ImageProcessor:
    """Get the global image processor instance."""
    global _image_processor
    if _image_processor is None:
        _image_processor = ImageProcessor()
    return _image_processor