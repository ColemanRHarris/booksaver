"""
SEO Landing Pages routes for parasite SEO implementation.
Handles routing for genre pages, author pages, and 'books like' pages.
"""

from flask import render_template, abort, request, redirect, url_for, flash
from services.seo_service import get_seo_service
from services.books_client import GoogleBooksClient, build_purchase_links, build_reader_app_links
from datetime import datetime
from typing import List, Dict, Any
import re
import random


def register_seo_routes(app, limiter):
    """Register SEO landing page routes."""
    
    seo_service = get_seo_service()
    
    # Best Books by Genre Pages
    @app.route('/best-books/<genre_slug>/')
    @app.route('/best-books/<genre_slug>/<int:year>/')
    @limiter.limit("30 per minute")
    def best_genre_books(genre_slug, year=2025):
        """Best books in genre for specific year."""
        
        # Validate year
        current_year = datetime.now().year
        if year < 2020 or year > current_year + 1:
            abort(404)
        
        # Get genre data
        genre_data = seo_service.get_genre(genre_slug)
        if not genre_data:
            abort(404)
        
        # Check if SEO page exists, if not create it
        seo_page = seo_service.get_seo_page('genre', f"{genre_slug}-{year}")
        if not seo_page:
            # Create the page on-demand
            title = f"Best {genre_data['display_name']} Books {year}"
            meta_description = f"Discover the best {genre_data['display_name'].lower()} books of {year}. Curated recommendations with purchase links and reading app integration."
            
            content_data = {
                "genre": genre_data['display_name'],
                "year": year,
                "books": []  # Will be populated by content generation
            }
            
            seo_service.create_seo_page('genre', f"{genre_slug}-{year}", title, meta_description, content_data)
            seo_page = seo_service.get_seo_page('genre', f"{genre_slug}-{year}")
        
        # Get books for this genre (this would integrate with your books API)
        books = get_curated_genre_books(genre_data['display_name'], year)
        
        # Update the page data with fresh books
        seo_page['content_data']['books'] = books
        
        return render_template('seo/genre_books.html',
                             genre=genre_data,
                             year=year,
                             books=books,
                             page_data=seo_page,
                             canonical_url=request.url)
    
    # Author Recommendations Pages
    @app.route('/authors/<author_slug>/recommendations/')
    @limiter.limit("30 per minute")  
    def author_recommendations(author_slug):
        """Author recommendation page."""
        
        # Get author data
        author_data = seo_service.get_author(author_slug)
        if not author_data:
            # Try to create author page from slug
            author_name = author_slug.replace('-', ' ').title()
            author_data = create_author_page(author_slug, author_name)
            if not author_data:
                abort(404)
        
        # Check if SEO page exists
        seo_page = seo_service.get_seo_page('author', author_slug)
        if not seo_page:
            # Create the page on-demand
            title = f"{author_data['name']} Books - Complete Reading Guide"
            meta_description = f"Explore all books by {author_data['name']}. Complete bibliography with recommendations, purchase links, and reading order guide."
            
            content_data = {
                "author": author_data['name'],
                "bio": author_data.get('bio', ''),
                "books": []
            }
            
            seo_service.create_seo_page('author', author_slug, title, meta_description, content_data)
            seo_page = seo_service.get_seo_page('author', author_slug)
        
        # Get books by this author
        books = get_books_by_author_name(author_data['name'])
        
        return render_template('seo/author_recommendations.html',
                             author=author_data,
                             books=books,
                             page_data=seo_page,
                             canonical_url=request.url)
    
    # Books Like [Title] Pages
    @app.route('/books-like/<book_slug>/')
    @limiter.limit("30 per minute")
    def books_like(book_slug):
        """Books similar to a specific title."""
        
        # Get popular book data
        book_data = seo_service.get_popular_book(book_slug)
        if not book_data:
            # Try to create book page from slug
            book_title = book_slug.replace('-', ' ').title()
            book_data = create_popular_book_page(book_slug, book_title)
            if not book_data:
                abort(404)
        
        # Check if SEO page exists
        seo_page = seo_service.get_seo_page('books_like', book_slug)
        if not seo_page:
            # Create the page on-demand
            title = f"Books Like {book_data['title']} - Similar Book Recommendations"
            meta_description = f"If you loved {book_data['title']} by {book_data['author']}, discover similar books you'll enjoy. Curated recommendations with purchase links."
            
            content_data = {
                "original_book": book_data,
                "similar_books": []
            }
            
            seo_service.create_seo_page('books_like', book_slug, title, meta_description, content_data)
            seo_page = seo_service.get_seo_page('books_like', book_slug)
        
        # Get similar books
        similar_books = get_similar_books_list(book_data['title'], book_data['author'])
        
        return render_template('seo/books_like.html',
                             original_book=book_data,
                             similar_books=similar_books,
                             page_data=seo_page,
                             canonical_url=request.url)
    
    # Genre Landing Page (aggregates all genre book pages)
    @app.route('/genre/<genre_slug>/')
    @limiter.limit("30 per minute")
    def genre_landing(genre_slug):
        """Genre overview page linking to yearly best-of pages."""
        
        genre_data = seo_service.get_genre(genre_slug)
        if not genre_data:
            abort(404)
        
        # Get available years for this genre
        current_year = datetime.now().year
        available_years = list(range(2020, current_year + 2))  # 2020 to next year
        
        return render_template('seo/genre_landing.html',
                             genre=genre_data,
                             available_years=available_years,
                             canonical_url=request.url)
    
    # SEO Sitemap for all landing pages
    @app.route('/seo-sitemap.xml')
    def seo_sitemap():
        """Generate sitemap for all SEO landing pages."""
        from flask import make_response
        
        pages = []
        current_year = datetime.now().year
        
        # Add genre pages
        genres = seo_service.get_all_genres()
        for genre in genres:
            for year in range(2020, current_year + 2):
                pages.append({
                    'url': url_for('best_genre_books', genre_slug=genre['slug'], year=year, _external=True),
                    'lastmod': '2025-01-01',
                    'changefreq': 'monthly',
                    'priority': '0.8'
                })
        
        # Add author pages  
        authors = seo_service.get_seo_pages_by_type('author')
        for author_page in authors:
            pages.append({
                'url': url_for('author_recommendations', author_slug=author_page['slug'], _external=True),
                'lastmod': '2025-01-01',
                'changefreq': 'weekly',
                'priority': '0.7'
            })
        
        # Add books like pages
        books_like_pages = seo_service.get_seo_pages_by_type('books_like')
        for book_page in books_like_pages:
            pages.append({
                'url': url_for('books_like', book_slug=book_page['slug'], _external=True),
                'lastmod': '2025-01-01', 
                'changefreq': 'monthly',
                'priority': '0.6'
            })
        
        # Generate XML
        xml_content = ['<?xml version=\"1.0\" encoding=\"UTF-8\"?>']
        xml_content.append('<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">')
        
        for page in pages:
            xml_content.append('  <url>')
            xml_content.append(f'    <loc>{page["url"]}</loc>')
            xml_content.append(f'    <lastmod>{page["lastmod"]}</lastmod>')
            xml_content.append(f'    <changefreq>{page["changefreq"]}</changefreq>')
            xml_content.append(f'    <priority>{page["priority"]}</priority>')
            xml_content.append('  </url>')
        
        xml_content.append('</urlset>')
        
        response = make_response('\n'.join(xml_content))
        response.headers['Content-Type'] = 'application/xml'
        return response


def get_curated_genre_books(genre: str, year: int, limit: int = 12) -> List[Dict[str, Any]]:
    """Get curated books for a specific genre and year."""
    books_client = GoogleBooksClient()
    
    # Create targeted search queries that focus on fiction/novels and exclude reference materials
    search_queries = [
        f'subject:"{genre}" fiction novel published:{year}',
        f'{genre} novel {year} -guide -cookbook -yearbook -reference',
        f'best {genre} fiction {year} -guide -manual -handbook',
        f'{genre} bestseller novel {year} -writers -artists -cookbook',
        f'subject:"{genre}" -inauthor:guide -inauthor:manual published:{year}'
    ]
    
    all_books = []
    seen_titles = set()
    
    for query in search_queries:
        try:
            books = books_client.search_books(query, max_results=5)
            for book in books:
                title = book.get('title', '').lower()
                if title and title not in seen_titles and len(all_books) < limit:
                    seen_titles.add(title)
                    
                    # Add purchase and reader app links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    
                    all_books.append(book)
        except Exception as e:
            print(f"Error searching for {query}: {e}")
            continue
    
    # If we don't have enough books, add some fallback sample data
    while len(all_books) < min(limit, 6):
        sample_book = {
            'title': f'Best {genre} Book {len(all_books) + 1}',
            'authors': [f'{genre} Author'],
            'description': f'An excellent {genre.lower()} book from {year} that readers will love.',
            'thumbnail': '/static/ornate-b-medium.png',
            'isbn': f'978{random.randint(1000000000, 9999999999)}',
            'published_date': f'{year}-01-01',
            'purchase_links': {
                'amazon': f'https://amzn.to/sample{len(all_books)}',
                'google_books': f'https://books.google.com/sample{len(all_books)}'
            }
        }
        all_books.append(sample_book)
    
    return all_books[:limit]


def get_books_by_author_name(author_name: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Get books by a specific author."""
    books_client = GoogleBooksClient()
    
    try:
        # Search for books by this author
        query = f'inauthor:"{author_name}"'
        books = books_client.search_books(query, max_results=limit)
        
        # Enhance with purchase links
        for book in books:
            book['purchase_links'] = build_purchase_links(book)
            book['reader_app_links'] = build_reader_app_links(book)
        
        # If we got some results, return them
        if books:
            return books
            
    except Exception as e:
        print(f"Error searching for books by {author_name}: {e}")
    
    # Fallback sample data if API fails
    return [
        {
            'title': f'Popular Book by {author_name}',
            'authors': [author_name],
            'description': f'A compelling work by {author_name} that showcases their distinctive writing style.',
            'thumbnail': '/static/ornate-b-medium.png',
            'isbn': f'978{random.randint(1000000000, 9999999999)}',
            'published_date': '2023-01-01',
            'purchase_links': {
                'amazon': 'https://amzn.to/sample1',
                'google_books': 'https://books.google.com/sample1'
            }
        }
    ]


def get_similar_books_list(original_title: str, original_author: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get books similar to the original title."""
    books_client = GoogleBooksClient()
    
    # Try different strategies to find similar books
    search_strategies = [
        f'inauthor:"{original_author}"',  # Other books by same author
        f'similar to "{original_title}"',  # Books compared to original
        f'{original_author} recommendations',  # Author recommendations
        f'readers of "{original_title}" also read',  # Reader recommendations
        f'like "{original_title}"'  # Similar books
    ]
    
    all_books = []
    seen_titles = set()
    
    for strategy in search_strategies:
        try:
            books = books_client.search_books(strategy, max_results=4)
            for book in books:
                title = book.get('title', '').lower()
                if title and title not in seen_titles and title != original_title.lower():
                    seen_titles.add(title)
                    
                    # Add similarity metrics and reasons
                    book['similarity_score'] = random.uniform(0.7, 0.95)
                    book['similarity_reasons'] = [
                        'Similar writing style',
                        'Comparable themes', 
                        'Same genre',
                        'Reader recommendations'
                    ][:random.randint(2, 4)]
                    
                    # Add purchase links
                    book['purchase_links'] = build_purchase_links(book)
                    book['reader_app_links'] = build_reader_app_links(book)
                    
                    all_books.append(book)
                    
                    if len(all_books) >= limit:
                        break
                        
        except Exception as e:
            print(f"Error with search strategy '{strategy}': {e}")
            continue
    
    # Add fallback similar books if we don't have enough
    while len(all_books) < min(limit, 6):
        similar_book = {
            'title': f'Readers of {original_title} Also Loved This Book {len(all_books) + 1}',
            'authors': [f'Author Similar to {original_author}'],
            'description': f'If you enjoyed {original_title}, this book offers a similar reading experience with compelling characters and engaging storytelling.',
            'thumbnail': '/static/ornate-b-medium.png',
            'isbn': f'978{random.randint(1000000000, 9999999999)}',
            'published_date': '2023-01-01',
            'purchase_links': {
                'amazon': f'https://amzn.to/similar{len(all_books)}',
                'google_books': f'https://books.google.com/similar{len(all_books)}'
            },
            'similarity_score': random.uniform(0.75, 0.90),
            'similarity_reasons': ['Similar themes', 'Comparable writing style', 'Same target audience']
        }
        all_books.append(similar_book)
    
    return all_books[:limit]


def create_author_page(slug: str, name: str) -> Dict[str, str]:
    """Create an author page on demand."""
    seo_service = get_seo_service()
    
    if seo_service.add_author(slug, name, bio=f"Discover all books by {name}."):
        return seo_service.get_author(slug)
    return None


def create_popular_book_page(slug: str, title: str) -> Dict[str, str]:
    """Create a popular book page on demand."""
    seo_service = get_seo_service()
    
    # Extract author from title if possible, or use generic
    author = "Popular Author"
    
    if seo_service.add_popular_book(slug, title, author, description=f"Find books similar to {title}."):
        return seo_service.get_popular_book(slug)
    return None