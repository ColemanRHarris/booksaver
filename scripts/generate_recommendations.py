#!/usr/bin/env python3
"""
Batch script to generate AI recommendations for all Pro users.

Run this script weekly to refresh recommendations for active Pro subscribers.

Usage:
    python scripts/generate_recommendations.py

Options:
    --force: Regenerate recommendations even if recent ones exist
    --user-id: Generate recommendations for a specific user only
"""

import os
import sys
import logging
from datetime import datetime

# Add parent directory to path so we can import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from models import db
from models.user import User
from models.subscription import Subscription
from services.recommendations_service import RecommendationsService

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/recommendations.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


def get_pro_users():
    """
    Get all users with active Pro subscriptions.

    Returns:
        List of User objects with active Pro subscriptions
    """
    # Query users with active subscriptions
    pro_users = db.session.query(User).join(Subscription).filter(
        Subscription.status == 'active',
        Subscription.stripe_price_id.isnot(None)
    ).all()

    return pro_users


def generate_for_user(user_id, force=False):
    """
    Generate recommendations for a specific user.

    Args:
        user_id: User ID
        force: If True, regenerate even if recent recommendations exist

    Returns:
        Number of recommendations generated, or None on error
    """
    try:
        logger.info(f"Generating recommendations for user {user_id}...")

        recommendations = RecommendationsService.generate_recommendations(
            user_id=user_id,
            force_regenerate=force
        )

        if recommendations:
            logger.info(f"✅ Generated {len(recommendations)} recommendations for user {user_id}")
            return len(recommendations)
        else:
            logger.info(f"⚠️ No recommendations generated for user {user_id} (may have no unread books)")
            return 0

    except Exception as e:
        logger.error(f"❌ Error generating recommendations for user {user_id}: {e}")
        return None


def main():
    """Main entry point for the batch script."""
    import argparse

    parser = argparse.ArgumentParser(description='Generate AI recommendations for Pro users')
    parser.add_argument('--force', action='store_true', help='Force regeneration even if recent recommendations exist')
    parser.add_argument('--user-id', type=int, help='Generate for specific user ID only')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("Starting AI Recommendations Batch Generation")
    logger.info(f"Timestamp: {datetime.now().isoformat()}")
    logger.info(f"Force regenerate: {args.force}")
    logger.info("=" * 60)

    # Create Flask app context
    app = create_app()

    with app.app_context():
        # Single user mode
        if args.user_id:
            logger.info(f"Running in single-user mode for user {args.user_id}")

            user = User.query.get(args.user_id)
            if not user:
                logger.error(f"User {args.user_id} not found")
                sys.exit(1)

            if not user.is_pro():
                logger.warning(f"User {args.user_id} is not a Pro subscriber")
                sys.exit(1)

            result = generate_for_user(args.user_id, force=args.force)

            if result is not None:
                logger.info("✅ Single user generation complete")
                sys.exit(0)
            else:
                logger.error("❌ Single user generation failed")
                sys.exit(1)

        # Batch mode - all Pro users
        logger.info("Running in batch mode for all Pro users")

        try:
            pro_users = get_pro_users()
            logger.info(f"Found {len(pro_users)} Pro users")

            if len(pro_users) == 0:
                logger.info("No Pro users found. Exiting.")
                sys.exit(0)

            # Process each user
            success_count = 0
            skip_count = 0
            error_count = 0

            for i, user in enumerate(pro_users, 1):
                logger.info(f"\n[{i}/{len(pro_users)}] Processing user {user.id} ({user.email})...")

                result = generate_for_user(user.id, force=args.force)

                if result is not None:
                    if result > 0:
                        success_count += 1
                    else:
                        skip_count += 1
                else:
                    error_count += 1

                # Rate limiting between users (to avoid API throttling)
                if i < len(pro_users):
                    import time
                    time.sleep(2)  # 2 second delay between users

            # Summary
            logger.info("\n" + "=" * 60)
            logger.info("Batch Generation Complete")
            logger.info(f"Total Pro users: {len(pro_users)}")
            logger.info(f"✅ Success: {success_count}")
            logger.info(f"⚠️ Skipped (no unread books): {skip_count}")
            logger.info(f"❌ Errors: {error_count}")
            logger.info("=" * 60)

            # Exit with appropriate code
            if error_count > 0:
                sys.exit(1)
            else:
                sys.exit(0)

        except Exception as e:
            logger.error(f"❌ Batch generation failed: {e}")
            import traceback
            logger.error(traceback.format_exc())
            sys.exit(1)


if __name__ == '__main__':
    main()
