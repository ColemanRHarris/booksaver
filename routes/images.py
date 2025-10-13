"""
Image processing routes for book detection.
"""

import os
import uuid
from flask import request, render_template, current_app, redirect, url_for, flash
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from core.utils import sanitize_input
from services.image_storage import get_image_storage_service
from services.image_processor import get_image_processor
from models import db

# Allowed image extensions and max file size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def allowed_file(filename):
    """Check if the file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS



def register_image_routes(app, limiter):
    """Register image processing routes"""

    @app.route('/process-image', methods=['POST'])
    @limiter.limit("30 per hour")  # Keep IP-based limit as backup
    @login_required
    def process_image_upload():
        current_app.logger.info(f"📸 Image processing request received from {current_user.email}")

        # Pro users can process images without payment
        if not current_user.is_pro():
            # Check if this is a paid scan (session_id from payment success page)
            session_id = request.form.get('session_id')
            if session_id:
                # Verify the payment was successful
                try:
                    import stripe
                    stripe.api_key = current_app.config['STRIPE_SECRET_KEY']
                    session = stripe.checkout.Session.retrieve(session_id)

                    if session.payment_status != 'paid':
                        flash('Payment not confirmed. Please try again.', 'error')
                        return redirect(url_for('index'))

                    current_app.logger.info(f"✅ Verified paid scan for {current_user.email}, session: {session_id}")
                except Exception as e:
                    current_app.logger.error(f"Error verifying payment session: {e}")
                    flash('Could not verify payment. Please contact support.', 'error')
                    return redirect(url_for('index'))
            else:
                # Non-Pro users need to pay per scan
                flash('Please pay $0.99 to scan this image, or upgrade to Pro for unlimited scans.', 'warning')
                return redirect(url_for('index'))

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
                
                # Store image in Redis instead of temp directory
                image_storage = get_image_storage_service()
                image_data = file.read()
                
                # Store image data temporarily (TTL: 1 hour should be plenty)
                image_id = image_storage.store_image(image_data, filename, ttl=3600)
                current_app.logger.info(f"✅ Image stored temporarily: {image_id} ({len(image_data)} bytes)")
                
                # Process the image directly
                current_app.logger.info(f"🚀 Starting direct image processing: {image_id}")
                processor = get_image_processor()
                result = processor.process_image(image_id)
                
                # Check if processing was successful
                if result['status'] == 'success':
                    books = result.get('books', [])
                    current_app.logger.info(f"✅ Processing completed: {len(books)} books found")

                    # Save to history for Pro users
                    if current_user.is_pro():
                        from models.scan_history import ScanHistory
                        try:
                            history_record = ScanHistory.create_from_scan(
                                user_id=current_user.id,
                                books_list=books,
                                search_query="Image analysis"
                            )
                            db.session.add(history_record)
                            db.session.commit()
                            current_app.logger.info(f"📝 Saved scan to history for {current_user.email}")
                        except Exception as e:
                            current_app.logger.error(f"Failed to save scan history: {e}")
                            # Don't fail the request if history save fails
                            db.session.rollback()

                    return render_template('results.html', books=books, query="Image analysis")
                else:
                    error_msg = result.get('error', 'Processing failed')
                    current_app.logger.error(f"❌ Processing failed: {error_msg}")
                    return render_template('index.html', error=error_msg)
                
            except Exception as e:
                import traceback
                # Log full technical details for debugging
                current_app.logger.error(f"❌ TECHNICAL ERROR: {type(e).__name__}: {str(e)}")
                current_app.logger.error(f"❌ Full exception: {e.__class__.__module__}.{e.__class__.__name__}")
                current_app.logger.error(f"❌ Stack trace: {traceback.format_exc()}")

                # Log request context
                current_app.logger.error(f"❌ Request context - File size: {len(image_data)} bytes, Filename: {filename}, IP: {request.remote_addr}")

                # Determine error message based on environment
                show_technical = os.getenv('FLASK_ENV') != 'production' or os.getenv('DEBUG_ERRORS') == 'true'
                if show_technical:
                    error_msg = f"TECHNICAL ERROR: {type(e).__name__}: {str(e)}"
                else:
                    error_msg = f"Failed to process image: {str(e)}"

                return render_template('index.html', error=error_msg)
        else:
            return render_template('index.html', error="Invalid file format. Please upload a JPG or PNG image.")
    
