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
import pytesseract

# Handle OpenCV import conflicts and threading issues
try:
    import cv2
    # Fix common OpenCV threading issues
    if hasattr(cv2, 'setNumThreads'):
        cv2.setNumThreads(0)  # Prevent threading issues with multiprocessing
except Exception as e:
    print(f"Warning: OpenCV import issue: {e}")
    import cv2  # Try again

from ultralytics import YOLO
from celery_app import celery_app
from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from ocr_backends import get_ocr_engine
from fuzzy_search import create_fuzzy_searcher
from book_filters import create_book_filter, create_trending_detector
from language_filter import create_language_filter
import uuid
import shutil
import time
from typing import List, Dict, Any
import numpy as np
from pathlib import Path

# Initialize YOLO model (will download on first use)
model = None

def get_yolo_model():
    """Get YOLO model, initializing if needed"""
    global model
    if model is None:
        import torch
        # Force single-threaded execution to prevent semaphore leaks in multiprocessing
        torch.set_num_threads(1)
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
def process_video(self, video_url: str, video_type: str):
    """
    Celery task to process a video (TikTok, Instagram Reel) and extract books.
    """
    print(f"🚀 Starting {video_type.title()} video processing for: {video_url}")
    try:
        # Log available OCR backends to confirm if PaddleOCR is loaded
        print("ℹ️  Initializing OCR engine to check for available backends...")
        ocr_engine = get_ocr_engine()
        if ocr_engine and ocr_engine.available_backends:
            backend_names = [b.name for b in ocr_engine.available_backends]
            print(f"ℹ️  Available OCR backends: {backend_names}")
            if "PaddleOCR" in backend_names:
                print("✅ PaddleOCR is successfully implemented and available.")
            else:
                print("⚠️  PaddleOCR is not available. Check dependencies (paddlepaddle, paddleocr).")
        else:
            print("❌ No OCR backends available. Text extraction will fail.")

        self.update_state(state='PROGRESS', meta={'step': 'Downloading video', 'progress': 10})
        
        temp_dir_prefix = f"{video_type}_{uuid.uuid4().hex}_"
        temp_dir = tempfile.mkdtemp(prefix=temp_dir_prefix)
        print(f"📁 Created temp directory: {temp_dir}")
        video_path = None
        
        try:
            video_path = download_video(video_url, temp_dir)
            print(f"✅ Video downloaded successfully: {video_path}")
            
            debug_dir_name = f"{video_type}_{uuid.uuid4().hex[:8]}"
            debug_dir = Path(os.getcwd()) / "debug_output" / debug_dir_name
            debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"🗂️  Debug output will be saved to: {debug_dir}")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting frames', 'progress': 30})
            print("🖼️  Starting frame extraction...")
            
            frames = extract_frames(video_path)
            print(f"✅ Extracted {len(frames)} frames")
            
            self.update_state(state='PROGRESS', meta={'step': 'Detecting objects', 'progress': 50})
            
            book_detections = detect_books_in_frames(frames, debug_dir=str(debug_dir))
            print(f"✅ Object detection completed: {len(book_detections)} frame detections")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting text', 'progress': 70})
            print("📝 Starting text extraction...")
            
            prioritized_detections = prioritize_forward_facing_detections(book_detections, max_total=20)
            
            book_texts = extract_text_from_detections(frames, prioritized_detections, debug_dir=str(debug_dir))
            print(f"✅ Text extraction completed: {len(book_texts)} texts found")
            print(f"📋 Extracted texts: {book_texts[:5]}")
            
            self.update_state(state='PROGRESS', meta={'step': 'Finding book details', 'progress': 85})
            print("📚 Starting book search...")
            
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
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

def download_video(url: str, output_dir: str) -> str:
    """Download video using yt-dlp (supports TikTok, Instagram, etc.)"""
    print(f"⬇️  Starting download of: {url}")
    print(f"📂 Output directory: {output_dir}")
    
    ydl_opts = {
        'outtmpl': os.path.join(output_dir, 'video.%(ext)s'),
        'quiet': False,
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
    
    print("🔍 Looking for downloaded video file...")
    files = os.listdir(output_dir)
    print(f"📋 Files in directory: {files}")
    
    for file in files:
        if file.startswith('video.') and file.endswith(('.mp4', '.webm', '.mkv', '.mov')): # Added .mov
            video_path = os.path.join(output_dir, file)
            print(f"✅ Found video: {video_path}")
            return video_path
    
    print("❌ No video file found after download")
    raise Exception("Video download failed - no output file found")

def extract_frames(video_path: str, num_frames: int = 30) -> List[np.ndarray]:
    """Extracts a specified number of frames equally spread throughout the video."""
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Error: Could not open video {video_path}")
        return []

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    if total_frames < num_frames:
        print(f"⚠️ Video has only {total_frames} frames, requesting {num_frames}. Extracting all available frames.")
        num_frames = total_frames
        
    if num_frames == 0: # Avoid division by zero if total_frames is 0
        cap.release()
        return []

    # Calculate frame indices to extract evenly
    # Exclude the very first and last frame to avoid potential black frames or transitions
    # Use total_frames - 1 to get the last valid frame index
    frame_indices = np.linspace(0, total_frames - 1, num_frames, dtype=int)
    
    selected_frames = []
    
    for i, frame_idx in enumerate(frame_indices):
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if ret:
            selected_frames.append(frame)
        else:
            print(f"⚠️ Could not read frame {frame_idx}")
            
    cap.release()
    print(f"📊 Extracted {len(selected_frames)} frames out of {total_frames} total frames.")
    return selected_frames

def is_likely_forward_facing_book(width: float, height: float, aspect_ratio: float, 
                                 area: float, relative_x: float, relative_y: float, 
                                 class_name: str, confidence: float) -> bool:
    """Determine if a detection is likely a forward-facing book (cover) vs spine"""
    
    # Basic size filter - must be substantial enough
    if area < 2000:  # Increased minimum area for book covers
        return False
    
    # Forward-facing books typically have these characteristics:
    # 1. Aspect ratio closer to book cover proportions (0.6-0.85 typical)
    # 2. Larger area (covers are more prominent than spines)
    # 3. More likely to be in center of frame (people show covers intentionally)
    # 4. Higher confidence if detected as 'book'
    
    # Aspect ratio filtering - prioritize book cover proportions
    if class_name == 'book':
        # Books should have reasonable cover-like aspect ratios
        # Typical paperback: 0.65, hardcover: 0.75, avoid very thin spines
        if not (0.4 < aspect_ratio < 1.2):  # Allow some variation but exclude very thin/wide
            return False
        # Prefer more cover-like ratios
        if 0.6 <= aspect_ratio <= 0.85:  # Sweet spot for book covers
            aspect_score = 1.0
        elif 0.5 <= aspect_ratio <= 1.0:  # Still good
            aspect_score = 0.8
        else:
            aspect_score = 0.4  # Less likely but possible
    else:
        # For other classes, be more restrictive
        if not (0.3 < aspect_ratio < 2.0):
            return False
        aspect_score = 0.6
    
    # Size scoring - larger objects more likely to be covers
    if area > 10000:  # Large objects
        size_score = 1.0
    elif area > 5000:  # Medium objects
        size_score = 0.8
    else:  # Smaller objects (might be spines)
        size_score = 0.5
    
    # Position scoring - center objects more likely to be intentionally shown covers
    center_distance = ((relative_x - 0.5) ** 2 + (relative_y - 0.5) ** 2) ** 0.5
    if center_distance < 0.2:  # Very central
        position_score = 1.0
    elif center_distance < 0.5:  # Reasonably central
        position_score = 0.8
    else:  # Peripheral
        position_score = 0.6
    
    # Confidence scoring
    if class_name == 'book':
        if confidence > 0.7:
            confidence_score = 1.0
        elif confidence > 0.5:
            confidence_score = 0.8
        else:
            confidence_score = 0.6
    else:
        # Other classes need higher confidence
        if confidence > 0.8:
            confidence_score = 0.7
        else:
            confidence_score = 0.5
    
    # Combined score
    total_score = (aspect_score * 0.3 + size_score * 0.25 + 
                  position_score * 0.25 + confidence_score * 0.2)
    
    # Threshold for acceptance
    return total_score > 0.65

def calculate_forward_facing_score(width: float, height: float, aspect_ratio: float,
                                 area: float, relative_x: float, relative_y: float,
                                 class_name: str, confidence: float) -> float:
    """Calculate a score indicating how likely this is a forward-facing book"""
    
    # Reuse logic from is_likely_forward_facing_book but return the score
    if class_name == 'book':
        if 0.6 <= aspect_ratio <= 0.85:
            aspect_score = 1.0
        elif 0.5 <= aspect_ratio <= 1.0:
            aspect_score = 0.8
        elif 0.4 <= aspect_ratio <= 1.2:
            aspect_score = 0.6
        else:
            aspect_score = 0.2
    else:
        if 0.5 <= aspect_ratio <= 1.0:
            aspect_score = 0.6
        else:
            aspect_score = 0.3
    
    size_score = min(1.0, area / 10000)  # Normalize by large area
    
    center_distance = ((relative_x - 0.5) ** 2 + (relative_y - 0.5) ** 2) ** 0.5
    position_score = max(0.3, 1.0 - center_distance)
    
    confidence_score = confidence if class_name == 'book' else confidence * 0.7
    
    return (aspect_score * 0.3 + size_score * 0.25 + 
           position_score * 0.25 + confidence_score * 0.2)

def detect_books_in_frames(frames: List[np.ndarray], debug_dir: str = None) -> List[List[Dict]]:
    """Detect objects (potentially books) in frames using YOLO"""
    print(f"🤖 Loading YOLO model...")
    model = get_yolo_model()
    print(f"✅ YOLO model loaded successfully")
    
    # Create debug directory if specified
    if debug_dir:
        debug_frames_dir = Path(debug_dir) / "debug_frames"
        debug_frames_dir.mkdir(parents=True, exist_ok=True)
        print(f"🖼️  Debug frames will be saved to: {debug_frames_dir}")
    
    all_detections = []
    
    for frame_idx, frame in enumerate(frames):
        print(f"🔍 Processing frame {frame_idx+1}/{len(frames)}")
        # Run YOLO detection
        results = model(frame, verbose=False)
        
        frame_detections = []
        debug_frame = frame.copy() if debug_dir else None
        
        for result in results:
            boxes = result.boxes
            if boxes is not None:
                for box_idx, box in enumerate(boxes):
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
                        
                        # Calculate position in frame (for prioritizing central objects)
                        frame_height, frame_width = frame.shape[:2]
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2
                        relative_x = center_x / frame_width
                        relative_y = center_y / frame_height
                        
                        # Enhanced filtering for forward-facing books vs spines
                        is_forward_facing = is_likely_forward_facing_book(
                            width, height, aspect_ratio, area, relative_x, relative_y, class_name, confidence
                        )
                        
                        if is_forward_facing:
                            detection = {
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'confidence': confidence,
                                'class': class_name,
                                'aspect_ratio': aspect_ratio,
                                'area': area,
                                'forward_facing_score': calculate_forward_facing_score(
                                    width, height, aspect_ratio, area, relative_x, relative_y, class_name, confidence
                                ),
                                'position': {'x': relative_x, 'y': relative_y}
                            }
                            frame_detections.append(detection)
                            
                            # Draw bounding box on debug frame
                            if debug_frame is not None:
                                # Color coding: Green for high-scoring books, yellow for medium, orange for low/other
                                ff_score = detection['forward_facing_score']
                                if class_name == 'book' and ff_score > 0.8:
                                    color = (0, 255, 0)  # Bright green for high-scoring books
                                elif class_name == 'book' and ff_score > 0.65:
                                    color = (0, 255, 255)  # Yellow for medium-scoring books
                                else:
                                    color = (255, 165, 0)  # Orange for low-scoring or other objects
                                
                                cv2.rectangle(debug_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                                
                                # Enhanced label with forward-facing score
                                label = f"{class_name} {confidence:.2f} (ff:{ff_score:.2f})"
                                label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0]
                                cv2.rectangle(debug_frame, (int(x1), int(y1) - label_size[1] - 10), 
                                            (int(x1) + label_size[0], int(y1)), color, -1)
                                cv2.putText(debug_frame, label, (int(x1), int(y1) - 5), 
                                          cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
        
        # Save debug frame if debug directory is specified
        if debug_dir and debug_frame is not None:
            debug_filename = debug_frames_dir / f"frame_{frame_idx:03d}_detections_{len(frame_detections)}.jpg"
            cv2.imwrite(str(debug_filename), debug_frame)
            print(f"💾 Saved debug frame: {debug_filename}")
        
        # Sort detections by forward-facing score (best first)
        frame_detections.sort(key=lambda d: d['forward_facing_score'], reverse=True)
        
        # Limit to top N detections per frame to focus on best candidates
        max_detections_per_frame = 5  # Reduce noise from too many detections
        frame_detections = frame_detections[:max_detections_per_frame]
        
        if frame_detections:
            print(f"📊 Top detections for frame {frame_idx+1}:")
            for i, det in enumerate(frame_detections[:3]):  # Show top 3
                print(f"   {i+1}. {det['class']} (conf: {det['confidence']:.2f}, "
                      f"aspect: {det['aspect_ratio']:.2f}, score: {det['forward_facing_score']:.2f})")
        
        all_detections.append(frame_detections)
    
    return all_detections

def enhance_image_for_ocr(image: np.ndarray) -> np.ndarray:
    """Apply optimized image enhancement for better OCR results"""
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image.copy()
    
    # Apply multiple enhancement techniques
    enhanced = gray.copy()
    
    # 1. Noise reduction with bilateral filter
    enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)
    
    # 2. Contrast enhancement using CLAHE (better than simple scaling)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
    enhanced = clahe.apply(enhanced)
    
    # 3. Sharpening kernel to enhance text edges
    kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    enhanced = cv2.filter2D(enhanced, -1, kernel)
    
    # 4. Morphological operations to clean up text
    # Remove small noise
    kernel_denoise = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2,2))
    enhanced = cv2.morphologyEx(enhanced, cv2.MORPH_OPEN, kernel_denoise)
    
    # 5. Ensure good contrast for OCR (convert back to BGR for compatibility)
    enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
    
    return enhanced_bgr

def prioritize_forward_facing_detections(detections: List[List[Dict]], max_total: int = 15) -> List[List[Dict]]:
    """Prioritize the best forward-facing book detections across all frames"""
    # Flatten all detections with frame info
    all_detections = []
    for frame_idx, frame_detections in enumerate(detections):
        for det in frame_detections:
            det_copy = det.copy()
            det_copy['frame_idx'] = frame_idx
            all_detections.append(det_copy)
    
    # Sort by forward-facing score
    all_detections.sort(key=lambda d: d['forward_facing_score'], reverse=True)
    
    # Take only the best detections up to max_total
    best_detections = all_detections[:max_total]
    
    print(f"🎯 Selected {len(best_detections)} best forward-facing candidates from {len(all_detections)} total detections")
    if best_detections:
        print(f"📊 Score range: {best_detections[-1]['forward_facing_score']:.2f} to {best_detections[0]['forward_facing_score']:.2f}")
    
    # Rebuild the frame-based structure
    prioritized_detections = [[] for _ in detections]
    for det in best_detections:
        frame_idx = det.pop('frame_idx')  # Remove the temporary frame index
        prioritized_detections[frame_idx].append(det)
    
    return prioritized_detections

def extract_text_from_detections(frames: List[np.ndarray], detections: List[List[Dict]], debug_dir: str = None) -> List[str]:
    """Extract and clean text from detection bounding boxes using OCR"""
    all_texts = []
    
    if debug_dir:
        debug_dir = Path(debug_dir)
        debug_crops_dir = debug_dir / "ocr_crops"
        debug_crops_dir.mkdir(exist_ok=True)
    
    for frame_idx, frame_detections in enumerate(detections):
        if not frame_detections:
            continue
            
        frame = frames[frame_idx]
        
        for det_idx, detection in enumerate(frame_detections):
            x, y, w, h = detection['bbox']
            
            # Crop the detection region
            crop = frame[y:y+h, x:x+w]
            if crop.size == 0:
                continue
                
            try:
                # Enhance image for better OCR
                enhanced = enhance_image_for_ocr(crop)
                
                # OCR approach using pytesseract
                raw_text = pytesseract.image_to_string(enhanced, config='--psm 6')
                debug_info = {'best_backend': 'pytesseract', 'best_score': 1.0, 'all_results': {'pytesseract': raw_text}}
                
                if raw_text.strip():
                    cleaned_text = clean_ocr_text(raw_text)
                    if cleaned_text:
                        print(f"   📖 Frame {frame_idx+1}, Det {det_idx+1}: Multi-OCR -> '{cleaned_text}'")
                        print(f"   Best: {debug_info.get('best_backend', 'None')} (score: {debug_info.get('best_score', 0):.2f})")
                        
                        # Save comprehensive OCR debug info
                        if debug_dir:
                            ocr_filename = debug_crops_dir / f"frame_{frame_idx:03d}_det_{det_idx:02d}_ocr.txt"
                            with open(ocr_filename, 'w', encoding='utf-8') as f:
                                f.write(f"Raw Multi-OCR: {raw_text.strip()}\n")
                                f.write(f"Cleaned: {cleaned_text}\n")
                                f.write(f"Best Backend: {debug_info.get('best_backend', 'None')}\n")
                                f.write(f"Best Score: {debug_info.get('best_score', 0):.2f}\n")
                                f.write(f"\nAll Results:\n")
                                for backend, result in debug_info.get('all_results', {}).items():
                                    f.write(f"  {backend}: {result}\n")
                                f.write(f"\nDetection Info:\n")
                                f.write(f"Class: {detection['class']}\n")
                                f.write(f"Confidence: {detection['confidence']:.2f}\n")
                                f.write(f"Forward-facing score: {detection['forward_facing_score']:.2f}\n")
                                f.write(f"Aspect ratio: {detection['aspect_ratio']:.2f}\n")
                                f.write(f"Area: {detection['area']:.0f}\n")
                                f.write(f"Position: x={detection['position']['x']:.2f}, y={detection['position']['y']:.2f}\n")
                                f.write(f"BBox: {detection['bbox']}\n")
                
                        if cleaned_text and len(cleaned_text) > 3 and is_likely_book_title(cleaned_text):
                            all_texts.append(cleaned_text)
                            print(f"✅ Accepted as book title: '{cleaned_text}'")
                        elif cleaned_text:
                            print(f"❌ Rejected as non-book: '{cleaned_text}'")
                
            except Exception as e:
                print(f"❌ OCR error on frame {frame_idx+1} detection {det_idx+1}: {e}")
                continue
    
    # Remove duplicates while preserving order
    unique_texts = []
    seen = set()
    for text in all_texts:
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

def _is_all_caps(s: str) -> bool:
    """Checks if a string is all uppercase and has more than one letter."""
    return len(s) > 1 and s.isupper()

def preprocess_and_extract_candidates(text: str) -> List[str]:
    """
    Preprocesses a raw OCR text string to extract multiple candidate queries
    for book titles and authors. Aims to split up cluttered OCR results.
    """
    import re

    # First, apply basic cleaning.
    text = clean_ocr_text(text)

    # Remove common marketing phrases and noise from book covers.
    noise_patterns = [
        r'new york times best ?selling( author)?',
        r'usa today best ?selling( author)?',
        r'(international|sunday times) best ?seller',
        r'best ?selling author',
        r'the number one',
        r'a novel',
        r'book (\w+ )?of the',
    ]
    processed_text = text
    for pattern in noise_patterns:
        processed_text = re.sub(pattern, ' ', processed_text, flags=re.IGNORECASE)

    # Normalize whitespace after removals
    processed_text = re.sub(r'\s+', ' ', processed_text).strip()

    candidates = []
    
    # The whole cleaned text is a candidate itself
    if processed_text:
        candidates.append(processed_text)
        
    words = processed_text.split()
    
    # Heuristic: Find a split between a run of all-caps words (author)
    # and what follows (title).
    author_end_idx = -1
    if len(words) > 1:
        for i in range(len(words) - 1):
            # Find the end of the first run of 2+ all-caps words
            if _is_all_caps(words[i]) and _is_all_caps(words[i+1]):
                author_end_idx = i + 1
            elif author_end_idx != -1:
                # The run of all-caps words has ended
                break
    
    if author_end_idx != -1:
        # We found a potential split
        author_candidate = ' '.join(words[:author_end_idx + 1])
        title_candidate = ' '.join(words[author_end_idx + 1:])
        
        if author_candidate:
            candidates.append(author_candidate)
        if title_candidate:
            candidates.append(title_candidate)

    # Deduplicate and clean final candidates
    unique_candidates = []
    seen = set()
    for cand in candidates:
        # Further clean each candidate
        cand = clean_ocr_text(cand)
        if len(cand) > 3 and cand.lower() not in seen:
            unique_candidates.append(cand)
            seen.add(cand.lower())
            
    return unique_candidates

def search_books_from_text(texts: List[str]) -> List[Dict]:
    """Search for books using extracted text with fuzzy matching for near-misses"""
    print(f"📚 Starting fuzzy book search with {len(texts)} text extractions")
    
    # Create fuzzy searcher
    fuzzy_searcher = create_fuzzy_searcher()
    found_books = []
    seen_titles = set()
    processed_queries = set()
    
    # Preprocess texts to extract candidate queries (authors, titles)
    candidate_queries = []
    for text in texts:
        # Extract multiple candidates (e.g., author, title) from a single OCR block
        candidates = preprocess_and_extract_candidates(text)
        for cand in candidates:
            if is_likely_book_title(cand) and cand.lower() not in processed_queries:
                if len(cand) >= 3 and len(cand.split()) >= 1:
                    candidate_queries.append(cand)
                    processed_queries.add(cand.lower())

    # Limit the number of searches to avoid excessive API calls
    max_searches = min(len(candidate_queries), 15)
    search_queries = candidate_queries[:max_searches]
    
    print(f"📝 Will fuzzy search for {len(search_queries)} candidates: {search_queries}")
    
    # Add delay between searches to avoid rate limiting (fuzzy does multiple calls)
    search_delay = 1.0  # Longer delay since fuzzy search is more intensive
    
    for i, clean_text in enumerate(search_queries):
        if len(found_books) >= 15:  # Increased limit to collect more unique books
            print(f"📚 Reached book limit (15), stopping search")
            break
            
        try:
            print(f"\n🔮 Fuzzy search {i+1}/{len(search_queries)}: '{clean_text}'")
            
            # Add delay between searches (except first one)
            if i > 0:
                time.sleep(search_delay)
            
            # Use fuzzy search with fallback
            search_results = fuzzy_searcher.search_with_fuzzy_fallback(clean_text, max_results=3)
            
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
                    if books_added_this_search >= 2:
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
            if 'popularity_score' not in book:
                book['popularity_score'] = 0.0
        # Sort descending by popularity_score
        found_books.sort(key=lambda b: b.get('popularity_score', 0.0), reverse=True)
        print(f"🏆 Final sorted books by popularity: {len(found_books)} entries")
        return found_books
    
    return found_books
