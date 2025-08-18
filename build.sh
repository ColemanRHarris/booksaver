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

# Download YOLO model if not present
python3 -c "
import os
if not os.path.exists('yolov8s.pt'):
    from ultralytics import YOLO
    model = YOLO('yolov8s.pt')  # This downloads the model
    print('YOLO model downloaded successfully')
else:
    print('YOLO model already exists')
"