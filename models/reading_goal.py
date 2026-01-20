"""
Reading Goal model to store annual reading goals for Pro users.
"""

from datetime import datetime
from models import db


class ReadingGoal(db.Model):
    """Model to store reading goals for users."""

    __tablename__ = 'reading_goals'

    # Primary key
    id = db.Column(db.Integer, primary_key=True)

    # Foreign key to user (one goal per user)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True, index=True)

    # Goal details
    year = db.Column(db.Integer, nullable=False)  # e.g., 2026
    target_count = db.Column(db.Integer, nullable=False)  # e.g., 24 books

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f'<ReadingGoal {self.id} - User {self.user_id} - {self.target_count} books in {self.year}>'

    @staticmethod
    def get_goal_for_user(user_id):
        """Get the reading goal for a user (only one goal per user)."""
        return ReadingGoal.query.filter_by(user_id=user_id).first()

    @staticmethod
    def set_goal(user_id, year, target_count):
        """
        Set or update reading goal for a user.

        Args:
            user_id: User ID
            year: Goal year (e.g., 2026)
            target_count: Number of books to read

        Returns:
            ReadingGoal instance
        """
        goal = ReadingGoal.get_goal_for_user(user_id)

        if goal:
            # Update existing goal
            goal.year = year
            goal.target_count = target_count
            goal.updated_at = datetime.utcnow()
        else:
            # Create new goal
            goal = ReadingGoal(
                user_id=user_id,
                year=year,
                target_count=target_count
            )
            db.session.add(goal)

        return goal
