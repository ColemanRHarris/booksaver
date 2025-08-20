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
from recommendation_engine import get_recommendation_engine
from system_monitor import get_system_monitor

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
            "img-src 'self' data: https://pagead2.googlesyndication.com https://tpc.googlesyndication.com https://books.google.com",
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
            "img-src 'self' data: https: https://books.google.com",
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
@limiter.exempt
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
        
        # Add system monitoring data for Render optimization
        try:
            monitor = get_system_monitor()
            status['system_stats'] = monitor.get_current_stats()
        except Exception as monitor_error:
            status['system_stats'] = {'error': f'Monitoring unavailable: {str(monitor_error)}'}
            
        return jsonify(status), 200
    except Exception as e:
        # Log detailed error but return generic message
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'unhealthy',
            'error': 'Service temporarily unavailable',
            'timestamp': time.time()
        }), 500

@app.route('/system-monitor')
@limiter.exempt
def system_monitor_dashboard():
    """Detailed system monitoring endpoint for instance optimization"""
    try:
        monitor = get_system_monitor()
        
        # Get both current and historical stats
        current_stats = monitor.get_current_stats()
        historical_stats = monitor.get_historical_stats()
        
        response = {
            'timestamp': time.time(),
            'current': current_stats,
            'historical': historical_stats,
            'monitoring_info': {
                'auto_started': True,
                'interval_seconds': 60 if os.getenv('RENDER') else 30,
                'history_minutes': monitor.history_minutes
            }
        }
        
        return jsonify(response), 200
        
    except Exception as e:
        logger.error(f"System monitor dashboard failed: {str(e)}", exc_info=True)
        return jsonify({
            'error': 'System monitoring unavailable',
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
    allowed_domains = ['tiktok.com', 'vm.tiktok.com', 'www.tiktok.com']
    if not validate_url(tiktok_url, allowed_domains):
        return render_template('index.html', error="Please enter a valid TikTok URL. Supported formats: https://www.tiktok.com/@username/video/123... or https://vm.tiktok.com/abc123")
    
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
        
        # Store video session for recommendation engine
        try:
            rec_engine = get_recommendation_engine()
            rec_engine.store_video_session(task_id, tiktok_url, 'tiktok')
        except Exception as e:
            logger.warning(f"Failed to store video session: {e}")
        
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
    allowed_domains = ['instagram.com', 'instagr.am', 'www.instagram.com']
    if not validate_url(reel_url, allowed_domains):
        return render_template('index.html', error="Please enter a valid Instagram Reel URL (e.g., https://www.instagram.com/reel/ABC123def456/)")
    
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
        
        # Store video session for recommendation engine
        try:
            rec_engine = get_recommendation_engine()
            rec_engine.store_video_session(task_id, reel_url, 'instagram')
        except Exception as e:
            logger.warning(f"Failed to store video session: {e}")
        
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

def serialize_task_result(result):
    """Safely serialize task results, handling exceptions and non-serializable objects"""
    if result is None:
        return {'error': 'No result available'}
    
    # If it's already a dict with serializable content, return it
    if isinstance(result, dict):
        try:
            # Test if the dict is JSON serializable
            import json
            json.dumps(result)
            return result
        except (TypeError, ValueError):
            # Convert any non-serializable values to strings
            serialized = {}
            for key, value in result.items():
                try:
                    json.dumps(value)
                    serialized[key] = value
                except (TypeError, ValueError):
                    serialized[key] = str(value)
            return serialized
    
    # If it's an exception or other non-serializable object
    return {'error': str(result)}

def safe_get_task_result(result, key, default=None):
    """Safely get a value from task result, handling non-dict results"""
    if result is None:
        return default
    
    if isinstance(result, dict):
        return result.get(key, default)
    
    # If result is not a dict (like an exception), return default
    return default

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
                    'result': serialize_task_result(task_data['result']),
                    'redirect': True
                }
            else:  # FAILURE
                print(f"❌ Task {task_id} failed: {task_data['result']}")
                response = {
                    'state': 'FAILURE',
                    'result': serialize_task_result(task_data['result'])
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
            
            if task.state == 'SUCCESS' and safe_get_task_result(task.result, 'status') == 'success':
                books = safe_get_task_result(task.result, 'books', [])
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{video_type.title()} Video: {video_url[:50]}..." if video_url else f"{video_type.title()} Video",
                                         is_tiktok=True, # Retain is_tiktok for now, could generalize later
                                         session_id=task_id)
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
            
            if task_data['state'] == 'SUCCESS' and safe_get_task_result(task_data['result'], 'status') == 'success':
                books = safe_get_task_result(task_data['result'], 'books', [])
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{video_type.title()} Video: {video_url[:50]}..." if video_url else f"{video_type.title()} Video",
                                         is_tiktok=True, # Retain is_tiktok for now, could generalize later
                                         session_id=task_id)
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

@app.route('/recommendations')
def recommendations():
    """Show curated book recommendations"""
    try:
        # Create some sample recommendations (you can customize these)
        sample_books = [
        {
            'title': 'Tender Is the Flesh',
            'authors': ['Agustina Bazterrica'],
            'published_date': '2020-08-04',
            'isbn': '9781982150921',
            'description': 'Working at the local processing plant, Marcos is in the business of slaughtering humans—though no one calls them that anymore. His wife has left him, his father is sinking into dementia, and Marcos tries not to think too hard about how he makes a living.',
            'thumbnail': 'https://books.google.com/books/content?id=FMLvDwAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=FMLvDwAAQBAJ&printsec=frontcover&dq=tender+is+the+flesh&hl=en&sa=X',
            'purchase_links': {
                'amazon': 'https://amzn.to/41LP8LR',
                'audible': 'https://amzn.to/4oMjNmg',
                'barnes_noble': 'https://www.barnesandnoble.com/s/tender+is+the+flesh',
                'bookshop': 'https://bookshop.org/books/tender-is-the-flesh/9781982150921',
                'google_books': 'https://books.google.com/books?id=FMLvDwAAQBAJ'
            },
            'reader_app_links': build_reader_app_links({'title': 'Tender Is the Flesh', 'authors': ['Agustina Bazterrica']})
        },
        {
            'title': 'Cold Storage',
            'authors': ['David Koepp'],
            'published_date': '2019-09-03',
            'isbn': '9780062916426',
            'description': 'For decades, a deadly organism has been locked away in a military bunker. But when an earthquake cracks the structure, the organism escapes and begins spreading. Now it\'s up to two unlikely heroes to stop the outbreak before it\'s too late.',
            'thumbnail': 'https://books.google.com/books/content?id=9IQyAQAAMAAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=cold-storage-koepp&printsec=frontcover&dq=cold+storage+david+koepp',
            'purchase_links': {
                'amazon': 'https://amzn.to/46XJ3iU',
                'audible': 'https://amzn.to/4mNhuxq',
                'barnes_noble': 'https://www.barnesandnoble.com/s/cold+storage+david+koepp',
                'bookshop': 'https://bookshop.org/books/cold-storage/9780062916426',
                'google_books': 'https://books.google.com/books?q=cold+storage+david+koepp'
            },
            'reader_app_links': build_reader_app_links({'title': 'Cold Storage', 'authors': ['David Koepp']})
        },
        {
            'title': 'Project Hail Mary',
            'authors': ['Andy Weir'],
            'published_date': '2021-05-04',
            'isbn': '9780593135204',
            'description': 'A lone astronaut must save the earth from disaster in this critically acclaimed and bestselling new novel by the author of The Martian. Ryland Grace woke up on a spaceship with no idea how he got there. His crewmates are dead. His memories are fading.',
            'thumbnail': 'https://books.google.com/books/content?id=iEiHEAAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=project-hail-mary&printsec=frontcover&dq=project+hail+mary',
            'purchase_links': {
                'amazon': 'https://amzn.to/45G6uuK',
                'audible': 'https://amzn.to/45Gsiqk',
                'barnes_noble': 'https://www.barnesandnoble.com/s/project+hail+mary',
                'bookshop': 'https://bookshop.org/books/project-hail-mary/9780593135204',
                'google_books': 'https://books.google.com/books?q=project+hail+mary+andy+weir'
            },
            'reader_app_links': build_reader_app_links({'title': 'Project Hail Mary', 'authors': ['Andy Weir']})
        },
        {
            'title': 'King Sorrow',
            'authors': ['Joe Hill'],
            'published_date': '2024-11-01',
            'isbn': '9781803362694',
            'description': 'From the New York Times bestselling author of The Fireman and NOS4A2 comes a timely and terrifying novel about grief, loss, and the lengths people will go to hold onto what they love. A haunting exploration of how sorrow can transform into something monstrous.',
            'thumbnail': 'https://books.google.com/books/content?id=GmhOEQAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=king-sorrow-joe-hill&printsec=frontcover&dq=king+sorrow+joe+hill',
            'purchase_links': {
                'amazon': 'https://amzn.to/4fGPqtb',
                'audible': 'https://amzn.to/3V64Ldj',
                'barnes_noble': 'https://www.barnesandnoble.com/s/king+sorrow+joe+hill',
                'bookshop': 'https://bookshop.org/books/king-sorrow/9781803362694',
                'google_books': 'https://books.google.com/books?q=king+sorrow+joe+hill'
            },
            'reader_app_links': build_reader_app_links({'title': 'King Sorrow', 'authors': ['Joe Hill']})
        },
        {
            'title': 'Bury Your Gays',
            'authors': ['Chuck Tingle'],
            'published_date': '2024-07-16',
            'isbn': '9781803365190',
            'description': 'A horror novel that explores the deadly consequences of harmful media tropes. When screenwriter Misha refuses to kill off LGBTQ+ characters in his script, he discovers that reality itself begins to warp around him as the "bury your gays" trope takes on a terrifying life of its own.',
            'thumbnail': 'https://books.google.com/books/content?id=9OfWEAAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=9OfWEAAAQBAJ&printsec=frontcover&dq=bury+your+gays+chuck+tingle',
            'purchase_links': {
                'amazon': 'https://amzn.to/4mJqKm1',
                'audible': 'https://amzn.to/4lD09q2',
                'barnes_noble': 'https://www.barnesandnoble.com/s/bury+your+gays+chuck+tingle',
                'bookshop': 'https://bookshop.org/books/bury-your-gays/9781803365190',
                'google_books': 'https://books.google.com/books?id=9OfWEAAAQBAJ'
            },
            'reader_app_links': build_reader_app_links({'title': 'Bury Your Gays', 'authors': ['Chuck Tingle']})
        },
        {
            'title': 'King of Ashes',
            'authors': ['S. A. Cosby'],
            'published_date': '2025-06-10',
            'isbn': '9781250395023',
            'description': 'Award-winning, New York Times bestselling author S. A. Cosby returns with King of Ashes, a Godfather-esque crime saga that follows a Black funeral director who also happens to be the most feared crime boss on the East Coast.',
            'thumbnail': 'https://books.google.com/books/content?id=f78yEQAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
            'preview_link': 'https://books.google.com/books?id=f78yEQAAQBAJ&printsec=frontcover&dq=king+of+ashes+s.a.+cosby',
            'purchase_links': {
                'amazon': 'https://amzn.to/4oVPjhM',
                'audible': 'https://amzn.to/3UvcNfE',
                'barnes_noble': 'https://www.barnesandnoble.com/s/king+of+ashes+s.a.+cosby',
                'bookshop': 'https://bookshop.org/books/king-of-ashes/9781250395023',
                'google_books': 'https://books.google.com/books?id=f78yEQAAQBAJ'
            },
            'reader_app_links': build_reader_app_links({'title': 'King of Ashes', 'authors': ['S. A. Cosby']})
        }
        ]
        
        return render_template('recommendations.html', books=sample_books)
    except Exception as e:
        logger.error(f"Error loading recommendations: {str(e)}", exc_info=True)
        return render_template('index.html', error="Unable to load recommendations. Please try again later.")

@app.route('/api/feedback', methods=['POST'])
@limiter.limit("30 per minute")  # Allow frequent feedback
def submit_feedback():
    """Submit thumbs up/down feedback for a book"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON data'}), 400
        
        session_id = data.get('session_id')
        book_isbn = data.get('book_isbn', '')
        book_title = data.get('book_title', '')
        book_authors = data.get('book_authors', [])
        feedback = data.get('feedback')  # 1 for thumbs up, -1 for thumbs down
        
        if not session_id:
            return jsonify({'status': 'error', 'message': 'Session ID required'}), 400
        
        if not book_title:
            return jsonify({'status': 'error', 'message': 'Book title required'}), 400
        
        if feedback not in [1, -1]:
            return jsonify({'status': 'error', 'message': 'Invalid feedback value'}), 400
        
        # Submit feedback
        rec_engine = get_recommendation_engine()
        rec_engine.submit_feedback(session_id, book_isbn, book_title, book_authors, feedback)
        
        # Get updated counts
        counts = rec_engine.get_book_feedback_counts(book_isbn)
        
        return jsonify({
            'status': 'success',
            'message': 'Feedback submitted',
            'counts': counts
        })
        
    except Exception as e:
        logger.error(f"Feedback submission error: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to submit feedback'
        }), 500

@app.route('/api/feedback/<book_isbn>')
@limiter.limit("60 per minute")
def get_feedback_counts(book_isbn):
    """Get feedback counts for a book"""
    try:
        rec_engine = get_recommendation_engine()
        counts = rec_engine.get_book_feedback_counts(book_isbn)
        
        return jsonify({
            'status': 'success',
            'counts': counts
        })
        
    except Exception as e:
        logger.error(f"Feedback count error: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to get feedback counts'
        }), 500

@app.route('/api/session-feedback/<session_id>/<book_isbn>')
@limiter.limit("60 per minute")
def get_session_feedback(session_id, book_isbn):
    """Get existing feedback for a book in this session"""
    try:
        rec_engine = get_recommendation_engine()
        feedback = rec_engine.get_session_feedback(session_id, book_isbn)
        
        return jsonify({
            'status': 'success',
            'feedback': feedback
        })
        
    except Exception as e:
        logger.error(f"Session feedback error: {str(e)}", exc_info=True)
        return jsonify({
            'status': 'error',
            'message': 'Failed to get session feedback'
        }), 500

@app.route('/terms')
def terms():
    """Show terms of service"""
    from datetime import datetime
    current_date = datetime.now().strftime("%B %d, %Y")
    return render_template('terms.html', current_date=current_date)

@app.route('/privacy')
def privacy():
    """Show privacy policy"""
    from datetime import datetime
    current_date = datetime.now().strftime("%B %d, %Y")
    return render_template('privacy.html', current_date=current_date)

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt file for AdSense verification"""
    return app.send_static_file('ads.txt')

@app.route('/site.webmanifest')
def site_webmanifest():
    """Serve web app manifest"""
    return app.send_static_file('site.webmanifest')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10001, debug=True)
