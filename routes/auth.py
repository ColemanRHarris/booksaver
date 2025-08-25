"""
Authentication routes for user login, signup, and session management.
"""

import os
import uuid
import re
from flask import request, render_template, redirect, url_for, session, flash, jsonify, current_app, g
from werkzeug.utils import secure_filename

from services.user_service import get_user_service


def is_valid_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(pattern, email) is not None


def is_valid_password(password: str) -> bool:
    """Validate password requirements."""
    # At least 8 characters, at least one letter and one number
    if len(password) < 8:
        return False
    
    has_letter = any(c.isalpha() for c in password)
    has_number = any(c.isdigit() for c in password)
    
    return has_letter and has_number


def register_auth_routes(app, limiter):
    """Register authentication routes."""
    
    user_service = get_user_service()
    
    @app.route('/signup', methods=['GET', 'POST'])
    @limiter.limit("10 per minute")
    def signup():
        """User signup page."""
        if request.method == 'GET':
            return render_template('auth/signup.html')
        
        try:
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Validation
            if not email or not password:
                return render_template('auth/signup.html', 
                                     error="Email and password are required")
            
            if not is_valid_email(email):
                return render_template('auth/signup.html', 
                                     error="Please enter a valid email address")
            
            if password != confirm_password:
                return render_template('auth/signup.html', 
                                     error="Passwords do not match")
            
            if not is_valid_password(password):
                return render_template('auth/signup.html', 
                                     error="Password must be at least 8 characters with letters and numbers")
            
            # Try to register user
            if user_service.register_user(email, password):
                # Create session
                session_id = str(uuid.uuid4())
                user_service.create_session(session_id, email)
                session['user_session_id'] = session_id
                session['user_email'] = email
                
                current_app.logger.info(f"✅ User signed up and logged in: {email}")
                flash("Account created successfully! Welcome to BookSaver.", "success")
                return redirect(url_for('index'))
            else:
                return render_template('auth/signup.html', 
                                     error="Email already exists or registration failed")
                
        except Exception as e:
            current_app.logger.error(f"❌ Signup error: {e}")
            return render_template('auth/signup.html', 
                                 error="An error occurred during signup")
    
    @app.route('/login', methods=['GET', 'POST'])
    @limiter.limit("20 per minute")
    def login():
        """User login page."""
        if request.method == 'GET':
            return render_template('auth/login.html')
        
        try:
            email = request.form.get('email', '').strip().lower()
            password = request.form.get('password', '')
            
            if not email or not password:
                return render_template('auth/login.html', 
                                     error="Email and password are required")
            
            # Authenticate user
            user_data = user_service.authenticate_user(email, password)
            if user_data:
                # Create session
                session_id = str(uuid.uuid4())
                user_service.create_session(session_id, email)
                session['user_session_id'] = session_id
                session['user_email'] = email
                
                current_app.logger.info(f"✅ User logged in: {email}")
                flash("Welcome back!", "success")
                
                # Redirect to intended page or home
                next_page = request.args.get('next')
                if next_page:
                    return redirect(next_page)
                return redirect(url_for('index'))
            else:
                return render_template('auth/login.html', 
                                     error="Invalid email or password")
                
        except Exception as e:
            current_app.logger.error(f"❌ Login error: {e}")
            return render_template('auth/login.html', 
                                 error="An error occurred during login")
    
    @app.route('/logout', methods=['POST'])
    def logout():
        """User logout."""
        try:
            # Delete session from Redis
            if 'user_session_id' in session:
                user_service.delete_session(session['user_session_id'])
            
            # Clear Flask session
            session.clear()
            
            flash("You have been logged out.", "info")
            return redirect(url_for('index'))
            
        except Exception as e:
            current_app.logger.error(f"❌ Logout error: {e}")
            session.clear()
            return redirect(url_for('index'))
    
    @app.route('/account')
    def account_dashboard():
        """User account dashboard."""
        # Check if user is logged in
        if 'user_email' not in session:
            return redirect(url_for('login'))
        
        try:
            email = session['user_email']
            user_data = user_service.get_user(email)
            subscription_data = user_service.get_subscription(email)
            
            if not user_data or not subscription_data:
                flash("Account data not found. Please log in again.", "error")
                return redirect(url_for('logout'))
            
            # Get usage stats
            daily_usage = user_service.get_daily_usage(email)
            scan_history = user_service.get_history(email, limit=10)
            
            return render_template('auth/account.html',
                                 user=user_data,
                                 subscription=subscription_data,
                                 daily_usage=daily_usage,
                                 scan_history=scan_history)
            
        except Exception as e:
            current_app.logger.error(f"❌ Account dashboard error: {e}")
            flash("Error loading account data.", "error")
            return redirect(url_for('index'))
    
    # Authentication middleware
    @app.before_request
    def load_user():
        """Load user data before each request."""
        # Skip for static files and auth routes
        if (request.endpoint and 
            (request.endpoint.startswith('static') or 
             request.endpoint in ['signup', 'login', 'logout'])):
            return
        
        # Check if user has session
        if 'user_session_id' in session and 'user_email' in session:
            session_data = user_service.get_session(session['user_session_id'])
            
            if session_data and session_data.get('email') == session['user_email']:
                # Session is valid, load user data
                user_data = user_service.get_user(session['user_email'])
                if user_data:
                    # Make user available in templates
                    from flask import g
                    g.current_user = user_data
                    g.is_authenticated = True
                    return
        
        # No valid session
        from flask import g
        g.current_user = None
        g.is_authenticated = False
    
    def require_auth(f):
        """Decorator to require authentication."""
        def decorated_function(*args, **kwargs):
            if not getattr(g, 'is_authenticated', False):
                flash("Please log in to access this page.", "warning")
                return redirect(url_for('login', next=request.url))
            return f(*args, **kwargs)
        decorated_function.__name__ = f.__name__
        return decorated_function
    
    # Add require_auth to app context for use in other routes
    app.require_auth = require_auth
    
    return require_auth