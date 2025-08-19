from flask import Flask, render_template, request, redirect, url_for, jsonify
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from dotenv import load_dotenv
import os
import threading
import uuid
import time
import logging
import re
from logging.config import dictConfig

# Patch OpenCV before any imports that might use ultralytics
try:
    import cv2
    if not hasattr(cv2, 'setNumThreads'):
        def dummy_setNumThreads(num_threads):
            pass
        cv2.setNumThreads = dummy_setNumThreads
except Exception:
    pass

from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from celery_app import celery_app
from tasks import process_video

load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)
dictConfig({
    'version': 1,
    'formatters': {'default': {
        'format': '[%(asctime)s] %(levelname)s in %(module)s: %(message)s',
    }},
    'handlers': {'wsgi': {
        'class': 'logging.StreamHandler',
        'stream': 'ext://flask.logging.wsgi_errors_stream',
        'formatter': 'default'
    }},
    'root': {
        'level': 'INFO',
        'handlers': ['wsgi']
    }
})

app = Flask(__name__)

# Secure secret key handling
secret_key = os.getenv('SECRET_KEY')
if not secret_key:
    if os.getenv('FLASK_ENV') == 'production':
        raise ValueError("SECRET_KEY environment variable must be set in production!")
    else:
        secret_key = 'dev-secret-key-change-in-production'
        logger.warning("⚠️ Using default secret key - NOT SECURE FOR PRODUCTION!")

app.config['SECRET_KEY'] = secret_key

# Initialize security extensions
csrf = CSRFProtect(app)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

books_client = GoogleBooksClient()

# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    # Prevent XSS attacks
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Content Security Policy - allow AdSense and Google domains
    csp = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://pagead2.googlesyndication.com https://www.googletagservices.com; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data: https: http:; "
        "connect-src 'self' https://www.googleapis.com; "
        "frame-src https://googleads.g.doubleclick.net; "
    )
    response.headers['Content-Security-Policy'] = csp
    
    # Referrer policy
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Prevent MIME sniffing
    response.headers['X-Content-Type-Options'] = 'nosniff'
    
    return response

# Simple in-memory task tracking
task_results = {}

# Input validation functions
def validate_url(url: str, platform: str) -> tuple[bool, str]:
    """Validate and sanitize URL input"""
    if not url or len(url.strip()) == 0:
        return False, f"Please enter a {platform} URL"
    
    url = url.strip()
    
    # Check length limits
    if len(url) > 2000:
        return False, "URL is too long"
    
    # Basic URL format validation
    if not url.startswith(('http://', 'https://')):
        return False, "URL must start with http:// or https://"
    
    # Platform-specific validation
    if platform == 'tiktok':
        if not re.search(r'tiktok\.com', url, re.IGNORECASE):
            return False, "Please enter a valid TikTok URL"
    elif platform == 'instagram':
        if not re.search(r'instagram\.com/reel/', url, re.IGNORECASE) and not re.search(r'instagr\.am/reel/', url, re.IGNORECASE):
            return False, "Please enter a valid Instagram Reel URL"
    
    return True, url

def validate_search_query(query: str) -> tuple[bool, str]:
    """Validate and sanitize search query"""
    if not query or len(query.strip()) == 0:
        return False, "Please enter a book title or ISBN"
    
    query = query.strip()
    
    # Check length limits
    if len(query) < 2:
        return False, "Search query must be at least 2 characters long"
    
    if len(query) > 200:
        return False, "Search query is too long"
    
    # Remove any potentially dangerous characters but keep normal punctuation
    sanitized = re.sub(r'[<>"\';()&+]', '', query)
    
    if len(sanitized) == 0:
        return False, "Invalid search query"
    
    return True, sanitized

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
        logger.error(f"Error processing video in background: {str(e)}")
        task_results[task_id] = {
            'state': 'FAILURE',
            'result': {'error': str(e)}
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
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': time.time()
        }), 500

@app.route('/search', methods=['POST'])
@limiter.limit("10 per minute")
def search():
    query = request.form.get('query', '')
    
    # Validate and sanitize input
    is_valid, result = validate_search_query(query)
    if not is_valid:
        logger.warning(f"Invalid search query: {query}")
        return render_template('index.html', error=result)
    
    query = result
    logger.info(f"Book search: {query}")
    
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
        logger.error(f"Search configuration error: {str(e)}")
        return render_template('index.html', error=f"Configuration error: {str(e)}")
    except ConnectionError as e:
        logger.error(f"Search connection error: {str(e)}")
        return render_template('index.html', error="Unable to connect to search service. Please try again later.")
    except TimeoutError as e:
        logger.error(f"Search timeout: {str(e)}")
        return render_template('index.html', error="Search request timed out. Please try again.")
    except Exception as e:
        logger.error(f"Unexpected search error: {str(e)}", exc_info=True)
        return render_template('index.html', error="Something went wrong. Please try again later.")

@app.route('/process-tiktok', methods=['POST'])
@limiter.limit("5 per minute")
def process_tiktok():
    tiktok_url = request.form.get('tiktok_url', '')
    
    # Validate and sanitize input
    is_valid, result = validate_url(tiktok_url, 'tiktok')
    if not is_valid:
        logger.warning(f"Invalid TikTok URL: {tiktok_url}")
        return render_template('index.html', error=result)
    
    tiktok_url = result
    logger.info(f"TikTok processing request: {tiktok_url}")
    
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
        
    except ConnectionError as e:
        logger.error(f"TikTok processing connection error: {str(e)}")
        return render_template('index.html', error="Unable to connect to video processing service. Please try again later.")
    except Exception as e:
        logger.error(f"Failed to start TikTok processing: {str(e)}", exc_info=True)
        return render_template('index.html', error="Failed to start video processing. Please try again later.")

@app.route('/process-instagram-reel', methods=['POST'])
@limiter.limit("5 per minute")
def process_instagram_reel():
    reel_url = request.form.get('reel_url', '')
    
    # Validate and sanitize input
    is_valid, result = validate_url(reel_url, 'instagram')
    if not is_valid:
        logger.warning(f"Invalid Instagram URL: {reel_url}")
        return render_template('index.html', error=result)
    
    reel_url = result
    logger.info(f"Instagram processing request: {reel_url}")
    
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
        
    except ConnectionError as e:
        logger.error(f"Instagram processing connection error: {str(e)}")
        return render_template('index.html', error="Unable to connect to video processing service. Please try again later.")
    except Exception as e:
        logger.error(f"Failed to start Instagram processing: {str(e)}", exc_info=True)
        return render_template('index.html', error="Failed to start video processing. Please try again later.")

@app.route('/processing/<task_id>')
def processing_wait(task_id):
    """Show waiting page while video is being processed"""
    video_url = request.args.get('url', '')
    video_type = request.args.get('type', 'Video')
    return render_template('processing.html', task_id=task_id, video_url=video_url, video_type=video_type)

@app.route('/task-status/<task_id>')
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
        return jsonify({
            'state': 'FAILURE',
            'result': {'error': f'Failed to get task status: {str(e)}'}
        })

@app.route('/cancel-task/<task_id>', methods=['POST'])
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
        return jsonify({
            'status': 'error',
            'message': f'Failed to cancel task: {str(e)}'
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
        return render_template('index.html', error=f"Failed to retrieve results: {str(e)}")

@app.route('/recommendations')
def recommendations():
    """Show our recommended books using the results format"""
    # Hardcoded recommended books with their details and real covers
    recommended_books = [
        {
            'title': 'Tender Is the Flesh',
            'authors': ['Agustina Bazterrica'],
            'published_date': '2020-08-04',
            'isbn': '9781982150921',
            'description': 'Working at the local processing plant, Marcos is in the business of slaughtering humans—though no one calls them that anymore. His wife has left him, his father is sinking into dementia, and Marcos tries not to think too hard about how he makes a living.',
            'thumbnail': 'http://books.google.com/books/content?id=FMLvDwAAQBAJ&printsec=frontcover&img=1&zoom=1&edge=curl&source=gbs_api',
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
            'thumbnail': 'http://books.google.com/books/content?id=9IQyAQAAMAAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api',
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
            'thumbnail': 'https://images-na.ssl-images-amazon.com/images/S/compressed.photo.goodreads.com/books/1597695864i/54493401.jpg',
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
            'thumbnail': 'http://books.google.com/books/content?id=puo_0QEACAAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api',
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
            'thumbnail': 'http://books.google.com/books/content?id=9OfWEAAAQBAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api',
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
            'thumbnail': 'http://books.google.com/books/content?id=f78yEQAAQBAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api',
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
    
    return render_template('recommendations.html', books=recommended_books)

@app.route('/privacy')
def privacy():
    """Privacy Policy page"""
    from datetime import datetime
    return render_template('privacy.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/terms')
def terms():
    """Terms of Service page"""
    from datetime import datetime
    return render_template('terms.html', current_date=datetime.now().strftime('%B %d, %Y'))

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt file for AdSense verification"""
    return app.send_static_file('ads.txt')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10001, debug=True)
