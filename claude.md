# TikTok Book Finder – MVP+TikTok Development Plan (`claude.md`)

## 1. New MVP Goal
Extend the **existing Python-only web app** (search-only) to let a user **paste a TikTok URL** and receive a list of books detected in the video.

---

## 2. Core Flow (Updated)
1. **TikTok Ingestion**  
   - Input: TikTok share-link  
   - Output: `video.mp4` saved to **local tmp**  
   - Method: `yt-dlp` (community downloader) wrapped in **Celery** task

2. **Book Detection (CV)**  
   - Extract 1 fps frames with **FFmpeg** → `opencv-python`  
   - Run **YOLOv8-s** model fine-tuned on ~1 k book images → bounding boxes

3. **OCR & Title/Author Extraction**  
   - Crop bounding boxes → **Tesseract** OCR  
   - Clean & fuzzy-deduplicate titles → Google Books API → canonical title + **ASIN**

---

## 3. Tech Stack (Additions)
| Component        | Library / Service                         |
|------------------|------------------------------------------|
| Video download   | `yt-dlp`, `ffmpeg-python`                |
| CV + ML          | `ultralytics==8.0.200`, `opencv-python`, `pytesseract` |
| Async processing | **Celery**                   |
| Object storage   | local `/tmp`                             |
| Framework        | **Flask** (kept from previous MVP)       |

---

## 4. Privacy & Compliance (TikTok + Amazon)
- **TikTok Terms**: store only the video ID, no user data; respect rate limits.  
- **GDPR / CCPA**: add cookie banner for Amazon tracking cookies.  
- **Amazon Associates**:  
  - Display **prominent disclosure** on every page:  
    “As an Amazon Associate I earn from qualifying purchases.”  
  - Link to Amazon Privacy Policy.  