# BookSaver – the Shazam for Books (`claude.md`)

## 1. Overall Goal
Your job is to improve the **existing, functional web app** that takes images as input and runs requests to the Gemini model and Google Books API. The goal will be to streamline the user experience and remove the "fluff" from the existing web app.
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
- Create a much simpler user interface - images can be added on the left and results appear on the right. No processing page, just a clean, simple landing page (white with navy text). Think simple like these landing pages: news.ycombinator.com, google.com, remove.bg
- Remove user accounts, caching in Redis, and the Stripe integration. 
- The only source of monetization for the app will be affiliate links.
- Remove all references to upgrading to Booksaver premium.
- I would like to heavily simplify the results CSS - it looks too flashy now. Just some basic links to other sites with results.
- Change the fuzzy search, there are too many nonsense results. After gettings results from the Gemini model, rank based on text similarity to the <Title, Author> pair and remove any that are not close to the google Books results.