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

        # Log memory usage at start
        try:
            import psutil
            process = psutil.Process()
            mem_info = process.memory_info()
            logger.info(f"💾 Memory usage at start: {mem_info.rss / (1024*1024):.1f}MB RSS, {mem_info.vms / (1024*1024):.1f}MB VMS")
        except ImportError:
            logger.debug("psutil not available for memory monitoring")
        except Exception as mem_err:
            logger.debug(f"Could not get memory info: {mem_err}")

        temp_image_path = None
        
        try:
            # Validate input
            if not image_id or not isinstance(image_id, str):
                raise ValueError(f"Invalid image_id: {image_id}")
            
            logger.info(f"📋 Processing environment: Python, Memory available")
            
            # Check API key availability
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY not available")
            
            logger.info(f"🔑 API key available: {self.api_key[:8]}...")
            
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
            
            # Process with Gemini AI with comprehensive error handling
            logger.info("📤 Uploading image to Gemini AI...")
            try:
                gen_file = self.genai_client.files.upload(file=temp_image_path)
                logger.info(f"✅ Upload successful, file ID: {gen_file.name}")
            except Exception as upload_error:
                logger.error(f"❌ Gemini upload failed: {upload_error}")
                raise Exception(f"Failed to upload to Gemini AI: {str(upload_error)}")
            
            # Wait for processing with timeout
            logger.info("⏳ Waiting for Gemini processing...")
            processing_timeout = 30  # 30 second timeout
            processing_start = time.time()
            
            try:
                while gen_file.state.name == "PROCESSING":
                    if time.time() - processing_start > processing_timeout:
                        raise Exception(f"Gemini processing timeout after {processing_timeout}s")
                    
                    time.sleep(1)
                    gen_file = self.genai_client.files.get(name=gen_file.name)
                    logger.info(f"⏳ Processing status: {gen_file.state.name}")
                
                if gen_file.state.name == "FAILED":
                    raise Exception(f"Gemini processing failed: {gen_file.state.name}")
                
                logger.info(f"✅ Gemini processing completed: {gen_file.state.name}")
                
            except Exception as processing_error:
                logger.error(f"❌ Gemini processing error: {processing_error}")
                raise Exception(f"Gemini processing failed: {str(processing_error)}")
            
            # Generate book identification prompt
            prompt = """
            Please review this image and identify what books, if any, are present in the image. Look for book covers, spines, or any visible book titles and authors.
            Please provide results formatted as a Python list, with the following format:
            ["TITLE by AUTHOR"]
            If there are no books visible in the image, please return an empty list.
            Do NOT return in a code chunk and do NOT return with any additional text.
            """
            
            logger.info("🤖 Generating book identification...")
            try:
                response = self.genai_client.models.generate_content(
                    model="gemini-2.5-flash-preview-09-2025", 
                    contents=[gen_file, prompt]
                )
                logger.info("✅ Gemini response received")
                
            except Exception as generation_error:
                logger.error(f"❌ Gemini content generation failed: {generation_error}")
                raise Exception(f"Failed to generate content: {str(generation_error)}")
            
            # Parse response with error handling
            try:
                if not response.text or response.text.strip() == "":
                    logger.warning("⚠️ Empty response from Gemini")
                    book_texts = []
                else:
                    logger.info(f"📝 Raw Gemini response: {response.text[:200]}...")
                    book_texts = ast.literal_eval(response.text)
                    logger.info(f"📚 Parsed {len(book_texts)} potential book references")
                    
            except (ValueError, SyntaxError) as parse_error:
                logger.error(f"❌ Failed to parse Gemini response: {parse_error}")
                logger.error(f"Raw response: {response.text}")
                # Fallback: try to extract any text that looks like a book
                book_texts = []
            
            # Search for books with fallback handling
            logger.info("🔍 Searching for book details...")

            # Log memory usage before search
            try:
                import psutil
                process = psutil.Process()
                mem_info = process.memory_info()
                logger.info(f"💾 Memory before search: {mem_info.rss / (1024*1024):.1f}MB RSS")
            except:
                pass

            try:
                books = self._search_books_from_text(book_texts) if book_texts else []
                logger.info(f"✅ Book search completed: {len(books)} books found")

                # Log memory usage after search
                try:
                    import psutil
                    process = psutil.Process()
                    mem_info = process.memory_info()
                    logger.info(f"💾 Memory after search: {mem_info.rss / (1024*1024):.1f}MB RSS")
                except:
                    pass
                
            except Exception as search_error:
                logger.error(f"❌ Book search failed: {search_error}")
                # Fallback: return empty results rather than crashing
                books = []
            
            result = {
                'status': 'success',
                'books': books,
                'total_texts': len(book_texts)
            }
            
            # Clean up stored image
            self.image_storage.delete_image(image_id)
            logger.info(f"🧹 Cleaned up stored image: {image_id}")
            
            logger.info(f"🎉 Processing completed successfully! Found {len(books)} books")
            return result
            
        except Exception as e:
            # Log the raw technical error for debugging
            logger.error(f"❌ TECHNICAL ERROR: {type(e).__name__}: {str(e)}")
            logger.error(f"❌ Full exception details: {e.__class__.__module__}.{e.__class__.__name__}")
            
            # Additional debugging information
            import traceback
            logger.error(f"❌ Stack trace: {traceback.format_exc()}")
            
            # Check if we should show technical errors (for debugging)
            show_technical = os.getenv('FLASK_ENV') != 'production' or os.getenv('DEBUG_ERRORS') == 'true'
            
            if show_technical:
                error_message = f"TECHNICAL ERROR: {type(e).__name__}: {str(e)}"
                logger.error(f"❌ Showing technical error to user: {error_message}")
            else:
                error_message = self._get_user_friendly_error(str(e))
                logger.error(f"❌ Showing user-friendly error: {error_message}")
            
            logger.error(f"❌ Image processing failed with error: {error_message}")
            
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
        
        # Apply simplified filtering to reduce memory usage
        if found_books:
            logger.info("🔧 Applying lightweight filtering...")
            try:
                # Simplified filtering - just basic language and quality checks
                filtered_books = []
                for book in found_books:
                    # Basic quality filters
                    rating = book.get('average_rating', 0)
                    if rating >= 3.0 or rating == 0:  # Include unrated books
                        # Simple language check - just English preference
                        language = book.get('language', 'en')
                        if language in ['en', 'english'] or not language:
                            filtered_books.append(book)
                
                # Simple sorting by fuzzy match score only
                filtered_books.sort(
                    key=lambda x: x.get('fuzzy_match_score', 0), 
                    reverse=True
                )
                
                logger.info(f"✅ Lightweight filtering completed: {len(filtered_books)} books")
                return filtered_books[:8]  # Return top 8 results to reduce memory
                
            except Exception as e:
                logger.warning(f"⚠️ Filtering failed, returning unfiltered results: {e}")
                return found_books[:5]  # Even fewer results on fallback
        
        return found_books
    
    def _get_user_friendly_error(self, error_message: str) -> str:
        """Convert technical error messages to user-friendly ones."""
        # File and image errors
        if "Image not found" in error_message or "expired" in error_message:
            return "Image data expired or not found. Please try uploading again."
        elif "Image file not found" in error_message:
            return "Image file not found. Please try uploading again."
        elif "Image file exceeds" in error_message:
            return "Image file is too large. Please use an image smaller than 10MB."
        elif "Invalid image format" in error_message:
            return "Invalid image format. Please use JPG or PNG files."
        
        # API and service errors
        elif "GEMINI_API_KEY" in error_message:
            return "Service configuration error. Please try again later."
        elif "Gemini processing failed" in error_message or "Gemini upload failed" in error_message:
            return "AI processing failed. Please try with a different image."
        elif "timeout" in error_message.lower() or "timed out" in error_message.lower():
            return "Processing timed out. Please try again with a smaller or clearer image."
        
        # Memory and resource errors (common on Render)
        elif "MemoryError" in error_message or "memory" in error_message.lower():
            return "System resource limit reached. Please try with a smaller image."
        elif "ConnectionError" in error_message or "connection" in error_message.lower():
            return "Network connection error. Please try again in a moment."
        elif "HTTPError" in error_message and "429" in error_message:
            return "Service temporarily busy. Please wait a moment and try again."
        elif "HTTPError" in error_message and ("401" in error_message or "403" in error_message):
            return "Service authentication error. Please try again later."
        elif "HTTPError" in error_message and "500" in error_message:
            return "External service error. Please try again in a few minutes."
        
        # Content and processing errors
        elif "No books" in error_message or "empty list" in error_message:
            return "No books were detected in this image. Try with a clearer photo showing book covers or spines."
        elif "parsing" in error_message.lower() or "parsing failed" in error_message:
            return "Could not understand the AI response. Please try again."
        elif "Book search failed" in error_message:
            return "Book search failed. Please try again in a moment."
        
        # Generic fallback
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