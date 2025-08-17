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

def extract_frames(video_path: str, fps: float = 1.0) -> List[np.ndarray]:
    """Extract frames from video at specified FPS"""
    cap = cv2.VideoCapture(video_path)
    frames = []
    
    video_fps = cap.get(cv2.CAP_PROP_FPS)
    frame_interval = int(video_fps / fps)  # Take 1 frame per second
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_count % frame_interval == 0:
            frames.append(frame)
            
        frame_count += 1
        
        # Limit to 30 frames max to avoid processing too much
        if len(frames) >= 30:
            break
    
    cap.release()
    return frames

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
                    # YOLO classes that might be books: book (84), or general objects with high confidence
                    if (class_name == 'book' or 
                        (confidence > 0.5 and class_name in ['book', 'person', 'laptop', 'cell phone'])):
                        
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        
                        frame_detections.append({
                            'bbox': [int(x1), int(y1), int(x2), int(y2)],
                            'confidence': confidence,
                            'class': class_name
                        })
        
        all_detections.append(frame_detections)
    
    return all_detections

def extract_text_from_detections(frames: List[np.ndarray], detections: List[List[Dict]]) -> List[str]:
    """Extract text from detected regions using OCR"""
    texts = []
    
    for frame, frame_detections in zip(frames, detections):
        for detection in frame_detections:
            x1, y1, x2, y2 = detection['bbox']
            
            # Crop the detected region
            cropped = frame[y1:y2, x1:x2]
            
            # Convert to RGB (Tesseract expects RGB)
            cropped_rgb = cv2.cvtColor(cropped, cv2.COLOR_BGR2RGB)
            
            # Extract text using Tesseract
            try:
                text = pytesseract.image_to_string(cropped_rgb, config='--psm 6')
                text = text.strip()
                
                # Only keep text that might be book titles (length > 3, contains letters)
                if len(text) > 3 and any(c.isalpha() for c in text):
                    texts.append(text)
                    
            except Exception as e:
                print(f"OCR error: {e}")
                continue
    
    return texts

def clean_ocr_text(text: str) -> str:
    """Clean OCR text to make better search queries"""
    import re
    
    # Remove special characters and normalize
    text = re.sub(r'[^\w\s]', ' ', text)  # Remove non-alphanumeric except spaces
    text = re.sub(r'\s+', ' ', text)      # Normalize whitespace
    text = text.strip()
    
    # Remove common OCR artifacts
    text = text.replace('/', ' ')
    text = text.replace('\\', ' ')
    text = re.sub(r'\b[a-zA-Z]\b', '', text)  # Remove single letters
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text

def is_likely_book_title(text: str) -> bool:
    """Check if text looks like it could be a book title"""
    if len(text) < 3:
        return False
    
    # Must have at least some alphabetic characters
    if not any(c.isalpha() for c in text):
        return False
    
    # Filter out very short or single-word texts unless they look promising
    words = text.split()
    if len(words) == 1 and len(text) < 6:
        return False
    
    # Filter out obviously garbled OCR
    if len([c for c in text if c.isalpha()]) / len(text) < 0.6:
        return False
    
    return True

def search_books_from_text(texts: List[str]) -> List[Dict]:
    """Search for books using extracted text"""
    print(f"📚 Starting book search with {len(texts)} text extractions")
    
    books_client = GoogleBooksClient()
    found_books = []
    seen_titles = set()
    processed_queries = set()
    
    # Clean and filter texts
    cleaned_texts = []
    for text in texts:
        clean_text = clean_ocr_text(text)
        if is_likely_book_title(clean_text) and clean_text.lower() not in processed_queries:
            cleaned_texts.append(clean_text)
            processed_queries.add(clean_text.lower())
    
    print(f"📝 Cleaned texts for search: {cleaned_texts[:10]}")  # Show first 10
    
    for clean_text in cleaned_texts:
        if len(found_books) >= 15:  # Increased limit
            break
            
        try:
            print(f"🔍 Searching for: '{clean_text}'")
            # Search for books using the extracted text
            search_results = books_client.search_books(clean_text, max_results=5)
            
            for book in search_results:
                book_title = book.get('title', '').lower()
                if book_title not in seen_titles:
                    # Add purchase and reader app links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    
                    found_books.append(book)
                    seen_titles.add(book_title)
                    print(f"✅ Found book: {book.get('title', 'Unknown')}")
                    
                    # Limit results to avoid overwhelming the user
                    if len(found_books) >= 15:
                        break
                        
        except Exception as e:
            print(f"❌ Search error for '{clean_text}': {e}")
            continue
    
    print(f"🎯 Final book search result: {len(found_books)} unique books found")
    return found_books