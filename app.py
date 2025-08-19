from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from dotenv import load_dotenv
import os
import threading
import uuid
import time
import logging
from logging.config import dictConfig
from urllib.parse import urlparse
import html
import re
from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from celery_app import celery_app
from tasks import process_video

load_dotenv()

# Configure logging based on environment
log_level = 'INFO' if os.getenv('FLASK_ENV') == 'production' else 'DEBUG'

class SSLErrorFilter(logging.Filter):
    """Filter out SSL handshake errors on HTTP server"""
    def filter(self, record):
        message = record.getMessage()
        # Filter out SSL/TLS handshake errors - all variations
        ssl_error_patterns = [
            'Bad HTTP/0.9 request type',
            'Bad request version',
            '\\x16\\x03\\x01',  # TLS handshake
            'code 400, message Bad'
        ]
        return not any(pattern in message for pattern in ssl_error_patterns)

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

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
logger = logging.getLogger(__name__)

# Initialize CSRF protection
csrf = CSRFProtect(app)

# Configure CSRF for development
if os.getenv('FLASK_ENV') != 'production':
    app.config['WTF_CSRF_TIME_LIMIT'] = None  # No time limit in development
    app.config['WTF_CSRF_SSL_STRICT'] = False  # Allow HTTP in development

# Initialize rate limiter
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "20 per minute"],
    storage_uri=os.getenv('REDIS_URL', 'memory://'),
    strategy="fixed-window"
)

# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Content Security Policy - allowing local development
    if os.getenv('FLASK_ENV') == 'production':
        # Production CSP - more restrictive
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com https://googleads.g.doubleclick.net",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "img-src 'self' data: https://pagead2.googlesyndication.com https://tpc.googlesyndication.com",
            "font-src 'self' https://fonts.gstatic.com",
            "connect-src 'self' https://pagead2.googlesyndication.com",
            "frame-src https://googleads.g.doubleclick.net",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'"
        ]
        if request.is_secure:
            csp_directives.append("upgrade-insecure-requests")
    else:
        # Development CSP - more permissive for local development
        csp_directives = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://pagead2.googlesyndication.com",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: https:",
            "font-src 'self'",
            "connect-src 'self'",
            "frame-src 'none'",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'"
        ]
    
    csp_policy = "; ".join(csp_directives)
    response.headers['Content-Security-Policy'] = csp_policy
    
    # Only add HSTS in production over HTTPS
    if os.getenv('FLASK_ENV') == 'production' and request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    return response

books_client = GoogleBooksClient()

# Simple in-memory task tracking
task_results = {}

def validate_url(url: str, allowed_domains: list) -> bool:
    """Validate URL format and check if domain is allowed"""
    try:
        parsed = urlparse(url.lower().strip())
        
        # Check if URL has proper scheme and netloc
        if not parsed.scheme or not parsed.netloc:
            return False
        
        # Only allow HTTP/HTTPS
        if parsed.scheme not in ['http', 'https']:
            return False
        
        # Check if domain is in allowed list
        domain = parsed.netloc
        # Remove 'www.' prefix for comparison
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return any(allowed_domain in domain for allowed_domain in allowed_domains)
    
    except Exception:
        return False

def sanitize_input(input_str: str, max_length: int = 500) -> str:
    """Sanitize user input to prevent XSS and limit length"""
    if not input_str:
        return ""
    
    # Limit length
    input_str = input_str[:max_length]
    
    # Strip whitespace
    input_str = input_str.strip()
    
    # HTML escape to prevent XSS
    input_str = html.escape(input_str, quote=True)
    
    # Remove or replace potentially dangerous characters
    # Allow only alphanumeric, spaces, hyphens, periods, colons, slashes, underscores, and question marks
    input_str = re.sub(r'[^\w\s\-\.\:\/\?#&=]', '', input_str)
    
    return input_str

def validate_search_query(query: str) -> str:
    """Validate and sanitize book search query"""
    if not query:
        return ""
    
    # More permissive sanitization for search queries
    query = query.strip()[:200]  # Limit to 200 chars
    
    # HTML escape but allow more characters for book titles
    query = html.escape(query, quote=True)
    
    # Allow letters, numbers, spaces, common punctuation
    query = re.sub(r'[^\w\s\-\.\,\:\!\?\&\'\"]', '', query)
    
    return query

def process_video_background(task_id: str, video_url: str, video_type: str):
    """Process video (TikTok/Reel) in background thread for local development"""
    try:
        task_results[task_id] = {
            'state': 'PROGRESS',
            'progress': 10,
            'step': 'Starting processing...'
        }
        
        time.sleep(2)
        
        task_results[task_id] = {
            'state': 'PROGRESS', 
            'progress': 30,
            'step': f'Processing {video_type} video...'
        }
        
        # Call the actual processing function directly
        from tasks import process_video
        result = process_video.apply(args=[video_url, video_type]).result
        
        task_results[task_id] = {
            'state': 'SUCCESS',
            'result': result
        }
        
    except Exception as e:
        # Log detailed error server-side but show generic message to user
        logger.error(f"Error processing video in background: {str(e)}", exc_info=True)
        task_results[task_id] = {
            'state': 'FAILURE',
            'result': {'error': 'Video processing failed. Please try again with a different video.'}
        }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health_check():
    """Health check endpoint for monitoring"""
    try:
        redis_url = os.getenv('REDIS_URL')
        status = {
            'status': 'healthy',
            'timestamp': time.time(),
            'environment': 'production' if redis_url else 'development',
            'services': {
                'web': 'running',
                'redis': 'connected' if redis_url else 'local',
                'books_api': 'available'
            }
        }
        
        # Check if Google Books API key is available (don't make actual request)
        api_key = os.getenv('GOOGLE_BOOKS_KEY')
        if api_key:
            status['services']['books_api'] = 'configured'
        else:
            status['services']['books_api'] = 'public_only'
            
        return jsonify(status), 200
    except Exception as e:
        # Log detailed error but return generic message
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'error': 'Service temporarily unavailable',
            'timestamp': time.time()
        }), 500

@app.route('/search', methods=['POST'])
@limiter.limit("10 per minute")
def search():
    raw_query = request.form.get('query', '')
    query = validate_search_query(raw_query)
    
    if not query:
        return render_template('index.html', error="Please enter a valid book title or ISBN")
    
    try:
        books = books_client.search_books(query)
        
        # Add purchase and reader app links to each book
        for book in books:
            book['purchase_links'] = build_purchase_links(book)
            book['reader_app_links'] = build_reader_app_links(book)
            book['amazon_link'] = build_amazon_link(book)  # Keep for backward compatibility
        
        if not books:
            return render_template('results.html', books=[], query=query, 
                                 error="No books found for your search. Try a different title or ISBN.")
        
        return render_template('results.html', books=books, query=query)
        
    except ValueError as e:
        # Log detailed error but show generic message
        logger.error(f"Configuration error during search: {str(e)}", exc_info=True)
        return render_template('index.html', error="Service configuration issue. Please try again later.")
    except Exception as e:
        # Log detailed error but show generic message  
        logger.error(f"Unexpected error during search: {str(e)}", exc_info=True)
        return render_template('index.html', error="Something went wrong. Please try again later.")

@app.route('/process-tiktok', methods=['POST'])
@limiter.limit("5 per hour")  # More restrictive for video processing
def process_tiktok():
    raw_url = request.form.get('tiktok_url', '')
    tiktok_url = sanitize_input(raw_url, max_length=500)
    
    if not tiktok_url:
        return render_template('index.html', error="Please enter a TikTok URL")
    
    # Proper URL validation
    allowed_domains = ['tiktok.com', 'vm.tiktok.com']
    if not validate_url(tiktok_url, allowed_domains):
        return render_template('index.html', error="Please enter a valid TikTok URL")
    
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            # Production: Use Celery with Redis
            task = process_video.delay(tiktok_url, 'tiktok')
            task_id = task.id
        else:
            # Local development: Use threading
            task_id = str(uuid.uuid4())
            
            task_results[task_id] = {
                'state': 'PENDING',
                'progress': 0,
                'step': 'Waiting to start...'
            }
            
            thread = threading.Thread(
                target=process_video_background,
                args=(task_id, tiktok_url, 'tiktok')
            )
            thread.daemon = True
            thread.start()
        
        return redirect(url_for('processing_wait', task_id=task_id, url=tiktok_url, type='tiktok'))
        
    except Exception as e:
        # Log detailed error but show generic message
        logger.error(f"Failed to start TikTok processing: {str(e)}", exc_info=True)
        return render_template('index.html', error="Failed to start video processing. Please try again.")

@app.route('/process-instagram-reel', methods=['POST'])
@limiter.limit("5 per hour")  # More restrictive for video processing
def process_instagram_reel():
    raw_url = request.form.get('reel_url', '')
    reel_url = sanitize_input(raw_url, max_length=500)
    
    if not reel_url:
        return render_template('index.html', error="Please enter an Instagram Reel URL")
    
    # Proper URL validation with path checking for reels
    allowed_domains = ['instagram.com', 'instagr.am']
    if not validate_url(reel_url, allowed_domains):
        return render_template('index.html', error="Please enter a valid Instagram Reel URL")
    
    # Additional check for reel path
    parsed = urlparse(reel_url.lower())
    if '/reel/' not in parsed.path:
        return render_template('index.html', error="Please enter a valid Instagram Reel URL (must contain /reel/)")
    
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            task = process_video.delay(reel_url, 'instagram')
            task_id = task.id
        else:
            task_id = str(uuid.uuid4())
            
            task_results[task_id] = {
                'state': 'PENDING',
                'progress': 0,
                'step': 'Waiting to start...'
            }
            
            thread = threading.Thread(
                target=process_video_background,
                args=(task_id, reel_url, 'instagram')
            )
            thread.daemon = True
            thread.start()
        
        return redirect(url_for('processing_wait', task_id=task_id, url=reel_url, type='instagram'))
        
    except Exception as e:
        # Log detailed error but show generic message
        logger.error(f"Failed to start Instagram processing: {str(e)}", exc_info=True)
        return render_template('index.html', error="Failed to start video processing. Please try again.")

@app.route('/processing/<task_id>')
def processing_wait(task_id):
    """Show waiting page while video is being processed"""
    video_url = request.args.get('url', '')
    video_type = request.args.get('type', 'Video')
    return render_template('processing.html', task_id=task_id, video_url=video_url, video_type=video_type)

@app.route('/task-status/<task_id>')
@limiter.limit("30 per minute")  # Allow frequent polling for status
def task_status(task_id):
    """Get the status of a background task"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'PENDING':
                response = {
                    'state': task.state,
                    'result': {'step': 'Waiting to start...', 'progress': 0}
                }
            elif task.state == 'PROGRESS':
                response = {
                    'state': task.state,
                    'result': task.result
                }
            elif task.state == 'SUCCESS':
                print(f"🎯 Task {task_id} completed successfully")
                print(f"📋 Task result: {task.result}")
                
                response = {
                    'state': task.state,
                    'result': task.result,
                    'redirect': True
                }
            else:  # FAILURE
                print(f"❌ Task {task_id} failed: {task.result}")
                response = {
                    'state': task.state,
                    'result': {'error': str(task.result)}
                }
        else:
            if task_id not in task_results:
                return jsonify({
                    'state': 'PENDING',
                    'result': {'step': 'Task not found...', 'progress': 0}
                })
            
            task_data = task_results[task_id]
            
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
                        'progress': task_data.get('progress', 0)
                    }
                }
            elif task_data['state'] == 'SUCCESS':
                print(f"🎯 Task {task_id} completed successfully")
                print(f"📋 Task result: {task_data['result']}")
                
                response = {
                    'state': 'SUCCESS',
                    'result': task_data['result'],
                    'redirect': True
                }
            else:  # FAILURE
                print(f"❌ Task {task_id} failed: {task_data['result']}")
                response = {
                    'state': 'FAILURE',
                    'result': task_data['result']
                }
        
        return jsonify(response)
        
    except Exception as e:
        # Log detailed error but show generic message
        logger.error(f"Failed to get task status: {str(e)}", exc_info=True)
        return jsonify({
            'state': 'FAILURE',
            'result': {'error': 'Unable to get processing status. Please refresh the page.'}
        })

@app.route('/cancel-task/<task_id>', methods=['POST'])
@limiter.limit("10 per minute")
def cancel_task(task_id):
    """Cancel a running task"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            celery_app.control.revoke(task_id, terminate=True)
            message = f"Task {task_id} has been cancelled"
        else:
            if task_id in task_results:
                task_results[task_id] = {
                    'state': 'REVOKED',
                    'result': {'error': 'Task cancelled by user'}
                }
                message = f"Task {task_id} has been cancelled"
            else:
                message = f"Task {task_id} not found"
        
        return jsonify({
            'status': 'success',
            'message': message
        })
        
    except Exception as e:
        # Log detailed error but show generic message
        logger.error(f"Failed to cancel task {task_id}: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Unable to cancel task. Please try refreshing the page.'
        }), 500

@app.route('/tiktok-results/<task_id>')
def tiktok_results(task_id):
    """Show results from completed video processing"""
    try:
        redis_url = os.getenv('REDIS_URL')
        video_url = request.args.get('url', '')
        video_type = request.args.get('type', 'Video')
        
        if redis_url:
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'SUCCESS' and task.result.get('status') == 'success':
                books = task.result.get('books', [])
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{video_type.title()} Video: {video_url[:50]}..." if video_url else f"{video_type.title()} Video",
                                         is_tiktok=True) # Retain is_tiktok for now, could generalize later
                else:
                    return render_template('index.html', 
                                         error=f"No books found in this {video_type.title()} video. Try a video that shows book covers more clearly.")
            else:
                return render_template('index.html', 
                                     error="Processing failed or is still in progress.")
        else:
            if task_id not in task_results:
                return render_template('index.html', error="Task not found.")
            
            task_data = task_results[task_id]
            
            if task_data['state'] == 'SUCCESS' and task_data['result'].get('status') == 'success':
                books = task_data['result'].get('books', [])
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{video_type.title()} Video: {video_url[:50]}..." if video_url else f"{video_type.title()} Video",
                                         is_tiktok=True) # Retain is_tiktok for now, could generalize later
                else:
                    return render_template('index.html', 
                                         error=f"No books found in this {video_type.title()} video. Try a video that shows book covers more clearly.")
            else:
                return render_template('index.html', 
                                     error="Processing failed or is still in progress.")
    except Exception as e:
        # Log detailed error but show generic message
        logger.error(f"Failed to retrieve results for task {task_id}: {str(e)}", exc_info=True)
        return render_template('index.html', error="Unable to retrieve results. Please try processing the video again.")

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt file for AdSense verification"""
    return app.send_static_file('ads.txt')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10001, debug=True)
