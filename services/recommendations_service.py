"""
Recommendations Service - Generate AI-powered book recommendations.
"""

import os
import json
import logging
from typing import List, Dict
from datetime import datetime
from google import genai

from models import db
from models.book_collection import BookCollection
from models.ai_recommendation import AIRecommendation

# Configure logging
logger = logging.getLogger(__name__)


class RecommendationsService:
    """Service for generating and managing AI book recommendations."""

    @staticmethod
    def generate_recommendations(user_id: int, force_regenerate: bool = False) -> List[AIRecommendation]:
        """
        Generate AI-powered book recommendations from user's unread collection.

        Args:
            user_id: User ID to generate recommendations for
            force_regenerate: If True, regenerate even if recent recommendations exist

        Returns:
            List of AIRecommendation objects (top 5)
        """
        # Check if user has recent recommendations (within last 7 days)
        if not force_regenerate:
            recent_recs = AIRecommendation.get_latest_for_user(user_id, limit=5)
            if recent_recs and len(recent_recs) > 0:
                # Check if most recent is within 7 days
                most_recent = recent_recs[0]
                days_old = (datetime.now() - most_recent.generated_at).days
                if days_old < 7:
                    logger.info(f"Using existing recommendations (generated {days_old} days ago)")
                    return recent_recs

        # Get user's unread books
        unread_books = BookCollection.query.filter(
            BookCollection.user_id == user_id,
            BookCollection.read_status != 'read'
        ).order_by(BookCollection.added_at.desc()).limit(50).all()

        if not unread_books or len(unread_books) == 0:
            logger.info(f"No unread books found for user {user_id}")
            return []

        # Build prompt with unread books
        books_list = []
        for book in unread_books:
            books_list.append({
                'title': book.title,
                'authors': book.get_authors_display(),
                'genres': book.genres if book.genres else []
            })

        prompt = f"""
You are a professional book recommendation assistant. A reader has the following books in their "want to read" and "currently reading" shelves:

{json.dumps(books_list, indent=2)}

Based on this collection, please recommend the TOP 5 books from this list that the reader should prioritize reading next. Consider:
1. Genre diversity (don't recommend all the same genre)
2. Highly-rated and popular books
3. Books that complement each other well
4. A mix of different reading experiences

For each recommendation, provide:
- The exact title (must match one from the list above)
- The authors (as shown in the list)
- A brief, compelling reason (1-2 sentences) why this book should be read next

Format your response as a JSON array with this structure:
[
  {{
    "title": "Book Title",
    "authors": "Author Name",
    "reason": "A compelling 1-2 sentence reason why to read this book next."
  }}
]

IMPORTANT: Return ONLY the JSON array, no additional text before or after. The titles and authors must exactly match the books from the list provided.
"""

        # Call Gemini AI
        try:
            api_key = os.getenv('GEMINI_API_KEY')
            if not api_key:
                raise ValueError("GEMINI_API_KEY environment variable is required")

            genai_client = genai.Client(api_key=api_key)

            logger.info(f"Generating recommendations for {len(unread_books)} unread books...")

            response = genai_client.models.generate_content(
                model="gemini-2.5-flash-preview-09-2025",
                contents=prompt
            )

            logger.info("Gemini response received")

            # Parse JSON response
            recommendations_data = json.loads(response.text)

            if not isinstance(recommendations_data, list):
                logger.error("Invalid response format: expected JSON array")
                return []

            # Clear old recommendations for this user (keep history lightweight)
            AIRecommendation.query.filter_by(user_id=user_id).delete()
            db.session.commit()

            # Create recommendation records
            saved_recommendations = []

            for i, rec_data in enumerate(recommendations_data[:5]):  # Top 5 only
                # Find the book in collection to get ISBN
                book_title = rec_data.get('title', '')
                book = next(
                    (b for b in unread_books if b.title.lower() == book_title.lower()),
                    None
                )

                if not book:
                    logger.warning(f"Book not found in collection: {book_title}")
                    continue

                recommendation = AIRecommendation(
                    user_id=user_id,
                    book_title=book.title,
                    book_authors=book.get_authors_display(),
                    book_isbn=book.isbn,
                    recommendation_reason=rec_data.get('reason', 'Recommended for you'),
                    rank=i + 1
                )

                db.session.add(recommendation)
                saved_recommendations.append(recommendation)

            db.session.commit()
            logger.info(f"Saved {len(saved_recommendations)} recommendations for user {user_id}")

            return saved_recommendations

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Gemini response as JSON: {e}")
            logger.error(f"Raw response: {response.text if 'response' in locals() else 'No response'}")
            return []

        except Exception as e:
            logger.error(f"Error generating recommendations: {e}")
            return []

    @staticmethod
    def get_latest_recommendations(user_id: int, limit: int = 5) -> List[AIRecommendation]:
        """
        Get the latest AI recommendations for a user.

        Args:
            user_id: User ID
            limit: Maximum number of recommendations to return

        Returns:
            List of AIRecommendation objects
        """
        return AIRecommendation.get_latest_for_user(user_id, limit=limit)

    @staticmethod
    def mark_recommendation_read(recommendation_id: int) -> bool:
        """
        Mark a recommendation as read.

        Args:
            recommendation_id: Recommendation ID

        Returns:
            True if successful, False otherwise
        """
        recommendation = AIRecommendation.query.get(recommendation_id)

        if not recommendation:
            return False

        recommendation.is_read = True
        db.session.commit()

        return True

    @staticmethod
    def get_recommendation_stats(user_id: int) -> Dict:
        """
        Get statistics about recommendations for a user.

        Args:
            user_id: User ID

        Returns:
            Dict with recommendation statistics
        """
        total_recs = AIRecommendation.query.filter_by(user_id=user_id).count()
        read_recs = AIRecommendation.query.filter_by(user_id=user_id, is_read=True).count()

        latest_recs = AIRecommendation.get_latest_for_user(user_id, limit=1)
        last_generated = latest_recs[0].generated_at if latest_recs else None

        return {
            'total_recommendations': total_recs,
            'read_recommendations': read_recs,
            'unread_recommendations': total_recs - read_recs,
            'last_generated': last_generated
        }
