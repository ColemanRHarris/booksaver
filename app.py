from flask import Flask, render_template, request, redirect, url_for
from dotenv import load_dotenv
import os
from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

books_client = GoogleBooksClient()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form.get('query', '').strip()
    
    if not query:
        return render_template('index.html', error="Please enter a book title or ISBN")
    
    try:
        books = books_client.search_books(query)
        
        # Add purchase links to each book
        for book in books:
            book['purchase_links'] = build_purchase_links(book)
            book['amazon_link'] = build_amazon_link(book)  # Keep for backward compatibility
        
        if not books:
            return render_template('results.html', books=[], query=query, 
                                 error="No books found for your search. Try a different title or ISBN.")
        
        return render_template('results.html', books=books, query=query)
        
    except ValueError as e:
        return render_template('index.html', error=f"Configuration error: {str(e)}")
    except Exception as e:
        return render_template('index.html', error="Something went wrong. Please try again later.")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)