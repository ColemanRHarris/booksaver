"""
Goals Service - Business logic for managing reading goals.
"""

from models import db, ReadingGoal
from services.collections_service import CollectionsService
from datetime import datetime
from typing import Dict, Optional


class GoalsService:
    """Service for managing user reading goals."""

    @staticmethod
    def get_goal(user_id: int) -> Optional[ReadingGoal]:
        """
        Get the current reading goal for a user.

        Args:
            user_id: User ID

        Returns:
            ReadingGoal instance or None if no goal exists
        """
        return ReadingGoal.get_goal_for_user(user_id)

    @staticmethod
    def set_goal(user_id: int, year: int, target_count: int) -> ReadingGoal:
        """
        Set or update a reading goal for a user.

        Args:
            user_id: User ID
            year: Goal year (e.g., 2026)
            target_count: Number of books to read

        Returns:
            ReadingGoal instance
        """
        if target_count < 1:
            raise ValueError("Target count must be at least 1")

        goal = ReadingGoal.set_goal(user_id, year, target_count)
        db.session.commit()

        print(f"📚 Goal set: Read {target_count} books in {year}")
        return goal

    @staticmethod
    def get_progress(user_id: int) -> Dict:
        """
        Get progress towards current reading goal.

        Args:
            user_id: User ID

        Returns:
            Dict with goal details and progress:
            {
                'has_goal': bool,
                'year': int,
                'target_count': int,
                'current_count': int,
                'percentage': float,
                'books_read': List[BookCollection]
            }
        """
        goal = GoalsService.get_goal(user_id)

        if not goal:
            return {
                'has_goal': False,
                'year': datetime.now().year,
                'target_count': 0,
                'current_count': 0,
                'percentage': 0,
                'books_read': []
            }

        # Get books read in the goal year
        books_read = CollectionsService.get_books_read_this_year(user_id, goal.year)
        current_count = len(books_read)
        percentage = (current_count / goal.target_count * 100) if goal.target_count > 0 else 0

        return {
            'has_goal': True,
            'year': goal.year,
            'target_count': goal.target_count,
            'current_count': current_count,
            'percentage': round(percentage, 1),
            'books_read': books_read
        }

    @staticmethod
    def delete_goal(user_id: int) -> bool:
        """
        Delete a user's reading goal.

        Args:
            user_id: User ID

        Returns:
            True if deleted, False if no goal existed
        """
        goal = GoalsService.get_goal(user_id)

        if not goal:
            return False

        db.session.delete(goal)
        db.session.commit()

        print(f"🗑️ Deleted reading goal for user {user_id}")
        return True

    @staticmethod
    def get_goal_summary(user_id: int) -> str:
        """
        Get a human-readable summary of goal progress.

        Args:
            user_id: User ID

        Returns:
            String summary like "8 of 24 books (33%)"
        """
        progress = GoalsService.get_progress(user_id)

        if not progress['has_goal']:
            return "No goal set"

        return f"{progress['current_count']} of {progress['target_count']} books ({progress['percentage']}%)"

    @staticmethod
    def is_goal_completed(user_id: int) -> bool:
        """
        Check if user has completed their reading goal.

        Args:
            user_id: User ID

        Returns:
            True if goal is met or exceeded, False otherwise
        """
        progress = GoalsService.get_progress(user_id)

        if not progress['has_goal']:
            return False

        return progress['current_count'] >= progress['target_count']
