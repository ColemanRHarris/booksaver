"""
Collections routes for managing user book collections (Pro feature).
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, make_response
from flask_login import login_required, current_user
from models import db
from services.collections_service import CollectionsService
from services.export_service import ExportService
from datetime import datetime

collections_bp = Blueprint('collections', __name__, url_prefix='/collections')


@collections_bp.route('/')
@login_required
def index():
    """Show collections page with three-tab interface (Pro only)."""
    # Check if user is Pro
    if not current_user.is_pro():
        flash('Upgrade to Pro to organize your books into collections!', 'info')
        return redirect(url_for('billing.upgrade'))

    # Get current tab from query param (default: want_to_read)
    active_tab = request.args.get('tab', 'want_to_read')
    if active_tab not in CollectionsService.VALID_SHELVES:
        active_tab = 'want_to_read'

    # Get books for the active shelf
    books = CollectionsService.get_books_by_shelf(current_user.id, active_tab)

    # Get collection stats
    stats = CollectionsService.get_collection_stats(current_user.id)

    return render_template(
        'collections.html',
        books=books,
        active_tab=active_tab,
        stats=stats
    )


@collections_bp.route('/add', methods=['POST'])
@login_required
def add_book():
    """Add a book to collection from history page."""
    # Check if user is Pro
    if not current_user.is_pro():
        flash('Upgrade to Pro to save books to your collection!', 'error')
        return redirect(url_for('billing.upgrade'))

    # Get book data from form
    book_data = {
        'title': request.form.get('title', '').strip(),
        'authors': request.form.getlist('authors[]'),  # Array of authors
        'isbn': request.form.get('isbn', '').strip(),
        'thumbnail': request.form.get('thumbnail', '').strip(),
        'published_date': request.form.get('published_date', '').strip(),
        'categories': request.form.getlist('categories[]')  # Array of genres
    }

    # Get target shelf (default: want_to_read)
    shelf = request.form.get('shelf', 'want_to_read')

    # Validate required fields
    if not book_data['title'] or not book_data['authors']:
        flash('Book title and author are required.', 'error')
        return redirect(request.referrer or url_for('history'))

    # Add to collection
    collection = CollectionsService.add_book_to_collection(
        user_id=current_user.id,
        book_data=book_data,
        shelf=shelf
    )

    if collection:
        flash(f'Added "{book_data["title"]}" to your collection!', 'success')
    else:
        flash(f'"{book_data["title"]}" is already in your collection.', 'info')

    # Redirect back to where they came from (history page or collections)
    return redirect(request.referrer or url_for('collections.index'))


@collections_bp.route('/move', methods=['POST'])
@login_required
def move_book():
    """Move a book to a different shelf."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)
    new_shelf = request.form.get('shelf', '').strip()

    if not collection_id or not new_shelf:
        return jsonify({'error': 'Missing required fields'}), 400

    success = CollectionsService.move_book(collection_id, new_shelf)

    if success:
        return jsonify({'success': True, 'message': f'Moved to {new_shelf.replace("_", " ").title()}'}), 200
    else:
        return jsonify({'error': 'Failed to move book'}), 400


@collections_bp.route('/update-tags', methods=['POST'])
@login_required
def update_tags():
    """Update tags for a book."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)
    tags_str = request.form.get('tags', '').strip()

    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    # Parse tags (comma-separated)
    tags_list = [tag.strip() for tag in tags_str.split(',') if tag.strip()]

    success = CollectionsService.update_tags(collection_id, tags_list)

    if success:
        return jsonify({'success': True, 'tags': tags_list}), 200
    else:
        return jsonify({'error': 'Failed to update tags'}), 400


@collections_bp.route('/mark-read', methods=['POST'])
@login_required
def mark_as_read():
    """Mark a book as read."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)
    date_read_str = request.form.get('date_read', '').strip()

    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    # Parse date if provided, otherwise use today
    date_read = None
    if date_read_str:
        try:
            date_read = datetime.strptime(date_read_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': 'Invalid date format (use YYYY-MM-DD)'}), 400

    success = CollectionsService.mark_as_read(collection_id, date_read)

    if success:
        return jsonify({'success': True, 'message': 'Marked as read'}), 200
    else:
        return jsonify({'error': 'Failed to mark as read'}), 400


@collections_bp.route('/mark-reading', methods=['POST'])
@login_required
def mark_as_reading():
    """Mark a book as currently reading."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)

    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    success = CollectionsService.mark_as_reading(collection_id)

    if success:
        return jsonify({'success': True, 'message': 'Marked as reading'}), 200
    else:
        return jsonify({'error': 'Failed to mark as reading'}), 400


@collections_bp.route('/mark-unread', methods=['POST'])
@login_required
def mark_as_unread():
    """Mark a book as unread."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)

    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    success = CollectionsService.mark_as_unread(collection_id)

    if success:
        return jsonify({'success': True, 'message': 'Marked as unread'}), 200
    else:
        return jsonify({'error': 'Failed to mark as unread'}), 400


@collections_bp.route('/remove', methods=['POST'])
@login_required
def remove_book():
    """Remove a book from collection."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    collection_id = request.form.get('collection_id', type=int)

    if not collection_id:
        return jsonify({'error': 'Missing collection_id'}), 400

    success = CollectionsService.remove_book(collection_id)

    if success:
        flash('Book removed from your collection.', 'success')
        return jsonify({'success': True, 'message': 'Book removed'}), 200
    else:
        return jsonify({'error': 'Failed to remove book'}), 400


@collections_bp.route('/export')
@login_required
def export_csv():
    """Export user's collection as Goodreads-compatible CSV (Pro only)."""
    # Check if user is Pro
    if not current_user.is_pro():
        flash('Upgrade to Pro to export your collection!', 'error')
        return redirect(url_for('billing.upgrade'))

    try:
        # Generate CSV content
        csv_content = ExportService.generate_goodreads_csv(current_user.id)

        # Create response with CSV file download
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=booksaver_collection_{datetime.now().strftime("%Y%m%d")}.csv'

        return response

    except Exception as e:
        print(f"Error exporting collection: {e}")
        flash('An error occurred while exporting your collection.', 'error')
        return redirect(url_for('collections.index'))
