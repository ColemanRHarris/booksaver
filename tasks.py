import os
import tempfile
import cv2
import yt_dlp
import pytesseract
from ultralytics import YOLO
from celery_app import celery_app
from books_client import GoogleBooksClient, build_purchase_links, build_reader_app_links
import uuid
import shutil
import time
from typing import List, Dict, Any
import numpy as np

# Initialize YOLO model (will download on first use)
model = None

def get_yolo_model():
    """Get YOLO model, initializing if needed"""
    global model
    if model is None:
        import torch
        # Temporarily set weights_only to False for YOLO loading
        original_setting = getattr(torch, '_global_default_type_conversion', None)
        try:
            model = YOLO('yolov8s.pt', task='detect')  # Small model for faster processing
        except Exception as e:
            print(f"YOLO loading error: {e}")
            # Fallback: try without weights restrictions
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = YOLO('yolov8s.pt')
    return model

@celery_app.task(bind=True)
def process_tiktok_video(self, tiktok_url: str):
    """
    Celery task to process TikTok video and extract books
    """
    print(f"🚀 Starting TikTok processing for: {tiktok_url}")
    try:
        # Update task status
        print("📊 Updating task status to PROGRESS")
        self.update_state(state='PROGRESS', meta={'step': 'Downloading video', 'progress': 10})
        
        # Create temporary directory for this task
        temp_dir = tempfile.mkdtemp(prefix=f"tiktok_{uuid.uuid4().hex}_")
        print(f"📁 Created temp directory: {temp_dir}")
        video_path = None
        
        try:
            # Download TikTok video
            video_path = download_tiktok_video(tiktok_url, temp_dir)
            print(f"✅ Video downloaded successfully: {video_path}")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting frames', 'progress': 30})
            print("🖼️  Starting frame extraction...")
            
            # Extract frames from video
            frames = extract_frames(video_path)
            print(f"✅ Extracted {len(frames)} frames")
            
            self.update_state(state='PROGRESS', meta={'step': 'Detecting objects', 'progress': 50})
            print("🔍 Starting object detection...")
            
            # Detect books in frames using YOLO
            book_detections = detect_books_in_frames(frames)
            print(f"✅ Object detection completed: {len(book_detections)} frame detections")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting text', 'progress': 70})
            print("📝 Starting text extraction...")
            
            # Extract text from detected book regions
            book_texts = extract_text_from_detections(frames, book_detections)
            print(f"✅ Text extraction completed: {len(book_texts)} texts found")
            print(f"📋 Extracted texts: {book_texts[:5]}")  # Show first 5 texts
            
            self.update_state(state='PROGRESS', meta={'step': 'Finding book details', 'progress': 85})
            print("📚 Starting book search...")
            
            # Search for books using extracted text
            books = search_books_from_text(book_texts)
            print(f"✅ Book search completed: {len(books)} books found")
            
            self.update_state(state='PROGRESS', meta={'step': 'Complete', 'progress': 100})
            
            result = {
                'status': 'success',
                'books': books,
                'total_detections': len(book_detections),
                'total_texts': len(book_texts)
            }
            
            print(f"🎉 Task completed successfully!")
            print(f"📊 Final result: {len(books)} books, {len(book_detections)} detections, {len(book_texts)} texts")
            print(f"📚 Book titles found: {[book.get('title', 'Unknown') for book in books[:3]]}")
            
            return result
            
        finally:
            # Cleanup temporary files
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

def download_tiktok_video(url: str, output_dir: str) -> str:
    """Download TikTok video using yt-dlp"""
    print(f"⬇️  Starting download of: {url}")
    print(f"📂 Output directory: {output_dir}")
    
    ydl_opts = {
        'outtmpl': os.path.join(output_dir, 'video.%(ext)s'),
        #'format': 'best[height<=720]',  # Limit quality for faster processing
        'quiet': False,  # Enable output for debugging
        'no_warnings': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("🔄 Starting yt-dlp download...")
            ydl.download([url])
            print("✅ yt-dlp download completed")
    except Exception as e:
        print(f"❌ yt-dlp download failed: {e}")
        raise
    
    # Find the downloaded video file
    print("🔍 Looking for downloaded video file...")
    files = os.listdir(output_dir)
    print(f"📋 Files in directory: {files}")
    
    for file in files:
        if file.startswith('video.') and file.endswith(('.mp4', '.webm', '.mkv')):
            video_path = os.path.join(output_dir, file)
            print(f"✅ Found video: {video_path}")
            return video_path
    
    print("❌ No video file found after download")
    raise Exception("Video download failed - no output file found")

def extract_frames(video_path: str, fps: float = 0.5) -> List[np.ndarray]:
    """Extract frames from video with smart selection for book detection"""
    cap = cv2.VideoCapture(video_path)
    frames = []
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    duration = total_frames / video_fps if video_fps > 0 else 0
    
    print(f"📹 Video info: {total_frames} frames, {video_fps:.1f} fps, {duration:.1f}s")
    
    # Skip first and last 10% of video (often transitions/text overlays)
    start_frame = int(total_frames * 0.1)
    end_frame = int(total_frames * 0.9)
    
    # Calculate frame interval for desired FPS
    frame_interval = max(1, int(video_fps / fps))
    
    frame_count = 0
    selected_frames = []
    
    while True:
        ret, frame = cap.read()
        if not ret or frame_count >= end_frame:
            break
        
        # Start collecting after skip period
        if frame_count >= start_frame and frame_count % frame_interval == 0:
            # Basic frame quality check
            if is_good_frame_for_detection(frame):
                selected_frames.append(frame)
            
        frame_count += 1
        
        # Limit to 20 frames max for efficiency
        if len(selected_frames) >= 20:
            break
    
    cap.release()
    print(f"📊 Selected {len(selected_frames)} frames for processing")
    return selected_frames

def is_good_frame_for_detection(frame: np.ndarray) -> bool:
    """Check if frame is suitable for book detection"""
    if frame is None or frame.size == 0:
        return False
    
    # Convert to grayscale for analysis
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # Check if frame is too dark or too bright
    mean_brightness = np.mean(gray)
    if mean_brightness < 30 or mean_brightness > 220:
        return False
    
    # Check for motion blur (low variance indicates blur)
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < 100:  # Too blurry
        return False
    
    # Check for sufficient detail/edges (books usually have text/edges)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = np.sum(edges > 0) / edges.size
    if edge_density < 0.02:  # Too few edges
        return False
    
    return True

def detect_books_in_frames(frames: List[np.ndarray]) -> List[List[Dict]]:
    """Detect objects (potentially books) in frames using YOLO"""
    print(f"🤖 Loading YOLO model...")
    model = get_yolo_model()
    print(f"✅ YOLO model loaded successfully")
    
    all_detections = []
    
    for i, frame in enumerate(frames):
        print(f"🔍 Processing frame {i+1}/{len(frames)}")
        # Run YOLO detection
        results = model(frame, verbose=False)
        
        frame_detections = []
        for result in results:
            boxes = result.boxes
            if boxes is not None:
                for i, box in enumerate(boxes):
                    # Get confidence and class
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = model.names[class_id]
                    
                    # We're looking for book-like objects
                    # YOLO classes that might contain books or be books themselves
                    book_related_classes = ['book', 'person', 'laptop', 'cell phone', 'tv', 'dining table', 'bed']
                    
                    # Be more selective about confidence thresholds
                    min_confidence = 0.3 if class_name == 'book' else 0.6
                    
                    if class_name in book_related_classes and confidence > min_confidence:
                        
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        
                        # Calculate aspect ratio and size
                        width = x2 - x1
                        height = y2 - y1
                        aspect_ratio = width / height if height > 0 else 0
                        area = width * height
                        
                        # Filter by size and aspect ratio (books are usually rectangular)
                        # Skip very small detections or weird aspect ratios
                        if area > 1000 and 0.2 < aspect_ratio < 5.0:
                            frame_detections.append({
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'confidence': confidence,
                                'class': class_name,
                                'aspect_ratio': aspect_ratio,
                                'area': area
                            })
        
        all_detections.append(frame_detections)
    
    return all_detections

def enhance_image_for_ocr(image: np.ndarray) -> np.ndarray:
    """Apply simple, fast image enhancement for OCR"""
    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    # Simple contrast enhancement - much faster than CLAHE
    alpha = 1.2  # Contrast control
    beta = 10    # Brightness control
    enhanced = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)
    
    return enhanced

def extract_text_from_detections(frames: List[np.ndarray], detections: List[List[Dict]]) -> List[str]:
    """Extract text from detected regions using simple, fast OCR"""
    texts = []
    
    for frame_idx, (frame, frame_detections) in enumerate(zip(frames, detections)):
        print(f"🔍 Processing frame {frame_idx + 1} with {len(frame_detections)} detections")
        
        for det_idx, detection in enumerate(frame_detections):
            x1, y1, x2, y2 = detection['bbox']
            
            # Add padding around detection for better context
            padding = 10
            h, w = frame.shape[:2]
            x1 = max(0, x1 - padding)
            y1 = max(0, y1 - padding)
            x2 = min(w, x2 + padding)
            y2 = min(h, y2 + padding)
            
            # Crop the detected region
            cropped = frame[y1:y2, x1:x2]
            
            # Skip very small detections
            if cropped.shape[0] < 20 or cropped.shape[1] < 20:
                continue
            
            # Resize if too small (OCR works better on larger images)
            if cropped.shape[0] < 50 or cropped.shape[1] < 50:
                scale_factor = max(50 / cropped.shape[0], 50 / cropped.shape[1])
                new_width = int(cropped.shape[1] * scale_factor)
                new_height = int(cropped.shape[0] * scale_factor)
                cropped = cv2.resize(cropped, (new_width, new_height), interpolation=cv2.INTER_CUBIC)
            
            try:
                # Apply single, fast image enhancement
                enhanced_img = enhance_image_for_ocr(cropped)
                
                # Convert to RGB for Tesseract
                if len(enhanced_img.shape) == 2:  # Grayscale
                    rgb_img = cv2.cvtColor(enhanced_img, cv2.COLOR_GRAY2RGB)
                else:
                    rgb_img = cv2.cvtColor(enhanced_img, cv2.COLOR_BGR2RGB)
                
                # Simple OCR with single, reliable configuration
                ocr_config = '--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\\ '
                
                text = pytesseract.image_to_string(rgb_img, config=ocr_config)
                cleaned_text = clean_ocr_text(text)
                
                # Debug: Show all OCR results
                if text.strip():
                    print(f"🔤 Raw OCR: '{text.strip()}' -> Cleaned: '{cleaned_text}'")
                
                if cleaned_text and len(cleaned_text) > 3 and is_likely_book_title(cleaned_text):
                    texts.append(cleaned_text)
                    print(f"✅ Accepted as book title: '{cleaned_text}'")
                elif cleaned_text:
                    print(f"❌ Rejected as non-book: '{cleaned_text}'")
                
            except Exception as e:
                print(f"❌ OCR error on detection {det_idx}: {e}")
                continue
    
    # Remove duplicates while preserving order
    unique_texts = []
    seen = set()
    for text in texts:
        text_lower = text.lower()
        if text_lower not in seen:
            unique_texts.append(text)
            seen.add(text_lower)
    
    print(f"📝 Total unique texts extracted: {len(unique_texts)}")
    return unique_texts

def clean_ocr_text(text: str) -> str:
    """Clean OCR text to make better search queries"""
    import re
    
    if not text:
        return ""
    
    # Initial cleanup
    text = text.strip()
    
    # Common OCR misreads and corrections
    ocr_corrections = {
        '|': 'I',
        '1': 'I',
        '0': 'O',
        '5': 'S',
        '8': 'B',
        '@': 'a',
        '€': 'e',
        'rn': 'm',
        'cl': 'd',
        'vv': 'w',
        'ii': 'n',
        'll': 'n',
        '6': 'G',
        ')': '',
        '(': '',
    }
    
    # Apply corrections
    for wrong, correct in ocr_corrections.items():
        text = text.replace(wrong, correct)
    
    # Remove special characters but keep spaces, hyphens, and apostrophes
    text = re.sub(r'[^\w\s\-\']', ' ', text)
    
    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    
    # Remove standalone single characters except 'A' and 'I'
    words = text.split()
    cleaned_words = []
    for word in words:
        if len(word) == 1 and word.upper() not in ['A', 'I']:
            continue
        if len(word) >= 2 or word.upper() in ['A', 'I']:
            cleaned_words.append(word)
    
    text = ' '.join(cleaned_words)
    
    # Title case common words
    text = re.sub(r'\bthe\b', 'The', text, flags=re.IGNORECASE)
    text = re.sub(r'\band\b', 'and', text, flags=re.IGNORECASE)
    text = re.sub(r'\bof\b', 'of', text, flags=re.IGNORECASE)
    text = re.sub(r'\bin\b', 'in', text, flags=re.IGNORECASE)
    text = re.sub(r'\bto\b', 'to', text, flags=re.IGNORECASE)
    
    return text.strip()

def is_likely_book_title(text: str) -> bool:
    """Check if text looks like it could be a book title"""
    import re
    
    if not text or len(text) < 3:
        return False
    
    # Must have at least some alphabetic characters
    alpha_count = sum(1 for c in text if c.isalpha())
    if alpha_count < 2:
        return False
    
    # Calculate letter-to-total ratio
    letter_ratio = alpha_count / len(text.replace(' ', ''))
    if letter_ratio < 0.5:  # At least 50% letters
        return False
    
    words = text.split()
    text_lower = text.lower()
    
    # Filter out common non-book words that appear in videos
    common_junk_words = [
        'test', 'testing', 'demo', 'sample', 'example',
        'video', 'tiktok', 'follow', 'like', 'subscribe',
        'watch', 'view', 'click', 'tap', 'swipe',
        'music', 'sound', 'audio', 'play', 'pause',
        'share', 'comment', 'hashtag', 'viral',
        'live', 'stream', 'online', 'app', 'phone',
        'screen', 'display', 'menu', 'button', 'link'
    ]
    
    # Reject if the text is just common junk words
    if text_lower in common_junk_words:
        return False
    
    # Reject if all words are junk words
    if all(word.lower() in common_junk_words for word in words):
        return False
    
    # Filter out single-word texts that are too short
    if len(words) == 1:
        if len(text) < 4:  # Single words must be at least 4 characters
            return False
        # Allow common single-word book titles
        if text.lower() in ['dune', 'emma', 'beloved', 'it', 'gone', 'room']:
            return True
        # Reject single junk words
        if text.lower() in common_junk_words:
            return False
    
    # Filter out obvious non-book text patterns
    non_book_patterns = [
        r'^\d+$',  # Only numbers
        r'^[A-Z]{1,3}$',  # Only 1-3 capital letters
        r'page \d+',  # Page numbers
        r'chapter \d+',  # Chapter references
        r'^www\.',  # URLs
        r'@\w+',  # Social media handles
        r'^\$\d+',  # Prices
        r'^\d+%$',  # Percentages
        r'^loading',  # Loading text
        r'^buffering',  # Buffering text
    ]
    
    for pattern in non_book_patterns:
        if re.match(pattern, text, re.IGNORECASE):
            return False
    
    # Check for common book title indicators
    book_indicators = [
        'the ', 'a ', 'an ',  # Articles
        'and', 'of', 'in', 'to', 'for',  # Common prepositions
        'book', 'novel', 'story', 'tales',  # Book-related words
    ]
    
    has_indicator = any(indicator in text_lower for indicator in book_indicators)
    
    # More lenient for texts with book indicators
    if has_indicator and len(words) >= 2:
        return True
    
    # For other texts, require reasonable length and word count
    # But be more strict - require at least 2 words and 8 characters
    if len(words) >= 2 and len(text) >= 8:
        return True
    
    return False

def search_books_from_text(texts: List[str]) -> List[Dict]:
    """Search for books using extracted text with conservative API usage"""
    print(f"📚 Starting book search with {len(texts)} text extractions")
    
    books_client = GoogleBooksClient()
    found_books = []
    seen_titles = set()
    processed_queries = set()
    
    # Clean and filter texts more aggressively to reduce API calls
    cleaned_texts = []
    for text in texts:
        clean_text = clean_ocr_text(text)
        if is_likely_book_title(clean_text) and clean_text.lower() not in processed_queries:
            # Additional filtering for production
            if len(clean_text) >= 4 and len(clean_text.split()) >= 2:
                cleaned_texts.append(clean_text)
                processed_queries.add(clean_text.lower())
    
    # Limit the number of API calls to avoid rate limits
    max_searches = min(len(cleaned_texts), 8)  # Reduced from 15 to 8
    cleaned_texts = cleaned_texts[:max_searches]
    
    print(f"📝 Will search for {len(cleaned_texts)} book titles: {cleaned_texts}")
    
    # Add delay between searches to avoid rate limiting
    search_delay = 0.5  # 500ms between searches
    
    for i, clean_text in enumerate(cleaned_texts):
        if len(found_books) >= 10:  # Reduced limit to 10 total books
            print(f"📚 Reached book limit (10), stopping search")
            break
            
        try:
            print(f"🔍 Search {i+1}/{len(cleaned_texts)}: '{clean_text}'")
            
            # Add delay between searches (except first one)
            if i > 0:
                time.sleep(search_delay)
            
            # Search for books using the extracted text
            search_results = books_client.search_books(clean_text, max_results=3)  # Reduced from 5 to 3
            
            books_added_this_search = 0
            for book in search_results:
                if len(found_books) >= 10:
                    break
                    
                book_title = book.get('title', '').lower()
                if book_title not in seen_titles:
                    # Add purchase and reader app links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    
                    found_books.append(book)
                    seen_titles.add(book_title)
                    books_added_this_search += 1
                    
                    print(f"✅ Found book: {book.get('title', 'Unknown')}")
                    
                    # Limit books per search to 2
                    if books_added_this_search >= 2:
                        break
            
            if not search_results:
                print(f"❌ No results for: '{clean_text}'")
                        
        except Exception as e:
            print(f"❌ Search error for '{clean_text}': {e}")
            # Add extra delay after errors
            time.sleep(1.0)
            continue
    
    print(f"🎯 Final book search result: {len(found_books)} unique books found")
    print(f"📊 Books found: {[book.get('title', 'Unknown')[:30] for book in found_books]}")
    
    return found_books