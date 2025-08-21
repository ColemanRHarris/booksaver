"""
Multi-backend OCR system for BookSaver.
Supports EasyOCR (primary), Tesseract, and PaddleOCR with intelligent fallback.
"""

import os
import cv2
import numpy as np
from typing import List, Dict, Any, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class OCREngine:
    """Multi-backend OCR engine with intelligent fallback"""
    
    def __init__(self):
        self.available_backends = []
        self.primary_backend = None
        
        # Initialize available backends
        self._initialize_backends()
        
        # OCR enhancement settings
        self.enhance_image = True
        self.min_confidence = 0.5
        
        logger.info(f"🔍 OCR Engine initialized with {len(self.available_backends)} backends")
        logger.info(f"🎯 Primary backend: {self.primary_backend}")
        
    def _initialize_backends(self):
        """Initialize available OCR backends"""
        
        # Try EasyOCR (primary choice)
        try:
            import easyocr
            self.easyocr_reader = easyocr.Reader(['en'], gpu=False)
            self.available_backends.append('easyocr')
            self.primary_backend = 'easyocr'
            logger.info("✅ EasyOCR initialized successfully")
        except ImportError:
            logger.warning("⚠️ EasyOCR not available")
        except Exception as e:
            logger.warning(f"⚠️ EasyOCR initialization failed: {e}")
        
        # Try Tesseract
        try:
            import pytesseract
            # Test if tesseract is actually available
            pytesseract.get_tesseract_version()
            self.available_backends.append('tesseract')
            if not self.primary_backend:
                self.primary_backend = 'tesseract'
            logger.info("✅ Tesseract initialized successfully")
        except ImportError:
            logger.warning("⚠️ pytesseract not available")
        except Exception as e:
            logger.warning(f"⚠️ Tesseract initialization failed: {e}")
        
        # Try PaddleOCR
        try:
            from paddleocr import PaddleOCR
            self.paddle_ocr = PaddleOCR(use_angle_cls=True, lang='en', use_gpu=False, show_log=False)
            self.available_backends.append('paddleocr')
            if not self.primary_backend:
                self.primary_backend = 'paddleocr'
            logger.info("✅ PaddleOCR initialized successfully")
        except ImportError:
            logger.warning("⚠️ PaddleOCR not available")
        except Exception as e:
            logger.warning(f"⚠️ PaddleOCR initialization failed: {e}")
        
        if not self.available_backends:
            raise RuntimeError("❌ No OCR backends available! Please install easyocr, pytesseract, or paddleocr")
    
    def extract_text_multi_backend(self, image: np.ndarray, debug_info: Dict[str, Any] = None) -> str:
        """Extract text using multiple OCR backends with quality scoring"""
        if debug_info is None:
            debug_info = {}
        
        # Enhance image if requested
        if self.enhance_image:
            image = self._enhance_image_for_ocr(image)
        
        results = []
        
        # Try each backend and collect results
        for backend in self.available_backends:
            try:
                text, confidence = self._extract_with_backend(image, backend)
                if text.strip():  # Only consider non-empty results
                    results.append({
                        'backend': backend,
                        'text': text,
                        'confidence': confidence,
                        'quality_score': self._calculate_quality_score(text, confidence, backend)
                    })
                    logger.debug(f"🔍 {backend}: '{text[:50]}...' (conf: {confidence:.2f})")
            except Exception as e:
                logger.warning(f"⚠️ {backend} failed: {e}")
                continue
        
        if not results:
            logger.warning("❌ All OCR backends failed")
            return ""
        
        # Sort by quality score and return best result
        results.sort(key=lambda x: x['quality_score'], reverse=True)
        best_result = results[0]
        
        # Store debug information
        debug_info.update({
            'ocr_backends_tried': len(results),
            'best_backend': best_result['backend'],
            'best_confidence': best_result['confidence'],
            'best_quality_score': best_result['quality_score'],
            'all_results': [{'backend': r['backend'], 'text': r['text'][:100]} for r in results]
        })
        
        logger.info(f"🎯 Best OCR result from {best_result['backend']}: quality={best_result['quality_score']:.1f}")
        return best_result['text']
    
    def _extract_with_backend(self, image: np.ndarray, backend: str) -> Tuple[str, float]:
        """Extract text with a specific backend"""
        
        if backend == 'easyocr':
            return self._extract_with_easyocr(image)
        elif backend == 'tesseract':
            return self._extract_with_tesseract(image)
        elif backend == 'paddleocr':
            return self._extract_with_paddleocr(image)
        else:
            raise ValueError(f"Unknown backend: {backend}")
    
    def _extract_with_easyocr(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using EasyOCR"""
        # Convert BGR to RGB
        if len(image.shape) == 3:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        else:
            image_rgb = image
        
        # EasyOCR parameters optimized for book detection
        results = self.easyocr_reader.readtext(
            image_rgb, 
            detail=1, 
            paragraph=False,
            width_ths=0.7,          # Better word separation for titles
            height_ths=0.7,         # Better line separation
            text_threshold=0.6,     # Higher threshold for better quality
            canvas_size=2560,       # Higher resolution processing
            mag_ratio=1.5           # Magnification for better small text
        )
        
        if not results:
            return "", 0.0
        
        # Extract text and calculate average confidence
        texts = []
        confidences = []
        
        for (bbox, text, conf) in results:
            if conf > self.min_confidence:
                texts.append(text.strip())
                confidences.append(conf)
        
        if not texts:
            return "", 0.0
        
        combined_text = ' '.join(texts)
        avg_confidence = sum(confidences) / len(confidences)
        
        return combined_text, avg_confidence
    
    def _extract_with_tesseract(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using Tesseract OCR"""
        import pytesseract
        
        # Tesseract configuration for book detection
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,!?-:;'
        
        # Get text with confidence data
        data = pytesseract.image_to_data(image, config=custom_config, output_type=pytesseract.Output.DICT)
        
        # Filter high-confidence words
        texts = []
        confidences = []
        
        for i in range(len(data['text'])):
            conf = int(data['conf'][i])
            text = data['text'][i].strip()
            
            if conf > (self.min_confidence * 100) and text:  # Tesseract confidence is 0-100
                texts.append(text)
                confidences.append(conf / 100.0)  # Convert to 0-1 scale
        
        if not texts:
            return "", 0.0
        
        combined_text = ' '.join(texts)
        avg_confidence = sum(confidences) / len(confidences)
        
        return combined_text, avg_confidence
    
    def _extract_with_paddleocr(self, image: np.ndarray) -> Tuple[str, float]:
        """Extract text using PaddleOCR"""
        results = self.paddle_ocr.ocr(image, cls=True)
        
        if not results or not results[0]:
            return "", 0.0
        
        texts = []
        confidences = []
        
        for line in results[0]:
            if len(line) >= 2:
                bbox, (text, conf) = line[0], line[1]
                if conf > self.min_confidence and text.strip():
                    texts.append(text.strip())
                    confidences.append(conf)
        
        if not texts:
            return "", 0.0
        
        combined_text = ' '.join(texts)
        avg_confidence = sum(confidences) / len(confidences)
        
        return combined_text, avg_confidence
    
    def _enhance_image_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """Enhance image for better OCR results"""
        try:
            # Convert to grayscale if needed
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image
            
            # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(gray)
            
            # Apply slight Gaussian blur to reduce noise
            enhanced = cv2.GaussianBlur(enhanced, (1, 1), 0)
            
            # Apply sharpening kernel
            sharpening_kernel = np.array([[-1,-1,-1],
                                        [-1, 9,-1],
                                        [-1,-1,-1]])
            enhanced = cv2.filter2D(enhanced, -1, sharpening_kernel)
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"⚠️ Image enhancement failed: {e}")
            return image
    
    def _calculate_quality_score(self, text: str, confidence: float, backend: str) -> float:
        """Calculate quality score for OCR result (0-100 scale)"""
        score = confidence * 100  # Base score from confidence
        
        # Backend preference (EasyOCR is preferred)
        backend_multiplier = {
            'easyocr': 1.2,
            'tesseract': 1.0,
            'paddleocr': 1.1
        }
        score *= backend_multiplier.get(backend, 1.0)
        
        # Text quality indicators
        if text:
            # Prefer longer text (more context)
            length_bonus = min(len(text) / 50.0, 1.0) * 10  # Up to 10 points
            score += length_bonus
            
            # Prefer text with proper capitalization (book titles)
            if any(c.isupper() for c in text):
                score += 5
            
            # Prefer text with alphabetic characters
            alpha_ratio = sum(c.isalpha() for c in text) / len(text) if text else 0
            score += alpha_ratio * 10
            
            # Penalize very short results
            if len(text.strip()) < 3:
                score -= 20
            
            # Penalize results with too many special characters
            special_ratio = sum(not c.isalnum() and not c.isspace() for c in text) / len(text) if text else 0
            if special_ratio > 0.3:
                score -= 15
        
        return max(0, min(100, score))  # Clamp to 0-100


# Global OCR engine instance
_ocr_engine = None


def get_ocr_engine() -> OCREngine:
    """Get or create the global OCR engine instance"""
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = OCREngine()
    return _ocr_engine


def extract_text_from_image(image: np.ndarray, debug_info: Dict[str, Any] = None) -> str:
    """Convenience function to extract text from an image"""
    engine = get_ocr_engine()
    return engine.extract_text_multi_backend(image, debug_info)


def extract_text_from_frames(frames: List[np.ndarray]) -> List[str]:
    """Extract text from multiple frames efficiently"""
    engine = get_ocr_engine()
    results = []
    
    for i, frame in enumerate(frames):
        try:
            debug_info = {}
            text = engine.extract_text_multi_backend(frame, debug_info)
            results.append(text)
            
            if text.strip():
                logger.info(f"📝 Frame {i+1}: Found text '{text[:50]}...' via {debug_info.get('best_backend', 'unknown')}")
            else:
                logger.debug(f"🔍 Frame {i+1}: No text detected")
                
        except Exception as e:
            logger.error(f"❌ Frame {i+1} OCR failed: {e}")
            results.append("")
    
    return results