# OCR Backend Setup

The TikTok Book Finder uses a multi-backend OCR system for optimal text extraction. Here's how the backends work:

## Default Backends (Always Available)

### ✅ EasyOCR 
- **Status**: Always installed and available
- **Best for**: Scene text, various fonts, angles, lighting conditions
- **Performance**: Good accuracy, reasonable speed

### ✅ Tesseract OCR
- **Status**: Always installed and available  
- **Best for**: Clean printed text, fallback option
- **Performance**: Fast, reliable for standard text

## Optional Backend

### ⚠️ PaddleOCR (Optional)
- **Status**: Optional due to complex dependencies
- **Best for**: Printed text, often most accurate when working
- **Installation**: `uv sync --extra paddle` or `pip install paddlepaddle-cpu paddleocr`

## Installation Notes

### Standard Installation
```bash
# Installs EasyOCR + Tesseract (recommended)
uv sync
```

### With PaddleOCR (Advanced Users Only)
```bash
# Standard installation (recommended)
uv sync

# If you want to try PaddleOCR manually (optional):
pip install paddlepaddle paddleocr
# or for CPU-only: pip install paddlepaddle-cpu paddleocr
```

**Note**: PaddleOCR has complex dependencies and may not install cleanly on all systems. The system works excellently with just EasyOCR + Tesseract, so this is completely optional.

## System Behavior

1. **Automatic Backend Detection**: The system detects which backends are available at runtime
2. **Graceful Degradation**: If PaddleOCR isn't installed or fails, continues with EasyOCR + Tesseract
3. **No Impact on Functionality**: Missing PaddleOCR does not affect the core book detection functionality
4. **Smart Fallback**: Always ensures at least 2 working OCR backends (EasyOCR + Tesseract)

## Troubleshooting

### PaddleOCR Messages
If you see `"PaddleOCR skipped - paddlepaddle not installed (this is optional)"`, this is completely normal and expected. The application works perfectly without it.

### Adding PaddleOCR Later (Optional)
If you want to experiment with PaddleOCR later:
```bash
# Try the standard package first
pip install paddlepaddle paddleocr

# If that fails, try CPU-only version
pip install paddlepaddle-cpu paddleocr
```

**Important**: PaddleOCR installation success varies by system. Don't worry if it doesn't work - EasyOCR + Tesseract provide excellent results.

### System Requirements
- **EasyOCR**: Works on all systems with Python 3.11+
- **Tesseract**: Requires tesseract binary (usually auto-installed)
- **PaddleOCR**: Requires paddlepaddle framework (heavyweight)
- **OpenCV**: Uses opencv-python-headless + opencv-python (handled automatically)

## Performance Comparison

| Backend | Speed | Accuracy | Reliability | Book Titles |
|---------|-------|----------|-------------|-------------|
| EasyOCR | Medium | High | Excellent | Excellent |
| Tesseract | Fast | Medium | Excellent | Good |
| PaddleOCR | Slow | Very High | Variable | Excellent |

## Recommendation

For most users, the default installation with **EasyOCR + Tesseract** provides excellent results without the complexity of PaddleOCR dependencies.