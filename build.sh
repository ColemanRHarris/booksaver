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

# YOLO models not currently used in production
# Book detection happens through OCR processing