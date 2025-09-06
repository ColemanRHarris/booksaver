# BookSaver – the Shazam for Books (`claude.md`)

## 1. Overall Goal
Your job is to improve the **existing, functional web app** that takes images as input and runs requests to the Gemini model and Google Books API. The goal will be to streamline the app deployment onto Render, including removing previous dependencies on Redis and celery tasks and instead having everything built into one app.
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

## 3. Improvements
- Perform a full repository audit, removing any unnecessary dependencies, spaghetti code, and unused modules. Focus on streamlining the app in its current form.
- Prepare the application for Render deployment, specifically removing dependencies on Redis as a backend (remember no user accounts, no caching for now) and removing dependencies on the worker machine as well.
- Finally, perform a security audit to ensure no issues are present.