#!/usr/bin/env python3
"""
Simple script to start Celery worker for development
Run this in a separate terminal: python start_celery.py
"""

import subprocess
import sys
import os

def start_celery_worker():
    """Start Celery worker with filesystem broker"""
    cmd = [
        sys.executable, '-m', 'celery', 
        '-A', 'celery_app', 
        'worker', 
        '--loglevel=info',
        '--concurrency=1'  # Single worker for development
    ]
    
    print("Starting Celery worker...")
    print("Command:", ' '.join(cmd))
    print("Make sure the Flask app is running on another terminal!")
    print("-" * 50)
    
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print("\nStopping Celery worker...")
    except subprocess.CalledProcessError as e:
        print(f"Error starting Celery worker: {e}")
        sys.exit(1)

if __name__ == '__main__':
    start_celery_worker()