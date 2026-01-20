"""
Authentication routes for magic link login.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from flask_login import login_user, logout_user, current_user
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from models import db
from models.user import User
from services.email_service import send_magic_link_email
from email_validator import validate_email, EmailNotValidError

auth_bp = Blueprint('auth', __name__, url_prefix='/auth')

# Rate limiter for magic link requests
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)


@auth_bp.route('/send-magic-link', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def send_magic_link():
    """Send magic link to user's email."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    if request.method == 'GET':
        return render_template('auth/login.html')

    email = request.form.get('email', '').strip().lower()

    # Validate email format
    try:
        valid = validate_email(email)
        email = valid.email
    except EmailNotValidError as e:
        flash('Please enter a valid email address.', 'error')
        return render_template('auth/login.html', email=email)

    # Find or create user
    user = User.find_by_email(email)
    if not user:
        user = User(email=email)
        db.session.add(user)

    # Generate magic link token
    token = user.generate_magic_link_token(
        expiration_minutes=current_app.config['MAGIC_LINK_EXPIRATION_MINUTES']
    )
    db.session.commit()

    # Send magic link email
    magic_link = url_for('auth.verify_magic_link', token=token, _external=True)

    # In development mode, print magic link to console instead of sending email
    if current_app.config.get('DEBUG') or current_app.config.get('TESTING'):
        print("\n" + "="*80)
        print("🔐 MAGIC LINK FOR DEVELOPMENT")
        print("="*80)
        print(f"Email: {email}")
        print(f"Magic Link: {magic_link}")
        print("="*80 + "\n")
        return render_template('auth/magic_link_sent.html', email=email)

    try:
        send_magic_link_email(email, magic_link)
        return render_template('auth/magic_link_sent.html', email=email)
    except Exception as e:
        current_app.logger.error(f"Failed to send magic link to {email}: {e}")
        # In development, still show the link even if email fails
        if current_app.config.get('DEBUG'):
            print("\n" + "="*80)
            print("🔐 MAGIC LINK (Email failed, using console)")
            print("="*80)
            print(f"Email: {email}")
            print(f"Magic Link: {magic_link}")
            print("="*80 + "\n")
            return render_template('auth/magic_link_sent.html', email=email)
        flash('Failed to send magic link. Please try again.', 'error')
        return render_template('auth/login.html', email=email)


@auth_bp.route('/verify/<token>')
def verify_magic_link(token):
    """Verify magic link token and log user in."""
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    # Find user by token
    user = User.find_by_token(token)
    if not user:
        return render_template('auth/magic_link_error.html',
                             error='Invalid magic link.')

    # Verify token is valid and not expired
    if not user.verify_magic_link_token(token):
        return render_template('auth/magic_link_error.html',
                             error='This magic link has expired. Please request a new one.')

    # Clear token and log user in
    user.clear_magic_link_token()
    db.session.commit()

    login_user(user, remember=True)

    # Redirect to wherever they were trying to go, or home
    next_page = request.args.get('next')
    if not next_page or not next_page.startswith('/'):
        next_page = url_for('index')

    return redirect(next_page)


@auth_bp.route('/logout')
def logout():
    """Log user out."""
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('index'))
