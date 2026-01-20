"""
Dashboard routes for analytics and statistics (Pro feature).
"""

from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from services.analytics_service import AnalyticsService
from services.recommendations_service import RecommendationsService
from datetime import datetime

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')


@dashboard_bp.route('/')
@login_required
def index():
    """Show analytics dashboard (Pro only)."""
    # Check if user is Pro
    if not current_user.is_pro():
        flash('Upgrade to Pro to access your analytics dashboard!', 'info')
        return redirect(url_for('billing.upgrade'))

    try:
        # Get all analytics data
        total_stats = AnalyticsService.get_total_stats(current_user.id)
        scans_over_time = AnalyticsService.get_scans_over_time(current_user.id)
        genre_distribution = AnalyticsService.get_genre_distribution(current_user.id)
        top_authors = AnalyticsService.get_top_authors(current_user.id, limit=10)
        collection_breakdown = AnalyticsService.get_collection_breakdown(current_user.id)
        reading_pace = AnalyticsService.get_reading_pace(current_user.id)

        # Get AI recommendations
        recommendations = RecommendationsService.get_latest_recommendations(current_user.id, limit=5)

        return render_template(
            'dashboard.html',
            total_stats=total_stats,
            scans_over_time=scans_over_time,
            genre_distribution=genre_distribution,
            top_authors=top_authors,
            collection_breakdown=collection_breakdown,
            reading_pace=reading_pace,
            recommendations=recommendations,
            current_year=datetime.now().year
        )
    except Exception as e:
        print(f"Error loading dashboard: {e}")
        flash('An error occurred while loading your dashboard.', 'error')
        return redirect(url_for('account'))
