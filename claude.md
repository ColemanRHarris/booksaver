# BookSaver, the TikTok Book Finder – TikTok Development Plan (`claude.md`)

## 1. New Goal
Refine the **existing, functional web app** to streamline the user experience and OCR to make an addicting TikTok book search app.

---

## 2. Core Flow (Updated)
1. **TikTok Ingestion**  
   - Input: TikTok share-link  
   - Output: `video.mp4` saved to **local tmp**  
   - Method: `yt-dlp` (community downloader) wrapped in **Celery** task

2. **Book Detection (CV)**  
   - Extract 1 fps frames with `opencv-python`  
   - Run **YOLO11-n** model fine-tuned on ~1 k book images → bounding boxes

3. **OCR & Title/Author Extraction**  
   - Crop bounding boxes → **EasyOCR**  
   - Clean & fuzzy-deduplicate titles → Google Books API → canonical title + **ASIN**

---

## 3. Tech Stack (Additions)
| Component        | Library / Service                         |
|------------------|------------------------------------------|
| Video download   | `yt-dlp`,               |
| CV + ML          | `ultralytics==8.0.200`, `opencv-python`, `easyocr` |
| Async processing | **Celery**                   |
| Object storage   | local `/tmp`                             |
| Framework        | **Flask** (kept from previous MVP)       |

---

## 4. Privacy & Compliance (TikTok + Amazon)
- **TikTok Terms**: store only the video ID, no user data; respect rate limits.  
- **GDPR / CCPA**: cookie banner for Amazon tracking cookies.  
- **Amazon Associates** and **Google Ads**:  
  - Display **prominent disclosure** on every page:  
    “As an Amazon Associate I earn from qualifying purchases.”
  - Link to Amazon Privacy Policy.  

---

## 5. Improvements
- Implement recommendation engine for training.
- Streamline UI for mobile web app users.
- Optimize for Google Ads implementation.