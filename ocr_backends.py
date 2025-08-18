"""
Multi-backend OCR system with fallback support for better text extraction
"""

# Handle OpenCV import conflicts and threading issues
try:
    import cv2
    # Fix common OpenCV threading issues  
    if hasattr(cv2, 'setNumThreads'):
        cv2.setNumThreads(1)  # Prevent threading issues
except Exception as e:
    print(f"Warning: OpenCV import issue in OCR backends: {e}")
    import cv2  # Try again

import numpy as np
import pytesseract
from typing import List, Dict, Optional, Tuple
import warnings
import os
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
        
        # Try multiple Tesseract configurations for book titles
        configs = [
            # Best for book titles (mixed case, preserve spaces)
            '--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\\ \\-\\\'',
            # Sparse text (good for isolated titles)
            '--oem 3 --psm 8 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\\ \\-\\\'',
            # Single text line
            '--oem 3 --psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789\\ \\-\\\'',
            # Default with character whitelist
            '--oem 3 --psm 6',
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
            import easyocr
            self.reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            self.available = True
            print(f"✅ {self.name} initialized successfully")
        except Exception as e:
            print(f"❌ {self.name} initialization failed: {e}")
            self.available = False
    
    def extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using EasyOCR"""
        if not self.available:
            return "", 0.0
        
        try:
            # EasyOCR expects RGB
            if len(image.shape) == 3:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
            
            # Run EasyOCR
            results = self.reader.readtext(image_rgb, detail=1, paragraph=False)
            
            if not results:
                return "", 0.0
            
            # Combine all detected text with confidence weighting
            texts = []
            confidences = []
            
            for (bbox, text, confidence) in results:
                if confidence > 0.3:  # Filter low-confidence detections
                    texts.append(text.strip())
                    confidences.append(confidence)
            
            if not texts:
                return "", 0.0
            
            # Join texts and calculate weighted confidence
            combined_text = " ".join(texts)
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
            
            return combined_text, avg_confidence
            
        except Exception as e:
            print(f"EasyOCR error: {e}")
            return "", 0.0

class PaddleOCRBackend(OCRBackend):
    """PaddleOCR backend - very accurate for printed text"""
    
    def initialize(self):
        try:
            # First check if paddle is available
            try:
                import paddle
            except ImportError:
                raise ImportError("PaddlePaddle not installed. Install with: pip install paddlepaddle")
            
            # Suppress paddle logging before import
            import os
            os.environ['FLAGS_logtostderr'] = '0'
            os.environ['FLAGS_eager_delete_tensor_gb'] = '0'
            
            # Import and initialize PaddleOCR with minimal config
            from paddleocr import PaddleOCR
            
            # Force CPU to avoid GPU conflicts
            paddle.set_device('cpu')
            
            # Initialize with conservative settings to avoid conflicts
            self.ocr = PaddleOCR(
                use_angle_cls=True, 
                lang='en'
            )
            self.available = True
            print(f"✅ {self.name} initialized successfully (CPU mode)")
            
        except ImportError as e:
            print(f"⚠️ {self.name} initialization failed - missing dependency: {e}")
            self.available = False
        except Exception as e:
            print(f"❌ {self.name} initialization failed: {e}")
            print(f"   Note: PaddleOCR can be resource intensive. EasyOCR and Tesseract are still available.")
            self.available = False
    
    def extract_text(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using PaddleOCR"""
        if not self.available:
            return "", 0.0
        
        try:
            # Suppress PaddleOCR warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                
                # PaddleOCR works with BGR images (OpenCV format)
                result = self.ocr.ocr(image)
                
                if not result or not result[0]:
                    return "", 0.0
                
                # Extract text and confidence
                texts = []
                confidences = []
                
                for line in result[0]:
                    # Ensure the structure of the detection is as expected: [bbox_coords, (text_str, confidence_float)]
                    if isinstance(line, list) and len(line) >= 2:
                        text_conf_data = line[1]
                        # Ensure the second element is a tuple/list containing (text, confidence)
                        if isinstance(text_conf_data, (tuple, list)) and len(text_conf_data) >= 2:
                            text = text_conf_data[0] # Get the text string
                            confidence = text_conf_data[1] # Get the confidence float
                            
                            # Clean and validate text/confidence before appending
                            if isinstance(text, str) and isinstance(confidence, (float, int)):
                                text = text.strip()
                                # Filter based on confidence and length of the extracted text
                                if confidence > 0.3 and len(text) > 1:
                                    texts.append(text)
                                    confidences.append(confidence)
                
                if not texts:
                    return "", 0.0
                
                # Join texts and calculate confidence
                combined_text = " ".join(texts)
                avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
                
                return combined_text, avg_confidence
                
        except Exception as e:
            print(f"PaddleOCR error: {e}")
            return "", 0.0

class MultiOCREngine:
    """OCR engine that tries multiple backends for best results"""
    
    def __init__(self):
        # Initialize core backends (always try these)
        self.backends = [
            EasyOCRBackend("EasyOCR"),          # Most reliable, good for scene text
            TesseractOCR("Tesseract"),          # Always available fallback
        ]
        
        # Try to add PaddleOCR if dependencies are available (completely optional)
        try:
            # Check for paddlepaddle and paddleocr libraries
            import paddle
            from paddleocr import PaddleOCR # Attempt to import PaddleOCR directly

            # If imports succeed, then try to initialize the backend
            paddle_backend = PaddleOCRBackend("PaddleOCR")
            if paddle_backend.available:
                self.backends.insert(1, paddle_backend)  # Insert after EasyOCR but before Tesseract
                print("ℹ️  PaddleOCR successfully added as optional backend")
            else:
                # If backend initialized but reported not available (e.g., internal Paddle error)
                print(f"⚠️  PaddleOCR backend reported not available after initialization.")

        except ImportError as e:
            # Differentiate between paddle and paddleocr import issues
            if "paddleocr" in str(e):
                print("ℹ️  PaddleOCR skipped - 'paddleocr' library not installed (this is optional). Install with: pip install paddleocr")
            else:
                print("ℹ️  PaddleOCR skipped - 'paddlepaddle' library not installed (this is optional). Install with: pip install paddlepaddle")
        except Exception as e:
            # Catch any other runtime issues during PaddleOCR setup
            print(f"❌ PaddleOCR initialization encountered an unexpected error and will be skipped: {e}")
            print(f"   Note: This might be due to a complex environment or resource issue. EasyOCR and Tesseract are still available.")
        
        self.available_backends = [b for b in self.backends if b.available]
        
        if self.available_backends:
            backend_names = [b.name for b in self.available_backends]
            print(f"🔤 OCR Engine initialized with {len(self.available_backends)} backends: {backend_names}")
            
            # Show which backends failed (if any)
            failed_backends = [b.name for b in self.backends if not b.available]
            if failed_backends:
                print(f"⚠️  Failed backends (will be skipped): {failed_backends}")
        else:
            print("❌ No OCR backends available!")
            print("   Try installing dependencies: pip install easyocr pytesseract paddlepaddle paddleocr")
    
    def extract_text_multi_backend(self, image: np.ndarray, debug_info: dict = None) -> str:
        """Extract text using multiple backends and return best result"""
        if not self.available_backends:
            return ""
        
        results = []
        
        # Try each available backend
        for backend in self.available_backends:
            try:
                text, confidence = backend.extract_text(image)
                if text and len(text.strip()) > 0:
                    results.append({
                        'backend': backend.name,
                        'text': text.strip(),
                        'confidence': confidence,
                        'quality_score': self._score_result_quality(text.strip(), confidence)
                    })
                    
                    if debug_info:
                        debug_info[f'{backend.name.lower()}_result'] = f"{text.strip()} (conf: {confidence:.2f})"
                        
            except Exception as e:
                print(f"Backend {backend.name} failed: {e}")
                continue
        
        if not results:
            return ""
        
        # Sort by quality score and return best
        results.sort(key=lambda x: x['quality_score'], reverse=True)
        best_result = results[0]
        
        if debug_info:
            debug_info['best_backend'] = best_result['backend']
            debug_info['best_score'] = best_result['quality_score']
            debug_info['all_results'] = {r['backend']: r['text'] for r in results}
        
        print(f"🏆 Best OCR result: {best_result['backend']} -> '{best_result['text']}' (score: {best_result['quality_score']:.2f})")
        return best_result['text']
    
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
