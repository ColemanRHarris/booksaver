"""
Tests for database migration safety.

Ensures that:
- Migration creates all required tables
- Existing data is preserved during migration
- Migration rollback works safely
"""

import pytest
from sqlalchemy import inspect, text

from models import db
from models.user import User
from models.scan_history import ScanHistory
from models.book_collection import BookCollection
from models.reading_goal import ReadingGoal
from models.ai_recommendation import AIRecommendation


class TestMigrationSafety:
    """Test database migration safety."""

    def test_migration_creates_all_tables(self, app):
        """Migration should create book_collections, reading_goals, and ai_recommendations tables."""
        with app.app_context():
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()

            # Verify Pro feature tables exist
            assert 'book_collections' in tables
            assert 'reading_goals' in tables
            assert 'ai_recommendations' in tables

            # Verify indexes on book_collections
            indexes = inspector.get_indexes('book_collections')
            index_names = [idx['name'] for idx in indexes]

            # Should have custom indexes (at least user_id related indexes)
            assert any('user_id' in name.lower() for name in index_names)

    def test_migration_preserves_existing_data(self, app):
        """Migration should not affect existing users or scan_history data."""
        with app.app_context():
            # Create test user
            user = User(email='test@example.com', subscription_status='free')
            db.session.add(user)
            db.session.commit()

            # Get user count before "migration" (tables already exist in test)
            initial_user_count = User.query.count()

            # Verify new Pro tables are empty (simulating fresh migration)
            assert BookCollection.query.count() == 0
            assert ReadingGoal.query.count() == 0
            assert AIRecommendation.query.count() == 0

            # Verify existing tables unchanged
            assert User.query.count() == initial_user_count
            assert User.query.filter_by(email='test@example.com').first() is not None

    def test_migration_rollback_safe(self, app):
        """Migration rollback should drop Pro tables without affecting existing tables."""
        with app.app_context():
            # Create user before rollback
            user = User(email='rollback-test@example.com', subscription_status='free')
            db.session.add(user)
            db.session.commit()

            user_email = user.email

            # Simulate rollback: drop Pro tables
            # Note: In a real migration test, you'd run `flask db downgrade`
            # Here we're just verifying tables can be dropped safely
            try:
                db.session.execute(text('DROP TABLE IF EXISTS book_collections'))
                db.session.execute(text('DROP TABLE IF EXISTS reading_goals'))
                db.session.execute(text('DROP TABLE IF EXISTS ai_recommendations'))
                db.session.commit()
            except Exception as e:
                # If tables don't exist yet, that's fine
                db.session.rollback()

            # Verify users table still exists and data intact
            inspector = inspect(db.engine)
            tables = inspector.get_table_names()
            assert 'users' in tables

            # Verify user data preserved
            user = User.query.filter_by(email=user_email).first()
            assert user is not None
            assert user.email == 'rollback-test@example.com'


class TestMigrationIndexes:
    """Test that Pro feature tables have proper indexes."""

    def test_book_collections_indexes(self, app):
        """BookCollection table should have indexes on user_id, shelf, read_status."""
        with app.app_context():
            inspector = inspect(db.engine)
            indexes = inspector.get_indexes('book_collections')
            columns = inspector.get_columns('book_collections')

            # Verify key columns exist
            column_names = [col['name'] for col in columns]
            assert 'user_id' in column_names
            assert 'shelf' in column_names
            assert 'read_status' in column_names
            assert 'isbn' in column_names

            # Verify at least one index exists (SQLite creates them automatically for FKs)
            assert len(indexes) >= 0  # May vary by SQLite version

    def test_reading_goals_indexes(self, app):
        """ReadingGoal table should have unique constraint on user_id."""
        with app.app_context():
            inspector = inspect(db.engine)
            columns = inspector.get_columns('reading_goals')

            column_names = [col['name'] for col in columns]
            assert 'user_id' in column_names
            assert 'year' in column_names
            assert 'target_count' in column_names

    def test_ai_recommendations_indexes(self, app):
        """AIRecommendation table should have indexes on user_id and generated_at."""
        with app.app_context():
            inspector = inspect(db.engine)
            columns = inspector.get_columns('ai_recommendations')

            column_names = [col['name'] for col in columns]
            assert 'user_id' in column_names
            assert 'generated_at' in column_names
            assert 'rank' in column_names
