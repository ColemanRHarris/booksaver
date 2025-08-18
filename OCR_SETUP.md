# OCR Backend Setup

The TikTok Book Finder uses a dual-backend OCR system for optimal text extraction from book covers.

## Available Backends

### ✅ EasyOCR (Primary)
- **Status**: Always installed and available
- **Best for**: Scene text, various fonts, angles, lighting conditions
- **Performance**: High accuracy, good speed
- **Use case**: Primary OCR engine for book title detection

### ✅ Tesseract OCR (Fallback)
- **Status**: Always installed and available  
- **Best for**: Clean printed text, reliable fallback
- **Performance**: Fast, good accuracy for standard text
- **Use case**: Backup when EasyOCR fails or for validation

## Installation

### Standard Installation
```bash
# Installs EasyOCR + Tesseract (everything you need)
uv sync
```

No additional setup required! The system automatically detects and uses both backends.

## System Behavior

1. **Automatic Backend Detection**: System detects available backends at runtime
2. **Multi-backend Processing**: Tries both EasyOCR and Tesseract for each detection
3. **Best Result Selection**: Automatically selects the highest quality result
4. **Graceful Degradation**: If one backend fails, continues with the other
5. **Optimized Performance**: Streamlined for speed without sacrificing accuracy

## Performance Comparison

| Backend | Speed | Accuracy | Reliability | Book Titles |
|---------|-------|----------|-------------|-------------|
| EasyOCR | Medium | High | Excellent | Excellent |
| Tesseract | Fast | Good | Excellent | Good |

## System Requirements

- **EasyOCR**: Works on all systems with Python 3.11+
- **Tesseract**: Requires tesseract binary (auto-installed via system packages)
- **OpenCV**: Uses opencv-python-headless (handled automatically)

## Troubleshooting

### Backend Initialization
The system logs which backends are available at startup:
```
🔤 OCR Engine initialized with 2 backends: ['EasyOCR', 'Tesseract']
```

### Common Issues
- **Tesseract not found**: Ensure system has tesseract installed (handled by build.sh)
- **EasyOCR loading**: First run downloads models automatically
- **Performance**: Both backends are optimized for book title detection

## Recommendation

The default installation provides excellent results with optimal performance. The two-backend system offers:
- **High accuracy** from EasyOCR for complex scene text
- **Fast processing** from Tesseract for clean text
- **Reliability** through automatic fallback mechanisms
- **Optimized speed** for production deployment