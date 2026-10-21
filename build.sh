#!/bin/bash

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Database initialization
echo "Initializing database..."

# Ensure instance directory exists with proper permissions
mkdir -p instance
chmod 755 instance

# Set Flask app for migrations
export FLASK_APP=app.py

# Run database migrations with verbose output
echo "Running database migrations..."
echo "Current migration status:"
flask db current || echo "No current migration found"

echo "Attempting upgrade to head..."
flask db upgrade head
MIGRATION_EXIT_CODE=$?

if [ $MIGRATION_EXIT_CODE -eq 0 ]; then
    echo "✓ Database migrations completed successfully"
    echo "New migration status:"
    flask db current
else
    echo "⚠ Database migrations failed with exit code: $MIGRATION_EXIT_CODE"
    echo "Attempting to create tables directly..."
    python -c "from app import app, db; app.app_context().push(); db.create_all(); print('Tables created via db.create_all()')"
fi