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

# Simple OpenCV import with minimal threading fixes
try:
    import cv2
    # Only set single-threaded mode to prevent semaphore leaks in multiprocessing
    if hasattr(cv2, 'setNumThreads'):
        cv2.setNumThreads(1)
    
    # Add minimal GUI patches only if functions are missing (for headless installs)
    if not hasattr(cv2, 'imshow'):
        def dummy_imshow(*args, **kwargs):
            pass
        cv2.imshow = dummy_imshow
        print("⚠️ Added dummy imshow (headless OpenCV detected)")
    
    if not hasattr(cv2, 'waitKey'):
        def dummy_waitKey(*args, **kwargs):
            return -1
        cv2.waitKey = dummy_waitKey
        print("⚠️ Added dummy waitKey (headless OpenCV detected)")
    
    if not hasattr(cv2, 'destroyAllWindows'):
        def dummy_destroyAllWindows(*args, **kwargs):
            pass
        cv2.destroyAllWindows = dummy_destroyAllWindows
        print("⚠️ Added dummy destroyAllWindows (headless OpenCV detected)")
    
    # Add essential constants if missing
    constants_to_check = {
        'IMREAD_COLOR': 1,
        'IMREAD_GRAYSCALE': 0,
        'IMREAD_UNCHANGED': -1,
        'CAP_PROP_FRAME_COUNT': 7,
        'CAP_PROP_FPS': 5,
        'CAP_PROP_POS_FRAMES': 1,
        'COLOR_BGR2GRAY': 6,
        'COLOR_BGR2RGB': 4,
        'COLOR_GRAY2RGB': 8,
        'COLOR_BGR2HSV': 40,
        'COLOR_GRAY2BGR': 8,
        'CV_64F': 6,
        'FONT_HERSHEY_SIMPLEX': 0,
        'BORDER_CONSTANT': 0,
        'BORDER_REPLICATE': 1,
    }
    
    missing_constants = []
    for const_name, const_value in constants_to_check.items():
        if not hasattr(cv2, const_name):
            setattr(cv2, const_name, const_value)
            missing_constants.append(const_name)
    
    if missing_constants:
        print(f"⚠️ Added missing OpenCV constants: {', '.join(missing_constants)}")
    
    print("✅ OpenCV imported successfully")
    print(f"📊 OpenCV functions available: imshow={hasattr(cv2, 'imshow')}, waitKey={hasattr(cv2, 'waitKey')}, VideoCapture={hasattr(cv2, 'VideoCapture')}")
except ImportError as e:
    print(f"❌ Failed to import OpenCV: {e}")
    print("Please install opencv-python: pip install opencv-python")
    raise

# Now safe to import ultralytics since cv2.setNumThreads exists
print("🚀 Importing ultralytics...")
try:
    from ultralytics import YOLO
    print("✅ Ultralytics imported successfully")
    # Check if ultralytics modified cv2
    print(f"📊 After ultralytics - OpenCV functions available: imshow={hasattr(cv2, 'imshow')}, waitKey={hasattr(cv2, 'waitKey')}, VideoCapture={hasattr(cv2, 'VideoCapture')}")
except Exception as e:
    print(f"⚠️ Ultralytics import issue: {e}")
    # Re-patch if needed
    if not hasattr(cv2, 'imshow'):
        def dummy_imshow(*args, **kwargs):
            pass
        cv2.imshow = dummy_imshow
        print("🔧 Re-added dummy imshow after ultralytics import")
    
    # Re-check constants after ultralytics import
    constants_to_check = {
        'IMREAD_COLOR': 1,
        'IMREAD_GRAYSCALE': 0,
        'IMREAD_UNCHANGED': -1,
        'CAP_PROP_FRAME_COUNT': 7,
        'CAP_PROP_FPS': 5,
        'CAP_PROP_POS_FRAMES': 1,
        'COLOR_BGR2GRAY': 6,
        'COLOR_BGR2RGB': 4,
        'COLOR_GRAY2RGB': 8,
        'COLOR_BGR2HSV': 40,
        'COLOR_GRAY2BGR': 8,
        'CV_64F': 6,
        'FONT_HERSHEY_SIMPLEX': 0,
        'BORDER_CONSTANT': 0,
        'BORDER_REPLICATE': 1,
    }
    
    missing_constants = []
    for const_name, const_value in constants_to_check.items():
        if not hasattr(cv2, const_name):
            setattr(cv2, const_name, const_value)
            missing_constants.append(const_name)
    
    if missing_constants:
        print(f"🔧 Re-added missing OpenCV constants after ultralytics: {', '.join(missing_constants)}")
    
    raise
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
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        # Log available OCR backends
        print("ℹ️  Initializing OCR engine to check for available backends...")
        ocr_engine = get_ocr_engine()
        if ocr_engine and ocr_engine.available_backends:
            backend_names = [b.name for b in ocr_engine.available_backends]
            print(f"ℹ️  Available OCR backends: {backend_names}")
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
            
            # Only create debug dir in development
            debug_dir = None
            if os.getenv('FLASK_ENV') == 'development' or os.getenv('DEBUG', '').lower() == 'true':
                debug_dir_name = f"{video_type}_{uuid.uuid4().hex[:8]}"
                debug_dir = Path(os.getcwd()) / "debug_output" / debug_dir_name
                debug_dir.mkdir(parents=True, exist_ok=True)
                print(f"🗂️  Debug output will be saved to: {debug_dir}")
            else:
                print("🚀 Production mode: Skipping debug output for faster processing")
            
            # Set performance mode based on environment
            performance_mode = os.getenv('PERFORMANCE_MODE', 'fast').lower()
            print(f"⚡ Performance mode: {performance_mode}")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting frames', 'progress': 30})
            print("🖼️  Starting frame extraction...")
            
            # Use simple frame extraction for better reliability
            try:
                from simple_frame_extractor import SimpleFrameExtractor
                extractor = SimpleFrameExtractor()
                frames = extractor.extract_optimal_frames(video_path, output_dir=str(debug_dir) if debug_dir else None)
                print(f"✅ Extracted {len(frames)} optimized frames")
                
                # If we got too few frames, fall back to uniform extraction
                if len(frames) < 3:
                    print("⚠️ Too few frames from smart extraction, falling back to uniform extraction")
                    frames = extract_frames(video_path, num_frames=12)
                    print(f"✅ Fallback: Extracted {len(frames)} uniform frames")
                    
            except Exception as e:
                print(f"⚠️ Simple frame extraction failed: {e}")
                print("🔄 Falling back to uniform frame extraction")
                try:
                    frames = extract_frames(video_path, num_frames=12)
                    print(f"✅ Fallback: Extracted {len(frames)} uniform frames")
                except Exception as e2:
                    print(f"❌ All frame extraction methods failed: {e2}")
                    # Return a graceful error instead of crashing
                    return {
                        'status': 'error',
                        'error': f'Video processing failed: Could not extract frames from video. Original error: {e}. Fallback error: {e2}',
                        'details': 'Video file may be corrupted or in an unsupported format.'
                    }
            
            # Check if we successfully extracted any frames
            if not frames or len(frames) == 0:
                print("❌ No frames were extracted from the video")
                return {
                    'status': 'error',
                    'error': 'No frames could be extracted from the video',
                    'details': 'Video may be too short, corrupted, or in an unsupported format.'
                }
            
            self.update_state(state='PROGRESS', meta={'step': 'Detecting objects', 'progress': 50})
            
            book_detections = detect_books_in_frames(frames, debug_dir=str(debug_dir))
            print(f"✅ Object detection completed: {len(book_detections)} frame detections")
            
            self.update_state(state='PROGRESS', meta={'step': 'Extracting text', 'progress': 70})
            print("📝 Starting text extraction...")
            
            prioritized_detections = prioritize_forward_facing_detections(book_detections, max_total=12)
            
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
        'format': 'worst[height<=480]/best[height<=480]/worst',  # Lower quality for faster download
        'prefer_ffmpeg': True,
        'writesubtitles': False,
        'writeautomaticsub': False,
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
    # Check if video file exists first
    if not os.path.exists(video_path):
        print(f"❌ Error: Video file does not exist: {video_path}")
        return []
    
    # Check if video file is not empty
    if os.path.getsize(video_path) == 0:
        print(f"❌ Error: Video file is empty: {video_path}")
        return []
    
    print(f"📹 Opening video file: {video_path} (size: {os.path.getsize(video_path)} bytes)")
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
    # Skip first 10% and last 10% to avoid black frames or transitions
    start_frame = max(1, int(total_frames * 0.1))
    end_frame = max(start_frame + 1, int(total_frames * 0.9))
    
    # Ensure we have enough frames to extract from
    if end_frame - start_frame < num_frames:
        start_frame = 1
        end_frame = total_frames - 1
    
    frame_indices = np.linspace(start_frame, end_frame, num_frames, dtype=int)
    
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
    """Detect objects (potentially books) in frames using YOLO with batch processing"""
    print(f"🤖 Loading YOLO model...")
    model = get_yolo_model()
    print(f"✅ YOLO model loaded successfully")
    
    # Create debug directory if specified
    if debug_dir:
        debug_frames_dir = Path(debug_dir) / "debug_frames"
        debug_frames_dir.mkdir(parents=True, exist_ok=True)
        print(f"🖼️  Debug frames will be saved to: {debug_frames_dir}")
    
    print(f"🚀 Processing {len(frames)} frames with batch inference...")
    
    # Batch process all frames at once for better efficiency
    try:
        results_batch = model(frames, verbose=False)
    except Exception as e:
        print(f"⚠️  Batch processing failed, falling back to individual processing: {e}")
        # Fallback to individual processing
        results_batch = []
        for frame in frames:
            results_batch.append(model(frame, verbose=False))
    
    all_detections = []
    
    for frame_idx, (frame, results) in enumerate(zip(frames, results_batch)):
        print(f"🔍 Processing detections for frame {frame_idx+1}/{len(frames)}")
        
        frame_detections = []
        debug_frame = frame.copy() if debug_dir else None
        
        for result in [results] if isinstance(results, list) else [results]:
            boxes = result.boxes
            if boxes is not None:
                for box_idx, box in enumerate(boxes):
                    # Get confidence and class
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = model.names[class_id]
                    
                    # We're looking for book-like objects
                    # YO classes that might contain books or be books themselves
                    book_related_classes = ['book', 'person', 'laptop', 'cell phone', 'tv', 'dining table', 'bed']
                    
                    # Be more selective about confidence thresholds
                    min_confidence = 0.3 if class_name == 'book' else 0.6
                    
                    if class_name in book_related_classes and confidence > min_confidence:
                        
                        # Get bounding box coordinates
                        x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                        
                        # Calculate dimensions and properties
                        width = x2 - x1
                        height = y2 - y1
                        area = width * height
                        aspect_ratio = width / height if height > 0 else 1.0
                        
                        # Calculate relative position (center of detection)
                        frame_height, frame_width = frame.shape[:2]
                        center_x = (x1 + x2) / 2
                        center_y = (y1 + y2) / 2
                        relative_x = center_x / frame_width
                        relative_y = center_y / frame_height
                        
                        # Calculate forward-facing score
                        forward_facing_score = calculate_forward_facing_score(
                            width, height, aspect_ratio, area, relative_x, relative_y, class_name, confidence
                        )
                        
                        # Store detection info
                        detection = {
                            'bbox': [int(x1), int(y1), int(width), int(height)],
                            'confidence': confidence,
                            'class': class_name,
                            'class_id': class_id,
                            'area': area,
                            'aspect_ratio': aspect_ratio,
                            'position': {'x': relative_x, 'y': relative_y},
                            'forward_facing_score': forward_facing_score
                        }
                        
                        frame_detections.append(detection)
                        
                        # Draw debug visualization if enabled
                        if debug_frame is not None:
                            color = (0, 255, 0) if class_name == 'book' else (255, 0, 0)
                            cv2.rectangle(debug_frame, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                            label = f"{class_name}: {confidence:.2f}, FF: {forward_facing_score:.2f}"
                            cv2.putText(debug_frame, label, (int(x1), int(y1-10)), 
                                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        
        # Save debug frame if requested
        if debug_dir and debug_frame is not None:
            debug_frame_path = Path(debug_dir) / "debug_frames" / f"frame_{frame_idx:03d}_detections.jpg"
            cv2.imwrite(str(debug_frame_path), debug_frame)
        
        all_detections.append(frame_detections)
        print(f"   📋 Frame {frame_idx+1}: {len(frame_detections)} detections")
    
    total_detections = sum(len(dets) for dets in all_detections)
    print(f"✅ Detection completed: {total_detections} total detections across {len(frames)} frames")
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
                
                # Multi-backend OCR for better results
                ocr_engine = get_ocr_engine()
                debug_info = {}
                raw_text = ocr_engine.extract_text_multi_backend(enhanced, debug_info)
                
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
        r'^$\d+',  # Prices
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
        r'b.*'
    ]

    # Remove noise patterns
    for pattern in noise_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Split into lines and strip
    candidates = [line.strip() for line in text.splitlines() if line.strip()]
    return candidates

def search_books_from_text(book_texts: List[str]) -> List[Dict]:
    """
    Search for books using the extracted text from OCR.
    Takes a list of text strings and returns book information.
    """
    if not book_texts:
        print("⚠️ No book texts provided for search")
        return []
    
    print(f"📚 Searching for {len(book_texts)} book texts...")
    
    # Initialize the books client
    books_client = GoogleBooksClient()
    
    found_books = []
    processed_titles = set()  # Track processed titles to avoid duplicates
    
    for i, text in enumerate(book_texts[:10]):  # Limit to first 10 to avoid rate limiting
        if not text or len(text.strip()) < 3:
            continue
            
        # Clean and normalize the text for search
        search_query = text.strip()
        search_query_lower = search_query.lower()
        
        # Skip if we've already processed this title (case-insensitive)
        if search_query_lower in processed_titles:
            print(f"⏭️ Skipping duplicate text: '{search_query}'")
            continue
            
        processed_titles.add(search_query_lower)
        
        print(f"🔍 Search {i+1}: '{search_query}'")
        
        try:
            # Search for books using the text
            search_results = books_client.search_books(search_query, max_results=3)
            
            if search_results:
                print(f"✅ Found {len(search_results)} results for '{search_query}'")
                
                # Add the best result(s) to our findings
                for book in search_results[:2]:  # Take top 2 results per search
                    # Add metadata about the search
                    book['search_query'] = search_query
                    book['ocr_confidence'] = 'medium'  # Could be enhanced with actual confidence
                    
                    # Build purchase links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    book['amazon_link'] = build_amazon_link(book)
                    
                    found_books.append(book)
                    
            else:
                print(f"❌ No results found for '{search_query}'")
                
        except Exception as e:
            print(f"❌ Error searching for '{search_query}': {e}")
            continue
    
    # Remove duplicates based on book ID or title
    unique_books = []
    seen_ids = set()
    seen_titles = set()
    
    for book in found_books:
        book_id = book.get('id', '')
        title = book.get('title', '').lower().strip()
        
        # Skip if we've seen this book ID or very similar title
        if book_id and book_id in seen_ids:
            continue
        if title and title in seen_titles:
            continue
            
        if book_id:
            seen_ids.add(book_id)
        if title:
            seen_titles.add(title)
            
        unique_books.append(book)
    
    print(f"📚 Final results: {len(unique_books)} unique books found from {len(book_texts)} texts")
    
    return unique_books
