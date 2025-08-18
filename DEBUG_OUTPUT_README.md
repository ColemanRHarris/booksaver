# Debug Output Directory

This document explains the debug output generated during TikTok video processing for OCR debugging.

## Directory Structure

When processing a TikTok video, debug files are saved to:
```
debug_output/
└── tiktok_[8-char-id]/
    ├── debug_frames/
    │   └── frame_XXX_detections_N.jpg    # Full frames with bounding boxes
    └── debug_crops/
        ├── frame_XXX_det_YY_original.jpg  # Original cropped regions
        ├── frame_XXX_det_YY_enhanced.jpg  # Enhanced for OCR
        └── frame_XXX_det_YY_ocr.txt       # OCR results and metadata
```

## File Types

### Debug Frames (`debug_frames/`)
- **Purpose**: Visual verification of object detection
- **Format**: `frame_XXX_detections_N.jpg`
- **Content**: Full video frames with colored bounding boxes:
  - 🟢 **Green**: Objects classified as "book"
  - 🟠 **Orange**: Other book-related objects (person, laptop, etc.)
- **Labels**: Show object class and confidence score

### Debug Crops (`debug_crops/`)
- **Original crops**: Raw regions extracted from bounding boxes
- **Enhanced crops**: After image processing for better OCR
- **OCR text files**: Contains:
  - Raw OCR output
  - Cleaned text
  - Object class and confidence
  - Bounding box coordinates

## Usage for Debugging

1. **Check detection accuracy**: Look at `debug_frames/` to see if books are being detected
2. **Analyze crop quality**: Examine `debug_crops/*_original.jpg` to see what regions are being extracted
3. **Review OCR enhancement**: Compare original vs enhanced crops to see processing effects
4. **Debug text extraction**: Read `*_ocr.txt` files to see raw vs cleaned OCR results

## Cleanup

Debug directories are automatically created with unique IDs and won't be deleted. You can manually remove old debug folders when no longer needed:

```bash
rm -rf debug_output/tiktok_[old-id]
```

The `debug_output/` directory is ignored by git to prevent committing debug files.