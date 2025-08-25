# BookSaver – the Shazam for Books (`claude.md`)

## 1. Overall Goal
Your job is to improve the **existing, functional web app** that takes images as input and runs requests to the Gemini model and Google Books API. Your primary goal is to improve the UI and user flow to make a cutting edge web app.

---

## 2. Core Flow (Updated)
1. **Image Ingestion**  
   - Input: Image of a book
   - Output: `image.jpg` saved to **local tmp**  

2. **Book Detection**  
   - Extract using image input and existing prompt to the Google Gemini model

3. **Author Extraction**  
   - Clean & fuzzy-deduplicate titles → Google Books API → canonical title + **ASIN**

---

## 3. Tech Stack (Additions)
| Component        | Library / Service                         |
|------------------|------------------------------------------|
| CV + ML          | `google-genai`  | 
| Async processing | **Celery**                   |
| Object storage   | local `/tmp`                             |
| Framework        | **Flask**       |

---

## 4. Privacy & Compliance (TikTok + Amazon)
- **GDPR / CCPA**: cookie banner for Amazon tracking cookies.  
- **Amazon Associates**:
  - Display **prominent disclosure** on every page:  
    “As an Amazon Associate I earn from qualifying purchases.”
  - Link to Amazon Privacy Policy.  

---

## 5. Improvements
- Streamline UI for mobile web app users to reel in subscriptions.