from flask import Flask, render_template, request, redirect, url_for, jsonify
from dotenv import load_dotenv
import os
import threading
import uuid
import time
from books_client import GoogleBooksClient, build_amazon_link, build_purchase_links, build_reader_app_links
from celery_app import celery_app
from tasks import process_tiktok_video

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

books_client = GoogleBooksClient()

# Simple in-memory task tracking
task_results = {}

def process_tiktok_background(task_id, tiktok_url):
    """Process TikTok video in background thread"""
    try:
        # Update progress
        task_results[task_id] = {
            'state': 'PROGRESS',
            'progress': 10,
            'step': 'Starting processing...'
        }
        
        # Add a small delay to show the waiting page
        time.sleep(2)
        
        # Update progress
        task_results[task_id] = {
            'state': 'PROGRESS', 
            'progress': 30,
            'step': 'Processing video...'
        }
        
        # Call the actual processing function directly
        from tasks import process_tiktok_video
        result = process_tiktok_video.apply(args=[tiktok_url]).result
        
        # Store final result
        task_results[task_id] = {
            'state': 'SUCCESS',
            'result': result
        }
        
    except Exception as e:
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
            task = process_tiktok_video.delay(tiktok_url)
            task_id = task.id
        else:
            # Local development: Use threading
            task_id = str(uuid.uuid4())
            
            # Initialize task status
            task_results[task_id] = {
                'state': 'PENDING',
                'progress': 0,
                'step': 'Waiting to start...'
            }
            
            # Start background processing thread
            thread = threading.Thread(
                target=process_tiktok_background,
                args=(task_id, tiktok_url)
            )
            thread.daemon = True
            thread.start()
        
        # Redirect to waiting page with task ID
        return redirect(url_for('processing_wait', task_id=task_id, url=tiktok_url))
        
    except Exception as e:
        return render_template('index.html', error=f"Failed to start processing: {str(e)}")

@app.route('/processing/<task_id>')
def processing_wait(task_id):
    """Show waiting page while TikTok video is being processed"""
    tiktok_url = request.args.get('url', '')
    return render_template('processing.html', task_id=task_id, tiktok_url=tiktok_url)

@app.route('/task-status/<task_id>')
def task_status(task_id):
    """Get the status of a background task"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            # Production: Use Celery task status
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
            # Local development: Use in-memory task results
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
            # Production: Revoke Celery task
            celery_app.control.revoke(task_id, terminate=True)
            message = f"Task {task_id} has been cancelled"
        else:
            # Local development: Remove from in-memory tracking
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
    """Show results from completed TikTok processing"""
    try:
        redis_url = os.getenv('REDIS_URL')
        
        if redis_url:
            # Production: Use Celery task result
            task = celery_app.AsyncResult(task_id)
            
            if task.state == 'SUCCESS' and task.result.get('status') == 'success':
                books = task.result.get('books', [])
                tiktok_url = request.args.get('url', '')
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"TikTok Video: {tiktok_url[:50]}..." if tiktok_url else "TikTok Video",
                                         is_tiktok=True)
                else:
                    return render_template('index.html', 
                                         error="No books found in this TikTok video. Try a video that shows book covers more clearly.")
            else:
                return render_template('index.html', 
                                     error="Processing failed or is still in progress.")
        else:
            # Local development: Use in-memory task results
            if task_id not in task_results:
                return render_template('index.html', error="Task not found.")
            
            task_data = task_results[task_id]
            
            if task_data['state'] == 'SUCCESS' and task_data['result'].get('status') == 'success':
                books = task_data['result'].get('books', [])
                tiktok_url = request.args.get('url', '')
                
                if len(books) > 0:
                    return render_template('results.html', 
                                         books=books, 
                                         query=f"TikTok Video: {tiktok_url[:50]}..." if tiktok_url else "TikTok Video",
                                         is_tiktok=True)
                else:
                    return render_template('index.html', 
                                         error="No books found in this TikTok video. Try a video that shows book covers more clearly.")
            else:
                return render_template('index.html', 
                                     error="Processing failed or is still in progress.")
    except Exception as e:
        return render_template('index.html', error=f"Failed to retrieve results: {str(e)}")

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10001, debug=True)