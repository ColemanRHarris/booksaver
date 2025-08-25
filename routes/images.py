"""
Image processing routes for book detection.
"""

import os
import uuid
import threading
from flask import request, render_template, redirect, url_for, current_app
from werkzeug.utils import secure_filename

from core.utils import sanitize_input
from tasks import process_image
from services.recommendation_engine import get_recommendation_engine

# Global task results storage for local development
task_results = {}

# Allowed image extensions and max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def allowed_file(filename):
    """Check if the file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def process_image_background(task_id: str, image_path: str):
    """Background task for local development (non-Redis)"""
    try:
        # Update status
        task_results[task_id] = {
            'state': 'PROGRESS',
            'step': 'Starting image analysis...',
            'progress': 5
        }
        
        # Process the image (this calls the actual Celery task function)
        result = process_image(image_path)
        
        # Update with final result
        task_results[task_id] = {
            'state': 'SUCCESS',
            'result': result
        }
        
    except Exception as e:
        error_message = str(e)
        
        # Clean up technical error messages for user-friendly display
        if "No books detected" in error_message:
            error_message = "No books were detected in this image. Try with a clearer photo showing book covers or spines."
        elif "Image too large" in error_message:
            error_message = "Image file is too large. Please use an image smaller than 10MB."
        elif "Invalid image format" in error_message:
            error_message = "Invalid image format. Please use JPG or PNG files."
        elif "GEMINI_API_KEY" in error_message:
            error_message = "Service configuration error. Please try again later."
        
        task_results[task_id] = {
            'state': 'FAILURE',
            'error': error_message
        }


def register_image_routes(app, limiter):
    """Register image processing routes"""
    
    @app.route('/process-image', methods=['POST'])
    @limiter.limit("30 per hour")
    def process_image_upload():
        current_app.logger.info(f"📸 Image processing request received from {request.remote_addr}")
        
        # Check if the post request has the file part
        if 'image' not in request.files:
            return render_template('index.html', error="Please select an image to upload")
        
        file = request.files['image']
        
        # If user does not select file, browser also submits empty part without filename
        if file.filename == '':
            return render_template('index.html', error="Please select an image to upload")
        
        if file and allowed_file(file.filename):
            # Check file size
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)  # Reset file pointer
            
            if file_size > MAX_FILE_SIZE:
                return render_template('index.html', error="Image file is too large. Please use an image smaller than 10MB.")
            
            try:
                # Create secure filename
                filename = secure_filename(file.filename)
                if not filename:
                    filename = f"image_{uuid.uuid4().hex}.jpg"
                
                # Save to temp directory
                import tempfile
                temp_dir = tempfile.mkdtemp(prefix="book_image_")
                image_path = os.path.join(temp_dir, filename)
                file.save(image_path)
                
                current_app.logger.info(f"✅ Image saved: {image_path}")
                
                # Process the image
                redis_url = os.getenv('REDIS_URL')
                
                # Check if we're using actual Redis (not memory:// for local dev)
                if redis_url and not redis_url.startswith('memory://'):
                    # Production: Use Celery with Redis
                    task = process_image.delay(image_path)
                    task_id = task.id
                else:
                    # Local development: Use threading
                    task_id = str(uuid.uuid4())
                    
                    task_results[task_id] = {
                        'state': 'PENDING',
                        'step': 'Initializing image analysis...',
                        'progress': 0
                    }
                    
                    # Start background processing
                    thread = threading.Thread(
                        target=process_image_background,
                        args=(task_id, image_path),
                        daemon=True
                    )
                    thread.start()
                
                current_app.logger.info(f"✅ Image processing task started: {task_id}")
                return redirect(url_for('processing_wait', task_id=task_id, url='image', type='Image', results_endpoint='image_results'))
                
            except Exception as e:
                current_app.logger.error(f"❌ Failed to process image: {e}")
                return render_template('index.html', error=f"Failed to process image: {str(e)}")
        else:
            return render_template('index.html', error="Invalid file format. Please upload a JPG or PNG image.")
    
    # Make task_results available to other modules
    app.task_results = task_results