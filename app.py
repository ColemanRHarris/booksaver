from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv
import os
import threading
import uuid
import time
import logging
from logging.config import dictConfig
from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from celery_app import celery_app
from tasks import process_video

load_dotenv()

# Configure logging
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
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
logger = logging.getLogger(__name__)

books_client = GoogleBooksClient()

# Simple in-memory task tracking
task_results = {}

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
def search():
    query = request.form.get('query', '').strip()
    
    if not query:
        return render_template('index.html', error="Please enter a book title or ISBN")
    
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
        return render_template('index.html', error=f"Configuration error: {str(e)}")
    except Exception as e:
        return render_template('index.html', error="Something went wrong. Please try again later.")

@app.route('/process-tiktok', methods=['POST'])
def process_tiktok():
    tiktok_url = request.form.get('tiktok_url', '').strip()
    
    if not tiktok_url:
        return render_template('index.html', error="Please enter a TikTok URL")
    
    # Basic URL validation
    if 'tiktok.com' not in tiktok_url:
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
        logger.error(f"Failed to start TikTok processing: {str(e)}")
        return render_template('index.html', error=f"Failed to start processing: {str(e)}")

@app.route('/process-instagram-reel', methods=['POST'])
def process_instagram_reel():
    reel_url = request.form.get('reel_url', '').strip()
    
    if not reel_url:
        return render_template('index.html', error="Please enter an Instagram Reel URL")
    
    if 'instagram.com/reel/' not in reel_url and 'instagr.am/reel/' not in reel_url:
        return render_template('index.html', error="Please enter a valid Instagram Reel URL")
    
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
        return render_template('index.html', error=f"Failed to start processing: {str(e)}")

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

@app.route('/ads.txt')
def ads_txt():
    """Serve ads.txt file for AdSense verification"""
    return app.send_static_file('ads.txt')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10001, debug=True)
