"""
Main Flask application for BookSaver.
Streamlined version with modular structure.
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, g
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_session import Session
from dotenv import load_dotenv
import os
import logging
import redis
from logging.config import dictConfig

from services.books_client import build_reader_app_links
from celery_app import celery_app
from services.recommendation_engine import get_recommendation_engine
from system_monitor import get_system_monitor
from core.utils import sanitize_input, serialize_task_result, safe_get_task_result
from routes.images import register_image_routes
from routes.auth import register_auth_routes

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

# Configure Flask-Session with Redis
redis_url = os.getenv('REDIS_URL')
if redis_url and not redis_url.startswith('memory://'):
    app.config['SESSION_TYPE'] = 'redis'
    app.config['SESSION_REDIS'] = redis.from_url(redis_url)
else:
    # Fallback to filesystem sessions for local development
    app.config['SESSION_TYPE'] = 'filesystem'
    
app.config['SESSION_PERMANENT'] = True
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_KEY_PREFIX'] = 'booksaver:'
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7 days

# Initialize session
Session(app)

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
register_image_routes(app, limiter)
require_auth = register_auth_routes(app, limiter)

# Import and register subscription routes
from routes.subscription import register_subscription_routes
register_subscription_routes(app, limiter, require_auth)


# Main routes
@app.route('/')
def index():
    # Get user data for authenticated users
    user_subscription = None
    daily_usage = 0
    
    if g.is_authenticated:
        from services.user_service import get_user_service
        user_service = get_user_service()
        email = session.get('user_email')
        user_subscription = user_service.get_subscription(email)
        daily_usage = user_service.get_daily_usage(email)
    
    return render_template('index.html', 
                         user_subscription=user_subscription,
                         daily_usage=daily_usage)


@app.route('/health')
@limiter.exempt
def health_check():
    """Simple health check endpoint"""
    try:
        # Test database/Redis connection if needed
        system_monitor = get_system_monitor()
        stats = system_monitor.get_current_stats()
        
        # Basic health indicators
        health_status = {
            'status': 'healthy',
            'system': stats.get('system', {}),
            'current_process': stats.get('current_process', {})
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500



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


@app.route('/image-results/<task_id>')
def image_results(task_id):
    """Show results from completed image processing"""
    try:
        from services.user_service import get_user_service
        user_service = get_user_service()
        
        redis_url = os.getenv('REDIS_URL')
        source_type = request.args.get('type', 'Image')
        
        # Get user data for authenticated users
        user_subscription = None
        daily_usage = 0
        
        if g.is_authenticated:
            email = session.get('user_email')
            user_subscription = user_service.get_subscription(email)
            daily_usage = user_service.get_daily_usage(email)
        
        # Check if we're using actual Redis (not memory:// for local dev)
        if redis_url and not redis_url.startswith('memory://'):
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'SUCCESS' and safe_get_task_result(task.result, 'status') == 'success':
                books = safe_get_task_result(task.result, 'books', [])
                
                # Save to history for authenticated premium users
                if g.is_authenticated and books:
                    email = session.get('user_email')
                    scan_result = {
                        'books': books,
                        'source_type': source_type,
                        'task_id': task_id
                    }
                    user_service.add_to_history(email, scan_result)
                
                
                if not books:
                    return render_template('results.html', 
                                         books=[], 
                                         query=f"{source_type} analysis",
                                         error="No books were detected in this image. Try with a clearer photo showing book covers or spines.",
                                         user_subscription=user_subscription,
                                         daily_usage=daily_usage)
                
                return render_template('results.html', 
                                     books=books, 
                                     query=f"Image analysis",
                                     user_subscription=user_subscription,
                                     daily_usage=daily_usage)
            else:
                error_msg = safe_get_task_result(task.result, 'error', 'Task failed or is still processing')
                return render_template('results.html', 
                                     books=[], 
                                     query=f"{source_type} analysis",
                                     error=error_msg,
                                     user_subscription=user_subscription,
                                     daily_usage=daily_usage)
        else:
            if task_id in app.task_results:
                task_data = app.task_results[task_id]
                
                if task_data['state'] == 'SUCCESS' and 'result' in task_data:
                    books = task_data['result'].get('books', [])
                    
                    # Save to history for authenticated premium users
                    if g.is_authenticated and books:
                        email = session.get('user_email')
                        scan_result = {
                            'books': books,
                            'source_type': source_type,
                            'task_id': task_id
                        }
                        user_service.add_to_history(email, scan_result)
                    
                    if not books:
                        return render_template('results.html', 
                                             books=[], 
                                             query=f"{source_type} analysis",
                                             error="No books were detected in this image.",
                                             user_subscription=user_subscription,
                                             daily_usage=daily_usage)
                    
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"{source_type} analysis",
                                         user_subscription=user_subscription,
                                         daily_usage=daily_usage)
                else:
                    error_msg = task_data.get('error', 'Task failed or is still processing')
                    return render_template('results.html', 
                                         books=[], 
                                         query=f"{source_type} analysis",
                                         error=error_msg,
                                         user_subscription=user_subscription,
                                         daily_usage=daily_usage)
            else:
                return render_template('results.html', 
                                     books=[], 
                                     query=f"{source_type} analysis",
                                     error="Task not found or expired",
                                     user_subscription=user_subscription,
                                     daily_usage=daily_usage)
                
    except Exception as e:
        logger.error(f"❌ Results error: {e}")
        return render_template('results.html', 
                             books=[], 
                             query=f"{source_type} analysis",
                             error="Failed to load results",
                             user_subscription=None,
                             daily_usage=0)


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


if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=(os.getenv('FLASK_ENV') != 'production'))