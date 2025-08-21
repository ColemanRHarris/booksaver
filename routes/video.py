"""
Video processing routes for TikTok and Instagram.
"""

import os
import uuid
import threading
from flask import request, render_template, redirect, url_for, current_app
from urllib.parse import urlparse

from core.utils import validate_url, sanitize_input
from tasks import process_video
from services.recommendation_engine import get_recommendation_engine

# Global task results storage for local development
task_results = {}


def process_video_background(task_id: str, video_url: str, video_type: str):
    """Background task for local development (non-Redis)"""
    try:
        # Update status
        task_results[task_id] = {
            'state': 'PROGRESS',
            'step': 'Starting processing...',
            'progress': 5
        }
        
        # Process the video (this calls the actual Celery task function)
        result = process_video(video_url, video_type)
        
        # Update with final result
        task_results[task_id] = {
            'state': 'SUCCESS',
            'result': result
        }
        
    except Exception as e:
        error_message = str(e)
        
        # Clean up technical error messages for user-friendly display
        if "Unable to download webpage: HTTP Error 404" in error_message:
            error_message = "Video not found. The video may have been deleted, made private, or the URL may be incorrect."
        elif "Private video" in error_message:
            error_message = "This video is private. Please use a public video URL."
        elif "Video unavailable" in error_message:
            error_message = "Video is unavailable. Please try a different video."
        elif "Connection timeout" in error_message or "timeout" in error_message.lower():
            error_message = "Connection timeout. Please check your internet connection and try again."
        elif "GEMINI_API_KEY" in error_message:
            error_message = "Service configuration error. Please try again later."
        
        task_results[task_id] = {
            'state': 'FAILURE',
            'error': error_message
        }


def register_video_routes(app, limiter):
    """Register video processing routes"""
    
    @app.route('/process-tiktok', methods=['POST'])
    @limiter.limit("20 per hour")  # Increased for testing
    def process_tiktok():
        current_app.logger.info(f"🎬 TikTok processing request received from {request.remote_addr}")
        raw_url = request.form.get('tiktok_url', '')
        current_app.logger.info(f"📝 Raw URL received: {raw_url}")
        tiktok_url = sanitize_input(raw_url, max_length=500)
        current_app.logger.info(f"🧹 Sanitized URL: {tiktok_url}")
        
        if not tiktok_url:
            return render_template('index.html', error="Please enter a TikTok URL")
        
        # Proper URL validation
        allowed_domains = ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'm.tiktok.com', 'vt.tiktok.com']
        if not validate_url(tiktok_url, allowed_domains):
            return render_template('index.html', error="Please enter a valid TikTok URL. Supported formats: https://www.tiktok.com/@username/video/123... or https://vm.tiktok.com/abc123")
        
        try:
            redis_url = os.getenv('REDIS_URL')
            
            # Check if we're using actual Redis (not memory:// for local dev)
            if redis_url and not redis_url.startswith('memory://'):
                # Production: Use Celery with Redis
                task = process_video.delay(tiktok_url, 'tiktok')
                task_id = task.id
            else:
                # Local development: Use threading
                task_id = str(uuid.uuid4())
                
                task_results[task_id] = {
                    'state': 'PENDING',
                    'step': 'Initializing...',
                    'progress': 0
                }
                
                # Start background processing
                thread = threading.Thread(
                    target=process_video_background,
                    args=(task_id, tiktok_url, 'tiktok'),
                    daemon=True
                )
                thread.start()
            
            current_app.logger.info(f"✅ Task started: {task_id}")
            return redirect(url_for('processing_wait', task_id=task_id, url=tiktok_url, type='TikTok'))
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to start TikTok processing: {e}")
            return render_template('index.html', error=f"Failed to process video: {str(e)}")
    
    
    @app.route('/process-instagram-reel', methods=['POST'])
    @limiter.limit("20 per hour")
    def process_instagram_reel():
        reel_url = sanitize_input(request.form.get('reel_url', ''), max_length=500)
        
        if not reel_url:
            return render_template('index.html', error="Please enter an Instagram Reel URL")
        
        # Validate Instagram URL
        parsed = urlparse(reel_url)
        if 'instagram.com' not in parsed.netloc.lower():
            return render_template('index.html', error="Please enter a valid Instagram URL")
        
        if '/reel/' not in parsed.path:
            return render_template('index.html', error="Please enter a valid Instagram Reel URL (must contain /reel/)")
        
        try:
            redis_url = os.getenv('REDIS_URL')
            
            # Check if we're using actual Redis (not memory:// for local dev)
            if redis_url and not redis_url.startswith('memory://'):
                task = process_video.delay(reel_url, 'instagram')
                task_id = task.id
            else:
                task_id = str(uuid.uuid4())
                
                task_results[task_id] = {
                    'state': 'PENDING',
                    'step': 'Initializing...',
                    'progress': 0
                }
                
                thread = threading.Thread(
                    target=process_video_background,
                    args=(task_id, reel_url, 'instagram'),
                    daemon=True
                )
                thread.start()
            
            return redirect(url_for('processing_wait', task_id=task_id, url=reel_url, type='Instagram'))
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to start Instagram processing: {e}")
            return render_template('index.html', error=f"Failed to process video: {str(e)}")
    
    # Make task_results available to other modules
    app.task_results = task_results