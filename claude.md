# Book Finder Web App - MVP Development Plan (`claude.md`)

## 1. MVP Goal
Build a minimal web application that lets a user **type a book title or ISBN** into a search bar, displays matching books via the **Google Books API**, and provides a one-click **“Add to Amazon wish-list”** link for each result.

*(No TikTok downloading, no video processing—keep the first release laser-focused.)*

---

## 2. Core Modules & Flow
1. **Search Input** → 2. **Google Books Query** → 3. **Display Results** → 4. **Amazon Redirect**

| Module              | Responsibility                                                                 |
|---------------------|--------------------------------------------------------------------------------|
| Search Bar          | HTML form + server-side validation (Flask-WTF).                             |
| Google Books Client | Python `requests` calling Google Books REST API.                              |
| Result Renderer     | Server-side Jinja2 template listing cover, title, author, Amazon link.         |
| Amazon Link Builder | Construct search URL: `https://www.amazon.com/s?k=<ISBN>` or `&field-keywords=<Title+Author>` |
| Error Handler       | If Google Books returns 0 hits, show “Book not found” message.                 |

---

## 3. Tech Stack (Minimal Python-Only)
- **Backend / Frontend**: **Flask** (micro-framework) + **Jinja2** templates  
- **Styling**: Vanilla CSS (single `style.css` file)  
- **HTTP Client**: `requests` library  
- **Development Runner**: `python -m flask run`  
- **Hosting**: **Render** (free Python web service) or **PythonAnywhere**  
- **Environment**: `.env` file storing `GOOGLE_BOOKS_KEY`

---

## 4. API Sketch
### Google Books endpoint (called from Flask)
```python
import requests, os

def search_books(query: str):
    url = &quot;https://www.googleapis.com/books/v1/volumes&quot;
    params = {
        &quot;q&quot;: f&quot;intitle:{query}&quot;,
        &quot;maxResults&quot;: 10,
        &quot;key&quot;: os.getenv(&quot;GOOGLE_BOOKS_KEY&quot;)
    }
    return requests.get(url, params=params).json()
