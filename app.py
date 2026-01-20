"""
Main Flask application for BookSaver.
Streamlined version with modular structure.
"""

from flask import Flask, render_template, request, redirect, url_for, jsonify, flash
from datetime import datetime
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_login import login_required, current_user
from dotenv import load_dotenv
import os
import logging
from logging.config import dictConfig

from config import get_config
from models import db, login_manager, User
from services.books_client import build_reader_app_links
from core.utils import sanitize_input
from routes.images import register_image_routes
from routes.seo_pages import register_seo_routes
from routes.auth import auth_bp
from routes.billing import billing_bp
from routes.collections import collections_bp
from routes.goals import goals_bp
from routes.dashboard import dashboard_bp

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

# Load configuration
config = get_config()
app.config.from_object(config)

logger = logging.getLogger(__name__)

# Initialize database
db.init_app(app)

# Initialize Flask-Migrate
migrate = Migrate(app, db)

# Ensure database tables exist (fallback if migrations fail)
with app.app_context():
    try:
        # Try to query the users table to see if it exists
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()

        if 'users' not in tables:
            logger.warning("Database tables not found. Creating tables...")
            db.create_all()
            logger.info("✓ Database tables created successfully")
        else:
            logger.info(f"✓ Database connected. Found {len(tables)} tables")
    except Exception as e:
        logger.error(f"Database initialization check failed: {e}")
        # Try to create tables anyway
        try:
            db.create_all()
            logger.info("✓ Database tables created successfully (after error)")
        except Exception as create_error:
            logger.error(f"Failed to create database tables: {create_error}")

# Initialize Flask-Login
login_manager.init_app(app)
login_manager.login_view = 'auth.send_magic_link'
login_manager.login_message = 'Please log in to access this page.'


@login_manager.user_loader
def load_user(user_id):
    """Load user by ID for Flask-Login."""
    return User.query.get(int(user_id))


# Create instance directory if it doesn't exist
instance_path = app.instance_path
os.makedirs(instance_path, exist_ok=True)
logger.info(f"📁 Instance path: {instance_path}")




def log_environment_status():
    """Log the status of important environment variables"""
    env_vars = {
        'GEMINI_API_KEY': os.getenv('GEMINI_API_KEY'),
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

# Initialize rate limiter (simplified)
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["100 per hour", "20 per minute"],
    strategy="fixed-window"
)
print("🔧 Flask-Limiter configured")


# Security headers middleware
@app.after_request
def add_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    
    # Only add HSTS in production with HTTPS
    if os.getenv('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Cache static assets for longer in production
        if request.endpoint and request.endpoint.startswith('static'):
            response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    else:
        # Shorter cache for development
        if request.endpoint and request.endpoint.startswith('static'):
            response.headers['Cache-Control'] = 'public, max-age=3600'
    
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
register_seo_routes(app, limiter)
app.register_blueprint(auth_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(collections_bp)
app.register_blueprint(goals_bp)
app.register_blueprint(dashboard_bp)


# Main routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/account')
@login_required
def account():
    """User account page with subscription management."""
    from models.subscription import Subscription
    from services.goals_service import GoalsService

    # Get active subscription
    subscription = Subscription.get_active_for_user(current_user.id)

    # Get goal progress for Pro users
    goal_progress = None
    if current_user.is_pro():
        goal_progress = GoalsService.get_progress(current_user.id)

    return render_template('account.html',
                         user=current_user,
                         subscription=subscription,
                         goal_progress=goal_progress)


@app.route('/history')
@login_required
def history():
    """View scan history (Pro users only)."""
    from models.scan_history import ScanHistory

    # Check if user is Pro
    if not current_user.is_pro():
        flash('Scan history is only available for Pro subscribers.', 'warning')
        return redirect(url_for('billing.upgrade'))

    # Get scan history for current user
    scans = ScanHistory.get_history_for_user(current_user.id, limit=50)

    return render_template('history.html', scans=scans)


@app.route('/health')
@limiter.exempt
def health_check():
    """Simple health check endpoint"""
    try:
        # Basic health check
        health_status = {
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify(health_status), 200
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500









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


@app.route('/robots.txt')
def robots_txt():
    """Serve robots.txt file with proper content-type"""
    from flask import make_response
    response = make_response(app.send_static_file('robots.txt'))
    response.headers['Content-Type'] = 'text/plain'
    return response


@app.route('/sitemap.xml')
def sitemap():
    """Generate XML sitemap dynamically"""
    from datetime import datetime
    from flask import make_response
    
    # Static pages
    pages = [
        {
            'url': url_for('index', _external=True),
            'lastmod': '2025-01-01',
            'changefreq': 'daily',
            'priority': '1.0'
        },
        {
            'url': url_for('recommendations', _external=True),
            'lastmod': '2025-01-01', 
            'changefreq': 'weekly',
            'priority': '0.8'
        },
        {
            'url': url_for('privacy', _external=True),
            'lastmod': '2025-01-01',
            'changefreq': 'monthly',
            'priority': '0.3'
        },
        {
            'url': url_for('terms', _external=True),
            'lastmod': '2025-01-01',
            'changefreq': 'monthly', 
            'priority': '0.3'
        },
    ]
    
    # Enhanced sitemap with SEO landing pages
    
    # Generate XML
    xml_content = ['<?xml version="1.0" encoding="UTF-8"?>']
    xml_content.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')
    
    for page in pages:
        xml_content.append('  <url>')
        xml_content.append(f'    <loc>{page["url"]}</loc>')
        xml_content.append(f'    <lastmod>{page["lastmod"]}</lastmod>')
        xml_content.append(f'    <changefreq>{page["changefreq"]}</changefreq>')
        xml_content.append(f'    <priority>{page["priority"]}</priority>')
        xml_content.append('  </url>')
    
    xml_content.append('</urlset>')
    
    response = make_response('\n'.join(xml_content))
    response.headers['Content-Type'] = 'application/xml'
    return response


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