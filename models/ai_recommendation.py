"""
AI Recommendation model to store Gemini-generated book recommendations for Pro users.
"""

from datetime import datetime
from models import db
import json


class AIRecommendation(db.Model):
    """Model to store AI-generated reading recommendations."""

    __tablename__ = 'ai_recommendations'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Foreign key to user
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    # Recommended book (from their collection)
    book_title = db.Column(db.String(500), nullable=False)
    book_authors_json = db.Column(db.Text, nullable=False)  # JSON array
    book_isbn = db.Column(db.String(20), nullable=True)

    # AI reasoning
    recommendation_reason = db.Column(db.Text, nullable=False)
    # e.g., "Based on your love of Project Hail Mary, you might enjoy this..."

    # Ranking (1-5, where 1 is top recommendation)
    rank = db.Column(db.Integer, nullable=False)

    # Metadata
    generated_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    is_read = db.Column(db.Boolean, default=False)  # Track if user acted on it

    # Composite index for performance
    __table_args__ = (
        db.Index('idx_user_generated', 'user_id', 'generated_at'),
    )

    def __repr__(self):
        return f'<AIRecommendation {self.id} - {self.book_title} (Rank {self.rank})>'

    @property
    def book_authors(self):
        """Get book authors list from JSON string."""
        try:
            return json.loads(self.book_authors_json) if self.book_authors_json else []
        except (json.JSONDecodeError, TypeError):
            return []

    @book_authors.setter
    def book_authors(self, authors_list):
        """Set book authors list as JSON string."""
        self.book_authors_json = json.dumps(authors_list if authors_list else [])

    def get_authors_display(self):
        """Get authors as comma-separated string."""
        authors = self.book_authors
        if not authors:
            return "Unknown Author"
        return ", ".join(authors)

    @staticmethod
    def get_latest_recommendations(user_id, limit=5):
        """
        Get the most recent recommendations for a user.

        Args:
            user_id: User ID
            limit: Maximum number of recommendations to return

        Returns:
            List of AIRecommendation instances ordered by rank
        """
        # Get the most recent batch of recommendations (by generated_at)
        latest_batch = AIRecommendation.query.filter_by(user_id=user_id)\
            .order_by(AIRecommendation.generated_at.desc())\
            .limit(limit)\
            .all()

        if not latest_batch:
            return []

        # Get the generation timestamp of the latest batch
        latest_timestamp = latest_batch[0].generated_at

        # Get all recommendations from that batch, ordered by rank
        return AIRecommendation.query.filter_by(user_id=user_id, generated_at=latest_timestamp)\
            .order_by(AIRecommendation.rank)\
            .all()

    @staticmethod
    def get_latest_for_user(user_id, limit=5):
        """Alias for get_latest_recommendations for backwards compatibility."""
        return AIRecommendation.get_latest_recommendations(user_id, limit)

    @staticmethod
    def clear_old_recommendations(user_id):
        """
        Clear old recommendations for a user before generating new ones.

        Args:
            user_id: User ID
        """
        AIRecommendation.query.filter_by(user_id=user_id).delete()

    @staticmethod
    def create_recommendation(user_id, book_title, book_authors, reason, rank, book_isbn=None):
        """
        Create a new AI recommendation.

        Args:
            user_id: User ID
            book_title: Book title
            book_authors: List of authors
            reason: AI-generated reason for recommendation
            rank: Ranking (1-5)
            book_isbn: Optional ISBN

        Returns:
            AIRecommendation instance
        """
        recommendation = AIRecommendation(
            user_id=user_id,
            book_title=book_title,
            book_isbn=book_isbn,
            recommendation_reason=reason,
            rank=rank
        )
        recommendation.book_authors = book_authors

        return recommendation
