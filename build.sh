#!/bin/bash

# Install system dependencies for Ubuntu/Render
apt-get update
apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-eng \
    ffmpeg \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgomp1

# Install Python dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Database initialization
echo "Initializing database..."

# Ensure instance directory exists with proper permissions
mkdir -p instance
chmod 755 instance

# Run database migrations
echo "Running database migrations..."
if flask db upgrade; then
    echo "✓ Database migrations completed successfully"
else
    echo "⚠ Database migrations failed or not needed"
    echo "  Tables will be auto-created on first app startup if needed"
fi

# YOLO models not currently used in production
# Book detection happens through OCR processing