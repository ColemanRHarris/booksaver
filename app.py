"""
Main Flask application for BookSaver.
Streamlined version with modular structure.
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import logging
from logging.config import dictConfig

from services.books_client import GoogleBooksClient
from celery_app import celery_app
from services.recommendation_engine import get_recommendation_engine
from system_monitor import get_system_monitor
from core.utils import sanitize_input, validate_search_query, serialize_task_result, safe_get_task_result
from routes.video import register_video_routes

load_dotenv()


class SSLErrorFilter(logging.Filter):
    """Filter out SSL handshake errors on HTTP server"""
    def filter(self, record):
        message = record.getMessage()
        ssl_error_patterns = [
            'Bad HTTP/0.9 request type',
            'Bad request version', 
            '\\x16\\x03\\x01',  # TLS handshake
            'code 400, message Bad'
        ]
        return not any(pattern in message for pattern in ssl_error_patterns)


# Configure logging
log_level = 'INFO' if os.getenv('FLASK_ENV') == 'production' else 'DEBUG'
dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'filters': {'ssl_filter': {
        '()': SSLErrorFilter,
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default',
        'filters': ['ssl_filter']
    }},
    'root': {
        'level': log_level,
        'handlers': ['wsgi']
    }
})


# Create Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
logger = logging.getLogger(__name__)


def log_environment_status():
    """Log the status of important environment variables"""
    env_vars = {
        'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
        'REDIS_URL': os.getenv('REDIS_URL'), 
        'SECRET_KEY': os.getenv('SECRET_KEY'),
        'FLASK_ENV': os.getenv('FLASK_ENV'),
        'GOOGLE_BOOKS_KEY': os.getenv('GOOGLE_BOOKS_KEY'),
        'PORT': os.getenv('PORT')
    }
    
    logger.info("🔐 Environment Variables Status:")
    for var_name, var_value in env_vars.items():
        if var_value:
            if 'KEY' in var_name and len(var_value) > 8:
                display_value = f"{var_value[:4]}...{var_value[-4:]}"
            else:
                display_value = var_value
            logger.info(f"   ✅ {var_name}: {display_value}")
        else:
            logger.warning(f"   ⚠️  {var_name}: NOT SET")


# Log environment status
log_environment_status()

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Configure CSRF for development
if os.getenv('FLASK_ENV') != 'production':
    app.config['WTF_CSRF_TIME_LIMIT'] = None
    app.config['WTF_CSRF_SSL_STRICT'] = False

# Initialize rate limiter
redis_url = os.getenv('REDIS_URL')
if redis_url and not redis_url.startswith('memory://'):
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["100 per hour", "20 per minute"],
        storage_uri=redis_url,
        strategy="fixed-window"
    )
    print(f"🔗 Flask-Limiter using Redis: {redis_url[:50]}...")
else:
    limiter = Limiter(
        app=app,
        key_func=get_remote_address,
        default_limits=["100 per hour", "20 per minute"],
        strategy="fixed-window"
    )
    print("🔧 Flask-Limiter using in-memory storage for local development")


# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Only add HSTS in production with HTTPS
    if os.getenv('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Content Security Policy
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com https://www.googletagmanager.com; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "font-src 'self' https:; "
        "connect-src 'self' https:; "
        "frame-src https://googleads.g.doubleclick.net; "
        "object-src 'none'"
    )
    response.headers['Content-Security-Policy'] = csp
    
    return response


# Register route modules
register_video_routes(app, limiter)


# Main routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/health')
@limiter.exempt
def health_check():
    """Simple health check endpoint"""
    try:
        # Test database/Redis connection if needed
        system_monitor = get_system_monitor()
        stats = system_monitor.get_stats()
        
        # Basic health indicators
        health_status = {
            'status': 'healthy',
            'uptime_seconds': stats.get('uptime_seconds', 0),
            'memory_usage_mb': stats.get('memory_usage_mb', 0),
            'cpu_usage_percent': stats.get('cpu_usage_percent', 0)
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/search', methods=['POST'])
@limiter.limit("30 per minute")
def search():
    """Search for books using Google Books API"""
    try:
        raw_query = request.form.get('query', '').strip()
        query = validate_search_query(raw_query)
        
        # Initialize Google Books client
        books_client = GoogleBooksClient()
        
        # Search for books
        books = books_client.search_books(query, max_results=10)
        
        if not books:
            return render_template('results.html', 
                                 books=[], 
                                 query=query,
                                 error="No books found for your search. Try different keywords or check spelling.")
        
        logger.info(f"✅ Search completed: {len(books)} books found for '{query}'")
        return render_template('results.html', books=books, query=query)
        
    except ValueError as e:
        return render_template('index.html', error=str(e))
    except Exception as e:
        logger.error(f"❌ Search error: {e}")
        return render_template('index.html', error="Search failed. Please try again.")


@app.route('/processing/<task_id>')
def processing_wait(task_id):
    """Show processing page with progress updates"""
    video_url = request.args.get('url', '')
    video_type = request.args.get('type', 'Video')
    return render_template('processing.html', task_id=task_id, video_url=video_url, video_type=video_type)


@app.route('/task-status/<task_id>')
@limiter.limit("30 per minute")
def task_status(task_id):
    """Get the status of a background task"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        # Check if we're using actual Redis (not memory:// for local dev)
        if redis_url and not redis_url.startswith('memory://'):
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'PENDING':
                response = {
                    'state': task.state,
                    'result': {'step': 'Waiting to start...', 'progress': 0}
                }
            elif task.state == 'PROGRESS':
                response = {
                    'state': task.state,
                    'result': serialize_task_result(task.result)
                }
            elif task.state == 'SUCCESS':
                print(f"🎯 Task {task_id} completed successfully")
                print(f"📋 Task result: {task.result}")
                
                response = {
                    'state': task.state,
                    'result': serialize_task_result(task.result),
                    'redirect': True
                }
            else:  # FAILURE
                print(f"❌ Task {task_id} failed: {task.result}")
                response = {
                    'state': task.state,
                    'result': serialize_task_result(task.result)
                }
        else:
            if task_id not in app.task_results:
                return jsonify({
                    'state': 'PENDING',
                    'result': {'step': 'Task not found...', 'progress': 0}
                })
            
            task_data = app.task_results[task_id]
            
            if task_data['state'] == 'PENDING':
                response = {
                    'state': 'PENDING',
                    'result': {
                        'step': task_data.get('step', 'Waiting to start...'),
                        'progress': task_data.get('progress', 0)
                    }
                }
            elif task_data['state'] == 'PROGRESS':
                response = {
                    'state': 'PROGRESS',
                    'result': {
                        'step': task_data.get('step', 'Processing...'),
                        'progress': task_data.get('progress', 50)
                    }
                }
            elif task_data['state'] == 'SUCCESS':
                response = {
                    'state': 'SUCCESS',
                    'result': task_data.get('result', {}),
                    'redirect': True
                }
            else:  # FAILURE
                response = {
                    'state': 'FAILURE',
                    'result': {
                        'error': task_data.get('error', 'Unknown error occurred')
                    }
                }
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"❌ Task status error: {e}")
        return jsonify({
            'state': 'FAILURE',
            'result': {'error': 'Unable to check task status'}
        }), 500


@app.route('/cancel-task/<task_id>', methods=['POST'])
@limiter.limit("10 per minute")
def cancel_task(task_id):
    """Cancel a running task"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        # Check if we're using actual Redis (not memory:// for local dev)
        if redis_url and not redis_url.startswith('memory://'):
            celery_app.control.revoke(task_id, terminate=True)
            message = f"Task {task_id} has been cancelled"
        else:
            if task_id in app.task_results:
                app.task_results[task_id] = {
                    'state': 'REVOKED',
                    'error': 'Task was cancelled by user'
                }
                message = f"Task {task_id} has been cancelled"
            else:
                message = f"Task {task_id} not found"
        
        return jsonify({'message': message}), 200
        
    except Exception as e:
        logger.error(f"❌ Cancel task error: {e}")
        return jsonify({'error': 'Failed to cancel task'}), 500


@app.route('/tiktok-results/<task_id>')
def tiktok_results(task_id):
    """Show results from completed video processing"""
    try:
        redis_url = os.getenv('REDIS_URL')
        video_url = request.args.get('url', '')
        video_type = request.args.get('type', 'Video')
        
        # Check if we're using actual Redis (not memory:// for local dev)
        if redis_url and not redis_url.startswith('memory://'):
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'SUCCESS' and safe_get_task_result(task.result, 'status') == 'success':
                books = safe_get_task_result(task.result, 'books', [])
                
                if not books:
                    return render_template('results.html', 
                                         books=[], 
                                         query=f"{video_type} analysis",
                                         error="No books were detected in this video. Try with a different video that shows book covers more clearly.")
                
                return render_template('results.html', 
                                     books=books, 
                                     query=f"{video_type} analysis",
                                     video_url=video_url)
            else:
                error_msg = safe_get_task_result(task.result, 'error', 'Task failed or is still processing')
                return render_template('results.html', 
                                     books=[], 
                                     query=f"{video_type} analysis",
                                     error=error_msg)
        else:
            if task_id in app.task_results:
                task_data = app.task_results[task_id]
                
                if task_data['state'] == 'SUCCESS' and 'result' in task_data:
                    books = task_data['result'].get('books', [])
                    
                    if not books:
                        return render_template('results.html', 
                                             books=[], 
                                             query=f"{video_type} analysis",
                                             error="No books were detected in this video.")
                    
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{video_type} analysis",
                                         video_url=video_url)
                else:
                    error_msg = task_data.get('error', 'Task failed or is still processing')
                    return render_template('results.html', 
                                         books=[], 
                                         query=f"{video_type} analysis",
                                         error=error_msg)
            else:
                return render_template('results.html', 
                                     books=[], 
                                     query=f"{video_type} analysis",
                                     error="Task not found or expired")
                
    except Exception as e:
        logger.error(f"❌ Results error: {e}")
        return render_template('results.html', 
                             books=[], 
                             query=f"{video_type} analysis",
                             error="Failed to load results")


# Static content routes
@app.route('/recommendations')
def recommendations():
    """Show curated book recommendations"""
    try:
        # Get curated recommendations (could be from a file, database, or API)
        recommended_books = get_curated_recommendations()
        
        return render_template('recommendations.html', books=recommended_books)
        
    except Exception as e:
        logger.error(f"❌ Recommendations error: {e}")
        return render_template('recommendations.html', books=[], error="Failed to load recommendations")


@app.route('/terms')
def terms():
    """Terms of service page"""
    return render_template('terms.html')


@app.route('/privacy')
def privacy():
    """Privacy policy page"""
    return render_template('privacy.html')


@app.route('/ads.txt')
def ads_txt():
    """Google AdSense ads.txt file"""
    return app.send_static_file('ads.txt')


@app.route('/site.webmanifest')
def site_webmanifest():
    return app.send_static_file('site.webmanifest')


@app.route('/favicon.ico')
def favicon():
    return app.send_static_file('favicon.png')


def get_curated_recommendations():
    """Get curated book recommendations"""
    # This could be replaced with database queries or external API calls
    return [
        {
            'title': 'Fourth Wing',
            'authors': ['Rebecca Yarros'],
            'description': 'A fantasy romance that took BookTok by storm.',
            'average_rating': 4.5,
            'ratings_count': 50000,
            'thumbnail': 'https://via.placeholder.com/128x192',
            'amazon_link': '#',
            'google_books_link': '#'
        },
        # Add more curated books...
    ]


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(os.getenv('FLASK_ENV') != 'production'))