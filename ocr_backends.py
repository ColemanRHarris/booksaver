"""
Multi-backend OCR system with fallback support for better text extraction
"""
import os

# Force single-threaded execution for all underlying libraries
# to prevent semaphore leaks in multiprocessing environments like Celery.
os.environ['OMP_NUM_THREADS'] = '1'
os.environ['MKL_NUM_THREADS'] = '1'
os.environ['OPENBLAS_NUM_THREADS'] = '1'
os.environ['VECLIB_MAXIMUM_THREADS'] = '1'
os.environ['NUMEXPR_NUM_THREADS'] = '1'

# Handle OpenCV import conflicts and threading issues
try:
    import cv2
    # Fix common OpenCV threading issues  
    if hasattr(cv2, 'setNumThreads'):
        cv2.setNumThreads(0)  # Prevent threading issues with multiprocessing
except Exception as e:
    print(f"Warning: OpenCV import issue in OCR backends: {e}")
    import cv2  # Try again

import numpy as np
import pytesseract
from typing import List, Dict, Optional, Tuple
import warnings
from pathlib import Path

class OCRBackend:
    """Base class for OCR backends"""
    
    def __init__(self, name: str):
        self.name = name
        self.available = False
        self.initialize()
    
    def initialize(self):
        """Initialize the backend - to be overridden"""
        pass
    
    def extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text from image - to be overridden
        Returns: (text, confidence_score)
        """
        raise NotImplementedError

class TesseractOCR(OCRBackend):
    """Tesseract OCR backend with optimized settings"""
    
    def initialize(self):
        try:
            # Test if tesseract is available
            pytesseract.get_tesseract_version()
            self.available = True
            print(f"✅ {self.name} initialized successfully")
        except Exception as e:
            print(f"❌ {self.name} initialization failed: {e}")
            self.available = False
    
    def extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using Tesseract with multiple configurations"""
        if not self.available:
            return "", 0.0
        
        # Convert to RGB if needed
        if len(image.shape) == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        
        # Optimized Tesseract configurations for book titles
        configs = [
            # Best for book titles (mixed case, preserve spaces and common punctuation)
            '--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -:.,!\'"',
            # Single uniform block of text
            '--oem 3 --psm 6',
            # Sparse text (good for isolated titles)
            '--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 -:.,',
            # Single text line
            '--oem 3 --psm 7',
            # Raw line without specific assumptions
            '--oem 3 --psm 13',
        ]
        
        best_text = ""
        best_confidence = 0.0
        
        for config in configs:
            try:
                # Get text and confidence
                text = pytesseract.image_to_string(image_rgb, config=config).strip()
                
                # Get confidence data
                try:
                    data = pytesseract.image_to_data(image_rgb, config=config, output_type=pytesseract.Output.DICT)
                    confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
                    avg_confidence = sum(confidences) / len(confidences) if confidences else 0
                except:
                    avg_confidence = 50.0  # Default confidence
                
                # Score this result
                text_score = self._score_text_quality(text)
                combined_score = (avg_confidence / 100.0) * 0.3 + text_score * 0.7
                
                if combined_score > best_confidence:
                    best_text = text
                    best_confidence = combined_score
                    
            except Exception as e:
                continue
        
        return best_text, best_confidence
    
    def _score_text_quality(self, text: str) -> float:
        """Score text quality for book titles"""
        if not text:
            return 0.0
        
        # Basic quality indicators
        score = 0.0
        
        # Length (sweet spot for book titles)
        if 5 <= len(text) <= 50:
            score += 0.3
        elif 3 <= len(text) <= 70:
            score += 0.2
        
        # Has letters
        alpha_ratio = sum(1 for c in text if c.isalpha()) / len(text)
        score += alpha_ratio * 0.4
        
        # Multiple words (most book titles have 2+ words)
        word_count = len(text.split())
        if word_count >= 2:
            score += 0.2
        elif word_count >= 1:
            score += 0.1
        
        # Not all caps or all lowercase (mixed case is better)
        if not (text.isupper() or text.islower()) and any(c.isupper() for c in text):
            score += 0.1
        
        return min(1.0, score)

class EasyOCRBackend(OCRBackend):
    """EasyOCR backend - often better for scene text"""
    
    def initialize(self):
        try:
            # Check for EasyOCR dependencies first
            import easyocr
            
            # Force single-threaded execution to prevent semaphore leaks
            import torch
            torch.set_num_threads(1)
            
            # Initialize with error handling for common issues
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # Try to initialize EasyOCR reader
                self.reader = easyocr.Reader(['en'], gpu=False, verbose=False)
                
            self.available = True
            print(f"✅ {self.name} initialized successfully")
            
        except ImportError as e:
            if "bidi" in str(e).lower():
                print(f"⚠️ {self.name} skipped: bidi dependency issue. This is common and Tesseract will work fine.")
            else:
                print(f"⚠️ {self.name} skipped: missing dependency - {e}")
            self.available = False
        except Exception as e:
            print(f"❌ {self.name} initialization failed: {e}")
            print(f"   Note: EasyOCR has complex dependencies. Tesseract will be used instead.")
            self.available = False
    
    def extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using EasyOCR with optimized settings for book covers"""
        if not self.available:
            return "", 0.0
        
        try:
            # EasyOCR expects RGB
            if len(image.shape) == 3:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            
            # Run EasyOCR with optimized parameters for book titles
            results = self.reader.readtext(
                image_rgb, 
                detail=1, 
                paragraph=False,
                width_ths=0.7,    # Slightly more aggressive text line detection
                height_ths=0.7,   # Better for book title text
                text_threshold=0.7,  # Higher threshold for better quality
                low_text=0.4      # Lower threshold for text detection
            )
            
            if not results:
                return "", 0.0
            
            # Process results with more lenient confidence threshold
            texts = []
            confidences = []
            
            for (bbox, text, confidence) in results:
                text_clean = text.strip()
                # More lenient filtering - accept lower confidence for longer text
                min_confidence = 0.2 if len(text_clean) >= 8 else 0.4
                
                if confidence > min_confidence and len(text_clean) >= 2:
                    texts.append(text_clean)
                    confidences.append(confidence)
            
            if not texts:
                return "", 0.0
            
            # Smart text combination - prefer longer single results over multiple short ones
            if len(texts) == 1:
                combined_text = texts[0]
                avg_confidence = confidences[0]
            else:
                # If multiple results, find the longest one or combine if they seem related
                longest_text = max(texts, key=len)
                if len(longest_text) >= 8:  # Prefer single long result
                    idx = texts.index(longest_text)
                    combined_text = longest_text
                    avg_confidence = confidences[idx]
                else:
                    # Combine all results
                    combined_text = " ".join(texts)
                    avg_confidence = sum(confidences) / len(confidences)
            
            return combined_text, avg_confidence
            
        except Exception as e:
            print(f"EasyOCR error: {e}")
            return "", 0.0


class MultiOCREngine:
    """OCR engine with EasyOCR as primary backend and Tesseract as fallback"""
    
    def __init__(self):
        # Initialize core backends with EasyOCR as primary choice
        self.backends = [
            EasyOCRBackend("EasyOCR"),          # PRIMARY: Best for scene text and book covers
            TesseractOCR("Tesseract"),          # FALLBACK: Always available backup
        ]
        
        self.available_backends = [b for b in self.backends if b.available]
        
        if self.available_backends:
            # Show EasyOCR as primary if available
            easyocr_available = any(b.name == "EasyOCR" for b in self.available_backends)
            tesseract_available = any(b.name == "Tesseract" for b in self.available_backends)
            
            if easyocr_available and tesseract_available:
                print(f"🔤 OCR Engine: EasyOCR (PRIMARY) + Tesseract (fallback)")
            elif easyocr_available:
                print(f"🔤 OCR Engine: EasyOCR only (recommended setup)")
            elif tesseract_available:
                print(f"🔤 OCR Engine: Tesseract only (EasyOCR unavailable)")
            
            # Show which backends failed (if any)
            failed_backends = [b.name for b in self.backends if not b.available]
            if failed_backends:
                if "EasyOCR" in failed_backends:
                    print(f"⚠️  EasyOCR unavailable (falling back to Tesseract): {failed_backends}")
                else:
                    print(f"⚠️  Failed backends: {failed_backends}")
        else:
            print("❌ No OCR backends available!")
            print("   Try installing dependencies: pip install easyocr pytesseract")
    
    def extract_text_multi_backend(self, image: np.ndarray, debug_info: dict = None) -> str:
        """Extract text using EasyOCR first, Tesseract as fallback"""
        if not self.available_backends:
            return ""
        
        # Find EasyOCR backend
        easyocr_backend = None
        tesseract_backend = None
        
        for backend in self.available_backends:
            if backend.name == "EasyOCR":
                easyocr_backend = backend
            elif backend.name == "Tesseract":
                tesseract_backend = backend
        
        # Try EasyOCR first (primary method)
        if easyocr_backend:
            try:
                text, confidence = easyocr_backend.extract_text(image)
                if text and len(text.strip()) >= 3:  # Require at least 3 characters
                    print(f"🎯 EasyOCR result: '{text.strip()}' (confidence: {confidence:.3f})")
                    if debug_info:
                        debug_info['easyocr_result'] = f"{text.strip()} (conf: {confidence:.2f})"
                        debug_info['best_backend'] = 'EasyOCR'
                        debug_info['best_confidence'] = confidence
                    return text.strip()
                else:
                    print(f"⚠️ EasyOCR returned short/empty result: '{text.strip()}'")
                    if debug_info:
                        debug_info['easyocr_result'] = f"Short result: '{text.strip()}' (conf: {confidence:.2f})"
            except Exception as e:
                print(f"❌ EasyOCR failed: {e}")
                if debug_info:
                    debug_info['easyocr_error'] = str(e)
        
        # Fallback to Tesseract if EasyOCR didn't work
        if tesseract_backend:
            try:
                text, confidence = tesseract_backend.extract_text(image)
                if text and len(text.strip()) >= 3:
                    print(f"🔄 Tesseract fallback: '{text.strip()}' (confidence: {confidence:.3f})")
                    if debug_info:
                        debug_info['tesseract_result'] = f"{text.strip()} (conf: {confidence:.2f})"
                        debug_info['best_backend'] = 'Tesseract'
                        debug_info['best_confidence'] = confidence
                    return text.strip()
                else:
                    print(f"⚠️ Tesseract returned short/empty result: '{text.strip()}'")
                    if debug_info:
                        debug_info['tesseract_result'] = f"Short result: '{text.strip()}' (conf: {confidence:.2f})"
            except Exception as e:
                print(f"❌ Tesseract failed: {e}")
                if debug_info:
                    debug_info['tesseract_error'] = str(e)
        
        # No usable results from either backend
        print("❌ No OCR backend produced usable results")
        if debug_info:
            debug_info['best_backend'] = 'None'
            debug_info['best_confidence'] = 0.0
        
        return ""
    
    def _score_result_quality(self, text: str, confidence: float) -> float:
        """Score the quality of an OCR result for book titles"""
        if not text:
            return 0.0
        
        score = confidence * 0.4  # Base confidence score
        
        # Text length (book titles are usually reasonable length)
        length = len(text.strip())
        if 5 <= length <= 50:
            score += 0.3
        elif 3 <= length <= 70:
            score += 0.2
        elif length < 3:
            score -= 0.3
        
        # Word count (most titles have multiple words)
        words = text.strip().split()
        if len(words) >= 2:
            score += 0.2
        elif len(words) == 1 and length >= 4:
            score += 0.1
        
        # Character composition
        alpha_ratio = sum(1 for c in text if c.isalpha()) / len(text) if text else 0
        if alpha_ratio > 0.7:
            score += 0.1
        
        # Mixed case (better than all caps or lowercase)
        if not (text.isupper() or text.islower()) and any(c.isupper() for c in text):
            score += 0.1
        
        return min(1.0, score)

# Global OCR engine instance
_ocr_engine = None

def get_ocr_engine() -> MultiOCREngine:
    """Get global OCR engine instance"""
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = MultiOCREngine()
    return _ocr_engine
