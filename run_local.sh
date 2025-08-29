#!/bin/bash

# BookSaver Local Development Runner
# This script sets up the environment for local testing

echo "🚀 Starting BookSaver in Local Testing Mode"
echo "=========================================="

# Check if .env file exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Creating from .env.example..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "✅ Created .env from .env.example"
        echo "📝 Please edit .env to add your API keys before running again"
        exit 1
    else
        echo "❌ No .env.example found. Please create a .env file manually."
        exit 1
    fi
fi

# Check for required environment variables
echo "🔍 Checking environment configuration..."

# Load .env file
set -a
source .env
set +a

# Check critical variables
if [ -z "$GEMINI_API_KEY" ] || [ "$GEMINI_API_KEY" = "your_gemini_api_key_here" ]; then
    echo "⚠️  GEMINI_API_KEY is not configured. Book detection will not work."
    echo "   Get your key from: https://console.cloud.google.com/apis/credentials"
fi

if [ -z "$SECRET_KEY" ] || [ "$SECRET_KEY" = "your-secret-key-here-change-in-production" ]; then
    echo "⚠️  SECRET_KEY is using default value. This is insecure."
    echo "   Please set a unique secret key in your .env file"
fi

# Set local testing defaults
export LOCAL_TESTING=true
export FLASK_ENV=development
export FLASK_DEBUG=1
export REDIS_URL=""

echo "✅ Environment configured for local testing"
echo "   LOCAL_TESTING=true (forces in-memory storage)"
echo "   FLASK_ENV=development"
echo "   REDIS_URL= (empty - using in-memory storage)"
echo ""

# Check if Python virtual environment exists
if [ ! -d "venv" ] && [ ! -d ".venv" ]; then
    echo "📦 No virtual environment found. Creating one..."
    python3 -m venv venv
    echo "✅ Virtual environment created at ./venv"
    echo "   Activate it with: source venv/bin/activate"
    echo "   Then install dependencies: pip install -r requirements.txt"
    echo ""
fi

# Check if we're in a virtual environment
if [ -z "$VIRTUAL_ENV" ]; then
    echo "⚠️  Not in a virtual environment. Attempting to activate..."
    if [ -d "venv" ]; then
        source venv/bin/activate
        echo "✅ Activated virtual environment"
    elif [ -d ".venv" ]; then
        source .venv/bin/activate
        echo "✅ Activated virtual environment"
    else
        echo "❌ Could not find virtual environment. Please create and activate one:"
        echo "   python3 -m venv venv"
        echo "   source venv/bin/activate"
        echo "   pip install -r requirements.txt"
        exit 1
    fi
fi

# Check if dependencies are installed
echo "📋 Checking Python dependencies..."
if ! python -c "import flask" 2>/dev/null; then
    echo "⚠️  Flask not installed. Installing dependencies..."
    pip install -r requirements.txt
    echo "✅ Dependencies installed"
fi

echo ""
echo "🎯 Configuration Summary:"
echo "   Mode: Local Testing (in-memory storage)"
echo "   Debug: Enabled"
echo "   Redis: Disabled (using in-memory alternatives)"
echo "   Port: ${PORT:-5000}"
echo ""

# Create flask_session directory if it doesn't exist
mkdir -p flask_session

echo "🚀 Starting Flask development server..."
echo "   Access the app at: http://localhost:${PORT:-5000}"
echo "   Press Ctrl+C to stop"
echo ""

# Start the Flask app
python app.py