"""
Goals routes for managing reading goals (Pro feature).
"""

from flask import Blueprint, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from services.goals_service import GoalsService
from datetime import datetime

goals_bp = Blueprint('goals', __name__, url_prefix='/goals')


@goals_bp.route('/set', methods=['POST'])
@login_required
def set_goal():
    """Set or update a reading goal."""
    # Check if user is Pro
    if not current_user.is_pro():
        flash('Upgrade to Pro to set reading goals!', 'error')
        return redirect(url_for('billing.upgrade'))

    # Get form data
    year = request.form.get('year', type=int)
    target_count = request.form.get('target_count', type=int)

    # Validate inputs
    if not year or not target_count:
        flash('Please provide both year and target count.', 'error')
        return redirect(url_for('account'))

    if target_count < 1:
        flash('Target count must be at least 1 book.', 'error')
        return redirect(url_for('account'))

    current_year = datetime.now().year
    if year < current_year - 1 or year > current_year + 5:
        flash(f'Please choose a year between {current_year - 1} and {current_year + 5}.', 'error')
        return redirect(url_for('account'))

    try:
        # Set the goal
        goal = GoalsService.set_goal(current_user.id, year, target_count)
        flash(f'Reading goal set: {target_count} books in {year}!', 'success')
    except ValueError as e:
        flash(f'Error setting goal: {str(e)}', 'error')
    except Exception as e:
        flash(f'An error occurred while setting your goal.', 'error')
        print(f"Error setting goal: {e}")

    return redirect(url_for('account'))


@goals_bp.route('/delete', methods=['POST'])
@login_required
def delete_goal():
    """Delete a reading goal."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    try:
        deleted = GoalsService.delete_goal(current_user.id)
        if deleted:
            flash('Reading goal deleted.', 'success')
            return jsonify({'success': True, 'message': 'Goal deleted'}), 200
        else:
            return jsonify({'error': 'No goal to delete'}), 404
    except Exception as e:
        print(f"Error deleting goal: {e}")
        return jsonify({'error': 'Failed to delete goal'}), 500


@goals_bp.route('/progress', methods=['GET'])
@login_required
def get_progress():
    """Get goal progress as JSON (for AJAX requests)."""
    if not current_user.is_pro():
        return jsonify({'error': 'Pro subscription required'}), 403

    try:
        progress = GoalsService.get_progress(current_user.id)
        return jsonify(progress), 200
    except Exception as e:
        print(f"Error getting progress: {e}")
        return jsonify({'error': 'Failed to get progress'}), 500
