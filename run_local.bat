@echo off
REM BookSaver Local Development Runner for Windows
REM This script sets up the environment for local testing

echo 🚀 Starting BookSaver in Local Testing Mode
echo ==========================================

REM Check if .env file exists
if not exist .env (
    echo ⚠️  No .env file found. Creating from .env.example...
    if exist .env.example (
        copy .env.example .env > nul
        echo ✅ Created .env from .env.example
        echo 📝 Please edit .env to add your API keys before running again
        pause
        exit /b 1
    ) else (
        echo ❌ No .env.example found. Please create a .env file manually.
        pause
        exit /b 1
    )
)

echo 🔍 Checking environment configuration...

REM Set local testing defaults
set LOCAL_TESTING=true
set FLASK_ENV=development
set FLASK_DEBUG=1
set REDIS_URL=

echo ✅ Environment configured for local testing
echo    LOCAL_TESTING=true (forces in-memory storage)
echo    FLASK_ENV=development
echo    REDIS_URL= (empty - using in-memory storage)
echo.

REM Check if Python virtual environment exists
if not exist venv\ (
    if not exist .venv\ (
        echo 📦 No virtual environment found. Creating one...
        python -m venv venv
        echo ✅ Virtual environment created at .\venv
        echo    Activate it with: venv\Scripts\activate
        echo    Then install dependencies: pip install -r requirements.txt
        echo.
    )
)

REM Try to activate virtual environment
if exist venv\Scripts\activate.bat (
    echo 🐍 Activating virtual environment...
    call venv\Scripts\activate.bat
    echo ✅ Virtual environment activated
) else if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
    echo ✅ Virtual environment activated
) else (
    echo ❌ Could not find virtual environment. Please create and activate one:
    echo    python -m venv venv
    echo    venv\Scripts\activate
    echo    pip install -r requirements.txt
    pause
    exit /b 1
)

REM Check if dependencies are installed
echo 📋 Checking Python dependencies...
python -c "import flask" 2>nul || (
    echo ⚠️  Flask not installed. Installing dependencies...
    pip install -r requirements.txt
    echo ✅ Dependencies installed
)

echo.
echo 🎯 Configuration Summary:
echo    Mode: Local Testing (in-memory storage)
echo    Debug: Enabled
echo    Redis: Disabled (using in-memory alternatives)
echo    Port: %PORT% (default: 5000)
echo.

REM Create flask_session directory if it doesn't exist
if not exist flask_session mkdir flask_session

echo 🚀 Starting Flask development server...
echo    Access the app at: http://localhost:5000
echo    Press Ctrl+C to stop
echo.

REM Start the Flask app
python app.py

pause