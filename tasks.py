import os

# Force single-threaded execution for all underlying libraries
# to prevent semaphore leaks in multiprocessing environments like Celery.
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import tempfile
import threading
import ast
import uuid
import shutil
import time
from typing import List, Dict, Any
from pathlib import Path

from celery_app import celery_app
from services.books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from core.filters import create_fuzzy_searcher, create_book_filter, create_trending_detector, create_language_filter
from services.recommendation_engine import get_recommendation_engine
# OCR and frame extraction available if needed:
# from core.ocr import get_ocr_engine, extract_text_from_frames  
# from core.smart_frame_extractor import SmartFrameExtractor
import os.path
import logging
from google import genai

# Set up logging based on environment
def get_logger(name: str):
    """Get logger with production-appropriate level"""
    logger = logging.getLogger(name)
    if not logger.handlers:  # Only add handler if none exists
        handler = logging.StreamHandler()
        formatter = logging.Formatter('[%(asctime)s] %(levelname)s in %(module)s: %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        # Set log level based on environment
        log_level = logging.INFO if os.getenv('FLASK_ENV') == 'production' else logging.DEBUG
        logger.setLevel(log_level)
    
    return logger

logger = get_logger(__name__)

# YOLO model initialization removed (using Gemini AI for video analysis instead)

# File processing limits
MAX_IMAGE_SIZE_MB = 10  # 10MB max size for images
MAX_TEMP_DIR_LIFETIME = 3600  # 1 hour in seconds
MAX_PROCESSING_TIME = 300  # 5 minutes timeout for images


def cleanup_temp_directory(temp_dir: str, delay: int = MAX_TEMP_DIR_LIFETIME):
    """Schedule temp directory cleanup after delay"""
    def cleanup():
        try:
            time.sleep(delay)
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                logger.info(f"🧹 Cleaned up temp directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to cleanup temp directory {temp_dir}: {e}")
    
    cleanup_thread = threading.Thread(target=cleanup, daemon=True)
    cleanup_thread.start()

def check_file_size(file_path: str, max_size_mb: int = MAX_IMAGE_SIZE_MB) -> bool:
    """Check if file size is within limits"""
    try:
        # Resolve path to prevent path traversal
        resolved_path = Path(file_path).resolve()
        
        # Additional security check: ensure file is in expected location
        # On macOS, tempfile.gettempdir() returns /var/folders but actual paths are /private/var/folders
        temp_dir = Path(tempfile.gettempdir()).resolve()
        temp_dir_alt = Path('/private' + tempfile.gettempdir()).resolve()
        
        resolved_str = str(resolved_path)
        temp_str = str(temp_dir)
        temp_alt_str = str(temp_dir_alt)
        
        if not (resolved_str.startswith(temp_str) or resolved_str.startswith(temp_alt_str)):
            print(f"❌ File not in allowed location: {resolved_path}")
            print(f"   Expected locations: {temp_str} or {temp_alt_str}")
            return False
        
        file_size = resolved_path.stat().st_size
        file_size_mb = file_size / (1024 * 1024)
        
        if file_size_mb > max_size_mb:
            logger.warning(f"❌ File too large: {file_size_mb:.1f}MB (max: {max_size_mb}MB)")
            return False
        
        logger.debug(f"✅ File size OK: {file_size_mb:.1f}MB")
        return True
    except Exception as e:
        logger.error(f"❌ Error checking file size: {e}")
        return False

def safe_join_path(base_dir: str, filename: str) -> str:
    """Safely join paths to prevent directory traversal"""
    try:
        # Normalize the filename to remove any path traversal attempts
        clean_filename = os.path.basename(filename)
        
        # Remove any remaining path separators
        clean_filename = clean_filename.replace('/', '').replace('\\', '')
        
        # Ensure filename is not empty and doesn't start with dots
        if not clean_filename or clean_filename.startswith('.'):
            raise ValueError("Invalid filename")
        
        # Join with base directory and resolve
        full_path = Path(base_dir) / clean_filename
        resolved_path = full_path.resolve()
        
        # Ensure the resolved path is still within the base directory
        # Handle macOS /private/var vs /var symlink issue
        base_resolved = Path(base_dir).resolve()
        base_resolved_alt = None
        
        # Check for macOS /private prefix issue
        if str(base_resolved).startswith('/private/') and not str(resolved_path).startswith('/private/'):
            base_resolved_alt = Path(str(base_resolved).replace('/private', '', 1)).resolve()
        elif not str(base_resolved).startswith('/private/') and str(resolved_path).startswith('/private'):
            base_resolved_alt = Path('/private' + str(base_resolved)).resolve()
        
        resolved_str = str(resolved_path)
        base_str = str(base_resolved)
        
        path_allowed = resolved_str.startswith(base_str)
        if not path_allowed and base_resolved_alt:
            path_allowed = resolved_str.startswith(str(base_resolved_alt))
        if not path_allowed:
            raise ValueError("Path traversal detected")
        return str(resolved_path)
    
    except Exception as e:
        logger.error(f"❌ Path join error: {e}")
        raise ValueError("Invalid file path")


def _process_image_core(image_id: str, task_self=None):
    """
    Core image processing logic that can be used by both Celery tasks and local development.
    """
    logger.info(f"🚀 Starting image processing for Redis image: {image_id}")
    
    # Get image storage service
    from services.image_storage import get_image_storage_service
    image_storage = get_image_storage_service()
    
    # Define update_state function
    def update_state(state, meta):
        if task_self:
            task_self.update_state(state=state, meta=meta)
    
    # Replace self.update_state calls with update_state function
    # Continue with the rest of the processing logic...
    
    # Check cache first - use image_id as cache key
    rec_engine = get_recommendation_engine()
    cached_result = rec_engine.get_cached_results(image_id)
    if cached_result:
        logger.info(f"🎉 Cache hit! Returning cached results for: {image_id}")
        return cached_result
    
    # Temporary file path for cleanup
    temp_image_path = None
    
    try:
        # Retrieve image from Redis
        logger.info(f"📥 Retrieving image from Redis: {image_id}")
        temp_image_path = image_storage.create_temp_file(image_id)
        
        if not temp_image_path:
            raise Exception(f"Image not found in Redis or expired: {image_id}")
        
        logger.info(f"✅ Created temporary file: {temp_image_path}")
        
        # Get Gemini API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            error_msg = "GEMINI_API_KEY environment variable is required for image processing"
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        logger.info("✅ Gemini API key loaded from environment")
        genai_client = genai.Client(api_key=api_key)
        update_state(state='PROGRESS', meta={'step': 'Analyzing image', 'progress': 10})
        
        # Verify temporary file exists and check file size limits
        if not os.path.exists(temp_image_path):
            raise Exception(f"Temporary image file not found: {temp_image_path}")
            
        if not check_file_size(temp_image_path):
            raise Exception(f"Image file exceeds {MAX_IMAGE_SIZE_MB}MB size limit")

        gen_file = genai_client.files.upload(file=temp_image_path)
        # update to delay prompt
        update_state(state='PROGRESS', meta={'step': 'Processing image', 'progress': 30})
        # Check whether the file is ready to be used.
        while gen_file.state.name == "PROCESSING":
            print('.', end='')
            time.sleep(1)
            gen_file = genai_client.files.get(name=gen_file.name)

        if gen_file.state.name == "FAILED":
          raise ValueError(gen_file.state.name)
        # prompt and request
        prompt = """
        Please review this image and identify what books, if any, are present in the image. Look for book covers, spines, or any visible book titles and authors.
        Please provide results formatted as a Python list, with the following format:
        ["TITLE by AUTHOR"]
        If there are no books visible in the image, please return an empty list.
        Do NOT return in a code chunk and do NOT return with any additional text.
        """
        response = genai_client.models.generate_content(
            model="gemini-2.0-flash-lite", 
            contents=[gen_file,prompt]
        )
        update_state(state='PROGRESS', meta={'step': 'Identifying books in image', 'progress': 50})
        book_texts = ast.literal_eval(response.text)
        update_state(state='PROGRESS', meta={'step': 'Finding book details', 'progress': 85})
        print("📚 Starting book search...")
        
        books = search_books_from_text(book_texts)
        print(f"✅ Book search completed: {len(books)} books found")
        
        result = {
            'status': 'success',
            'books': books,
            #'total_detections': len(book_detections),
            'total_texts': len(book_texts)
        }
        
        # Cache the successful result using image_id as key
        rec_engine.cache_results(image_id, 'image', result)
        
        logger.info(f"🎉 Task completed successfully!")
        logger.info(f"📊 Final result: {len(books)} books, {len(book_texts)} texts")
        logger.debug(f"📚 Book titles found: {[book.get('title', 'Unknown') for book in books[:3]]}")
        
        # Clean up Redis image after successful processing
        image_storage.delete_image(image_id)
        logger.info(f"🧹 Cleaned up Redis image: {image_id}")
        
        update_state(state='PROGRESS', meta={'step': 'Complete', 'progress': 100})
        return result    
                    
    except Exception as e:
        from celery.exceptions import SoftTimeLimitExceeded
        error_message = str(e)
        
        if isinstance(e, SoftTimeLimitExceeded):
            error_message = 'Image processing timed out. Please try with a smaller image.'
        else:
            # Clean up technical error messages for user-friendly display
            if "Image not found in Redis" in error_message or "expired" in error_message:
                error_message = "Image data expired or not found. Please try uploading again."
            elif "Image file not found" in error_message:
                error_message = "Image file not found. Please try uploading again."
            elif "Image file exceeds" in error_message:
                error_message = "Image file is too large. Please use an image smaller than 10MB."
            elif "No books" in error_message or "empty list" in error_message:
                error_message = "No books were detected in this image. Try with a clearer photo showing book covers or spines."
            elif "Invalid image format" in error_message:
                error_message = "Invalid image format. Please use JPG or PNG files."
        
        logger.error(f"Image processing failed: {e}")  # Log the technical error
        
        # Cleanup on error
        try:
            # Clean up temporary file
            if temp_image_path and os.path.exists(temp_image_path):
                os.unlink(temp_image_path)
                logger.info(f"🧹 Cleaned up temp file: {temp_image_path}")
            
            # Clean up Redis image
            if image_storage:
                image_storage.delete_image(image_id)
                logger.info(f"🧹 Cleaned up Redis image: {image_id}")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Cleanup failed: {cleanup_error}")
        
        return {
            'status': 'error',
            'error': error_message  # Return user-friendly error
        }
    
    finally:
        # Final cleanup - ensure temp file is removed
        try:
            if temp_image_path and os.path.exists(temp_image_path):
                os.unlink(temp_image_path)
                logger.info(f"🧹 Final cleanup: removed temp file {temp_image_path}")
        except Exception as cleanup_error:
            logger.warning(f"⚠️ Final cleanup failed: {cleanup_error}")


@celery_app.task(bind=True, time_limit=MAX_PROCESSING_TIME, soft_time_limit=MAX_PROCESSING_TIME-30)
def process_image(self, image_id: str):
    """
    Celery task to process an image and extract books from it.
    Now retrieves image data from Redis using image_id.
    """
    return _process_image_core(image_id, task_self=self)


def search_books_from_text(texts: List[str]) -> List[Dict]:
    """Search for using extracted text with fuzzy matching for near-misses"""
    print(f"📚 Starting fuzzy book search with {len(texts)} text extractions")
    
    # Create fuzzy searcher
    print("CONSTRUCTOR")
    print(texts)
    # Instantiate a GoogleBooksClient for searching
    books_client = GoogleBooksClient()
    fuzzy_searcher = create_fuzzy_searcher(books_client)
    found_books = []
    seen_titles = set()
    search_delay=0.1
    search_queries=texts
    print("OUTSIDE LOOP")
    print(search_queries)
    for i, clean_text in enumerate(search_queries):
        print("ENTERED LOOP")
        #if len(found_books) >= 15:  # Increased limit to collect more unique books
        #    print(f"📚 Reached book limit (15), stopping search")
        #    break
            
        try:
            print(f"\n🔮 Fuzzy search {i+1}/{len(search_queries)}: '{clean_text}'")
            
            # Add delay between searches (except first one)
            if i > 0:
                time.sleep(search_delay)
            
            # Use fuzzy search with fallback
            search_results = fuzzy_searcher.search_with_fuzzy_matching(clean_text, max_results=1)
            
            books_added_this_search = 0
            for book in search_results:
                #if len(found_books) >= 8:
                #    break
                    
                book_title = book.get('title', '').lower()
                if book_title not in seen_titles:
                    # Add purchase and reader app links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    
                    # Add fuzzy match info if available
                    if 'fuzzy_match_score' in book:
                        book['match_info'] = {
 'ocr_text': clean_text,
                            'fuzzy_score': book['fuzzy_match_score'],
                            'fuzzy_query': book.get('fuzzy_query', clean_text)
                        }
                    
                    found_books.append(book)
                    seen_titles.add(book_title)
                    books_added_this_search += 1
                    
                    match_score = book.get('fuzzy_match_score', 1.0)
                    fuzzy_info = f" (fuzzy: {match_score:.2f})" if 'fuzzy_match_score' in book else ""
                    print(f"✅ Found book: {book.get('title', 'Unknown')}{fuzzy_info}")
                    
                    # Limit books per search to 2
                    if books_added_this_search >= 5:
                        break
            
            if not search_results:
                print(f"❌ No fuzzy results for: '{clean_text}'")
                        
        except Exception as e:
            print(f"❌ Fuzzy search error for '{clean_text}': {e}")
            # Add extra delay after errors
            time.sleep(2.0)
            continue
    
    print(f"\n🎯 Fuzzy search found {len(found_books)} books, now filtering for quality...")
    
    # Instead of filtering, simply sort by popularity_score if available
    if found_books:
        # Ensure each book has a popularity_score; if missing, default to 0
        for book in found_books:
            if 'google_score' not in book:
                book['google_score'] = 0
        # Sort descending by popularity_score
        found_books.sort(key=lambda b: b.get('popularity_score', 0.0), reverse=True)
        print(f"🏆 Final sorted books by popularity: {len(found_books)} entries")
        return found_books
    
    return found_books
