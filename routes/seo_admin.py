"""
SEO Admin interface for managing parasite SEO content.
Protected routes for managing genres, authors, and SEO pages.
"""

from flask import render_template, request, redirect, url_for, flash, jsonify
from services.seo_service import get_seo_service
from datetime import datetime
from typing import Dict, Any


def register_seo_admin_routes(app, limiter, require_admin):
    """Register SEO admin routes."""
    
    seo_service = get_seo_service()
    
    @app.route('/admin/seo')
    @require_admin
    @limiter.limit("10 per minute")
    def seo_admin_dashboard():
        """SEO admin dashboard."""
        stats = seo_service.get_seo_stats()
        genres = seo_service.get_all_genres()
        popular_books = seo_service.get_all_popular_books()
        
        return render_template('admin/seo_dashboard.html',
                             stats=stats,
                             genres=genres,
                             popular_books=popular_books)
    
    @app.route('/admin/seo/genres')
    @require_admin 
    @limiter.limit("10 per minute")
    def seo_admin_genres():
        """Manage genres."""
        genres = seo_service.get_all_genres()
        return render_template('admin/seo_genres.html', genres=genres)
    
    @app.route('/admin/seo/genres/add', methods=['POST'])
    @require_admin
    @limiter.limit("5 per minute")
    def add_genre():
        """Add a new genre."""
        name = request.form.get('name', '').strip()
        if not name:
            flash('Genre name is required', 'error')
            return redirect(url_for('seo_admin_genres'))
        
        slug = seo_service.slugify(name)
        
        if seo_service.add_genre(slug, name):
            flash(f'Genre "{name}" added successfully', 'success')
        else:
            flash('Failed to add genre', 'error')
        
        return redirect(url_for('seo_admin_genres'))
    
    @app.route('/admin/seo/books')
    @require_admin
    @limiter.limit("10 per minute") 
    def seo_admin_books():
        """Manage popular books."""
        books = seo_service.get_all_popular_books()
        return render_template('admin/seo_books.html', books=books)
    
    @app.route('/admin/seo/books/add', methods=['POST'])
    @require_admin
    @limiter.limit("5 per minute")
    def add_popular_book():
        """Add a new popular book."""
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        description = request.form.get('description', '').strip()
        
        if not title or not author:
            flash('Title and author are required', 'error')
            return redirect(url_for('seo_admin_books'))
        
        slug = seo_service.slugify(title)
        
        if seo_service.add_popular_book(slug, title, author, description):
            flash(f'Book "{title}" added successfully', 'success')
        else:
            flash('Failed to add book', 'error')
        
        return redirect(url_for('seo_admin_books'))
    
    @app.route('/admin/seo/authors')
    @require_admin
    @limiter.limit("10 per minute")
    def seo_admin_authors():
        """Manage authors."""
        # Get all author pages created
        author_pages = seo_service.get_seo_pages_by_type('author')
        return render_template('admin/seo_authors.html', author_pages=author_pages)
    
    @app.route('/admin/seo/authors/add', methods=['POST'])
    @require_admin
    @limiter.limit("5 per minute")
    def add_author():
        """Add a new author."""
        name = request.form.get('name', '').strip()
        bio = request.form.get('bio', '').strip()
        image_url = request.form.get('image_url', '').strip()
        
        if not name:
            flash('Author name is required', 'error')
            return redirect(url_for('seo_admin_authors'))
        
        slug = seo_service.slugify(name)
        
        if seo_service.add_author(slug, name, bio, image_url):
            flash(f'Author "{name}" added successfully', 'success')
        else:
            flash('Failed to add author', 'error')
        
        return redirect(url_for('seo_admin_authors'))
    
    @app.route('/admin/seo/pages')
    @require_admin
    @limiter.limit("10 per minute")
    def seo_admin_pages():
        """View all SEO pages."""
        genre_pages = seo_service.get_seo_pages_by_type('genre')
        author_pages = seo_service.get_seo_pages_by_type('author') 
        books_like_pages = seo_service.get_seo_pages_by_type('books_like')
        
        return render_template('admin/seo_pages.html',
                             genre_pages=genre_pages,
                             author_pages=author_pages,
                             books_like_pages=books_like_pages)
    
    @app.route('/admin/seo/generate-content', methods=['POST'])
    @require_admin
    @limiter.limit("2 per minute")
    def generate_seo_content():
        """Generate SEO content for current year."""
        current_year = datetime.now().year
        content_type = request.form.get('type', 'genre')
        
        if content_type == 'genre':
            # Generate pages for all genres for current year
            genres = seo_service.get_all_genres()
            created_count = 0
            
            for genre in genres:
                page_slug = f"{genre['slug']}-{current_year}"
                
                # Check if page already exists
                if not seo_service.get_seo_page('genre', page_slug):
                    title = f"Best {genre['display_name']} Books {current_year}"
                    meta_description = f"Discover the best {genre['display_name'].lower()} books of {current_year}. Curated recommendations with purchase links and reading app integration."
                    
                    content_data = {
                        "genre": genre['display_name'],
                        "year": current_year,
                        "books": []
                    }
                    
                    if seo_service.create_seo_page('genre', page_slug, title, meta_description, content_data):
                        created_count += 1
            
            flash(f'Generated {created_count} genre pages for {current_year}', 'success')
        
        elif content_type == 'popular_books':
            # Generate 'books like' pages for all popular books
            books = seo_service.get_all_popular_books()
            created_count = 0
            
            for book in books:
                # Check if page already exists
                if not seo_service.get_seo_page('books_like', book['slug']):
                    title = f"Books Like {book['title']} - Similar Book Recommendations"
                    meta_description = f"If you loved {book['title']} by {book['author']}, discover similar books you'll enjoy. Curated recommendations with purchase links."
                    
                    content_data = {
                        "original_book": book,
                        "similar_books": []
                    }
                    
                    if seo_service.create_seo_page('books_like', book['slug'], title, meta_description, content_data):
                        created_count += 1
            
            flash(f'Generated {created_count} "books like" pages', 'success')
        
        return redirect(url_for('seo_admin_dashboard'))
    
    @app.route('/admin/seo/api/stats')
    @require_admin
    @limiter.limit("30 per minute")
    def seo_api_stats():
        """API endpoint for SEO stats."""
        stats = seo_service.get_seo_stats()
        return jsonify(stats)
    
    @app.route('/admin/seo/preview/<page_type>/<slug>')
    @require_admin
    @limiter.limit("20 per minute")
    def preview_seo_page(page_type, slug):
        """Preview an SEO page."""
        if page_type == 'genre':
            # Extract year from slug if present
            parts = slug.split('-')
            if parts[-1].isdigit():
                year = int(parts[-1])
                genre_slug = '-'.join(parts[:-1])
                return redirect(url_for('best_genre_books', genre_slug=genre_slug, year=year))
            else:
                return redirect(url_for('genre_landing', genre_slug=slug))
                
        elif page_type == 'author':
            return redirect(url_for('author_recommendations', author_slug=slug))
            
        elif page_type == 'books_like':
            return redirect(url_for('books_like', book_slug=slug))
        
        else:
            flash('Invalid page type', 'error')
            return redirect(url_for('seo_admin_pages'))