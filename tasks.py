import os

# Force single-threaded execution for all underlying libraries
# to prevent semaphore leaks in multiprocessing environments like Celery.
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

import tempfile
import yt_dlp
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
MAX_VIDEO_SIZE_MB = 100  # 100MB max size
MAX_TEMP_DIR_LIFETIME = 3600  # 1 hour in seconds
MAX_PROCESSING_TIME = 600  # 10 minutes timeout


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

def check_file_size(file_path: str, max_size_mb: int = MAX_VIDEO_SIZE_MB) -> bool:
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


@celery_app.task(bind=True, time_limit=MAX_PROCESSING_TIME, soft_time_limit=MAX_PROCESSING_TIME-60)
def process_video(self, video_url: str, video_type: str):
    """
    Celery task to process a video (TikTok, Instagram Reel) and extract books.
    """
    logger.info(f"🚀 Starting {video_type.title()} video processing for: {video_url}")
    
    # Check cache first
    rec_engine = get_recommendation_engine()
    cached_result = rec_engine.get_cached_results(video_url)
    if cached_result:
        logger.info(f"🎉 Cache hit! Returning cached results for: {video_url[:50]}...")
        return cached_result
    
    try:
        # Get Gemini API key from environment
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            error_msg = "GEMINI_API_KEY environment variable is required for video processing"
            logger.error(f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        logger.info("✅ Gemini API key loaded from environment")
        genai_client = genai.Client(api_key=api_key)
        self.update_state(state='PROGRESS', meta={'step': 'Downloading video', 'progress': 10})
        
        temp_dir_prefix = f"{video_type}_{uuid.uuid4().hex}_"
        temp_dir = tempfile.mkdtemp(prefix=temp_dir_prefix)
        logger.debug(f"📁 Created temp directory: {temp_dir}")
        
        # Schedule cleanup of temp directory
        cleanup_temp_directory(temp_dir)
        
        video_path = None
        video_path = download_video(video_url, temp_dir)
        logger.info(f"✅ Video downloaded successfully: {video_path}")
        
        # Check file size limits
        if not check_file_size(video_path):
            raise Exception(f"Video file exceeds {MAX_VIDEO_SIZE_MB}MB size limit")

        gen_file = genai_client.files.upload(file=video_path)
        # update to delay prompt
        self.update_state(state='PROGRESS', meta={'step': 'Extracting frames', 'progress': 30})
        # Check whether the file is ready to be used.
        while gen_file.state.name == "PROCESSING":
            print('.', end='')
            time.sleep(1)
            gen_file = genai_client.files.get(name=gen_file.name)

        if gen_file.state.name == "FAILED":
          raise ValueError(gen_file.state.name)
        # prompt and request
        prompt = """
        Please review this video and tell me what books, if any, are present in the video. 
        Please provide results formatted as a Python, with the following format:
        ["TITLE by AUTHOR"]
        If there are no videos, please return an empty list.
        Do NOT return in a code chunk and do NOT return with any additional text.
        """
        response = genai_client.models.generate_content(
            model="gemini-2.0-flash-lite", 
            contents=[gen_file,prompt]
        )
        self.update_state(state='PROGRESS', meta={'step': 'Selecting books from shelves', 'progress': 50})
        book_texts = ast.literal_eval(response.text)
        self.update_state(state='PROGRESS', meta={'step': 'Finding book details', 'progress': 85})
        print("📚 Starting book search...")
        
        books = search_books_from_text(book_texts)
        print(f"✅ Book search completed: {len(books)} books found")
        
        result = {
            'status': 'success',
            'books': books,
            #'total_detections': len(book_detections),
            'total_texts': len(book_texts)
        }
        
        # Cache the successful result
        rec_engine.cache_results(video_url, video_type, result)
        
        logger.info(f"🎉 Task completed successfully!")
        logger.info(f"📊 Final result: {len(books)} books, {len(book_texts)} texts")
        logger.debug(f"📚 Book titles found: {[book.get('title', 'Unknown') for book in books[:3]]}")
        
        self.update_state(state='PROGRESS', meta={'step': 'Complete', 'progress': 100})
        return result    
                    
    except Exception as e:
        from celery.exceptions import SoftTimeLimitExceeded
        error_message = str(e)
        
        if isinstance(e, SoftTimeLimitExceeded):
            error_message = 'Video processing timed out. Please try with a shorter video.'
        else:
            # Clean up technical error messages for user-friendly display
            if "Unable to download webpage: HTTP Error 404" in error_message:
                error_message = "Video not found. The video may have been deleted, made private, or the URL may be incorrect."
            elif "HTTP Error 403" in error_message:
                error_message = "Access denied. The video may be private or age-restricted."
            elif "Video unavailable" in error_message:
                error_message = "Video is unavailable. It may have been removed or made private."
            elif "Sign in to confirm" in error_message or "login" in error_message.lower():
                error_message = "This video requires login to access. Please use a public video."
            elif "Age-restricted" in error_message:
                error_message = "This video is age-restricted and cannot be processed."
        
        logger.error(f"Video processing failed: {e}")  # Log the technical error
        return {
            'status': 'error',
            'error': error_message  # Return user-friendly error
        }

def normalize_tiktok_url(url: str) -> str:
    """Normalize TikTok URL to the correct format"""
    import re
    
    # If it already has @ in the username part, return as is
    if '/@' in url:
        return url
    
    # Convert format like tiktok.com/username/video/123 to tiktok.com/@username/video/123
    # More flexible pattern to handle various URL structures
    tiktok_pattern = r'(https?://(?:www\.)?tiktok\.com/)([^/@?\s]+)((?:/video/\d+)?(?:\?.*)?)'
    match = re.match(tiktok_pattern, url.strip())
    
    if match:
        base_url, username, rest = match.groups()
        # Only add @ if username doesn't start with it and isn't a known system path
        system_paths = ['explore', 'discover', 'trending', 'search', 'foryou', 'following', 'live']
        if not username.startswith('@') and username not in system_paths:
            normalized = f"{base_url}@{username}{rest or ''}"
            print(f"🔄 TikTok URL normalization: {url} -> {normalized}")
            return normalized
    
    return url

def download_video(url: str, output_dir: str) -> str:
    """Download video using yt-dlp (supports TikTok, Instagram, etc.)"""
    
    # Normalize TikTok URLs to proper format
    if 'tiktok.com' in url.lower():
        original_url = url
        url = normalize_tiktok_url(url)
        if url != original_url:
            print(f"🔄 Normalized URL: {original_url} -> {url}")
    
    if 'instagram' in url.lower():
        original_url = url
        url 

    print(f"⬇️  Starting download of: {url}")
    print(f"📂 Output directory: {output_dir}")
    
    # Use safe path joining for output template
    try:
        safe_output_path = safe_join_path(output_dir, 'video.%(ext)s')
        base_dir = os.path.dirname(safe_output_path)
        output_template = os.path.join(base_dir, 'video.%(ext)s')
    except Exception:
        # Fallback to secure directory
        output_template = os.path.join(output_dir, 'video.%(ext)s')
    
    ydl_opts = {
        'outtmpl': output_template,
        'quiet': False,
        'no_warnings': False,
        # Add more robust options for social media platforms
        'format': 'best[height<=720]/best',  # Prefer lower quality for faster processing
        'extract_flat': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
        'ignoreerrors': False,
        # Add user agent and headers to avoid blocking
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        },
        # Add timeout settings
        'socket_timeout': 30,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("🔄 Starting yt-dlp download...")
            
            # First try to extract info to check if URL is valid
            try:
                print("🔍 Extracting video info...")
                info = ydl.extract_info(url, download=False)
                title = info.get('title', 'Unknown')
                duration = info.get('duration', 'Unknown')
                print(f"📱 Video found: '{title}' (duration: {duration}s)")
            except Exception as info_error:
                print(f"❌ Failed to extract video info: {info_error}")
                # Common error messages that users should understand
                error_msg = str(info_error).lower()
                if '404' in error_msg or 'not found' in error_msg:
                    raise Exception("Video not found. The URL may be incorrect, the video may have been deleted, or it may be private.")
                elif 'private' in error_msg or 'unavailable' in error_msg:
                    raise Exception("Video is private or unavailable. Please use a public video URL.")
                elif 'age-restricted' in error_msg or 'login' in error_msg:
                    raise Exception("Video is age-restricted or requires login. Please use a different video.")
                else:
                    raise Exception(f"Unable to access video: {info_error}")
            
            # If info extraction succeeded, proceed with download
            print("⬇️  Downloading video...")
            ydl.download([url])
            print("✅ yt-dlp download completed")
            
    except Exception as e:
        error_msg = str(e)
        print(f"❌ yt-dlp download failed: {error_msg}")
        # Clean up error messages for users
        if "ERROR:" in error_msg and "[" in error_msg:
            # Extract the actual error from yt-dlp format
            try:
                # Remove ANSI color codes
                import re
                clean_error = re.sub(r'\x1b\[[0-9;]*m', '', error_msg)
                if "]" in clean_error:
                    actual_error = clean_error.split("]", 1)[1].strip()
                    if actual_error:
                        error_msg = actual_error
            except:
                pass
        
        raise Exception(error_msg)
    
    print("🔍 Looking for downloaded video file...")
    try:
        files = os.listdir(output_dir)
        print(f"📋 Files in directory: {files}")
        
        for file in files:
            # Validate filename to prevent path traversal
            if file.startswith('video.') and file.endswith(('.mp4', '.webm', '.mkv', '.mov')):
                # Use safe path joining
                try:
                    video_path = safe_join_path(output_dir, file)
                    print(f"✅ Found video: {video_path}")
                    return video_path
                except ValueError as e:
                    print(f"⚠️ Skipping potentially unsafe file: {file} ({e})")
                    continue
    except Exception as e:
        print(f"❌ Error listing directory: {e}")
        raise Exception("Failed to list downloaded files")
    
    print("❌ No video file found after download")
    raise Exception("Video download failed - no output file found")

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
        if len(found_books) >= 15:  # Increased limit to collect more unique books
            print(f"📚 Reached book limit (15), stopping search")
            break
            
        try:
            print(f"\n🔮 Fuzzy search {i+1}/{len(search_queries)}: '{clean_text}'")
            
            # Add delay between searches (except first one)
            if i > 0:
                time.sleep(search_delay)
            
            # Use fuzzy search with fallback
            search_results = fuzzy_searcher.search_with_fuzzy_matching(clean_text, max_results=1)
            
            books_added_this_search = 0
            for book in search_results:
                if len(found_books) >= 8:
                    break
                    
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
