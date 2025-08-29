# Local Testing Guide

This guide helps you run BookSaver locally for development and testing without requiring external Redis servers.

## Quick Start (Recommended)

### Option 1: Test the Fix First (Recommended)

```bash
python test_redis_fix.py
```

This will verify that all Redis-related services can initialize properly without errors.

### Option 2: Use the Local Testing Scripts

**On macOS/Linux:**
```bash
./run_local.sh
```

**On Windows:**
```cmd
run_local.bat
```

These scripts will:
- Create a `.env` file from `.env.example` if needed
- Set up a Python virtual environment if needed
- Install dependencies
- Configure the app for local testing mode
- Start the development server

### Option 2: Manual Setup

1. **Create Environment File:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` file:**
   ```bash
   # Required: Add your Gemini API key
   GEMINI_API_KEY=your_actual_api_key_here
   
   # Local testing mode (forces in-memory storage)
   LOCAL_TESTING=true
   
   # Leave Redis URL empty for in-memory storage
   REDIS_URL=
   
   # Development settings
   FLASK_ENV=development
   FLASK_DEBUG=1
   ```

3. **Set up Python Environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Run the Application:**
   ```bash
   python app.py
   ```

## Configuration Options

### Environment Variables for Local Testing

| Variable | Recommended Value | Description |
|----------|-------------------|-------------|
| `LOCAL_TESTING` | `true` | Forces in-memory storage for all services |
| `REDIS_URL` | `` (empty) | Use in-memory storage instead of Redis |
| `FLASK_ENV` | `development` | Enables debug mode and detailed logging |
| `FLASK_DEBUG` | `1` | Enables auto-reload on code changes |
| `GEMINI_API_KEY` | `your_key` | **Required** for book detection |

### Optional Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | Auto-generated | Flask session security (change for production) |
| `PORT` | `5000` | Port to run the development server |
| `GOOGLE_BOOKS_KEY` | None | Enhanced book search (optional) |

## What LOCAL_TESTING=true Does

When `LOCAL_TESTING=true` is set:

1. **Bypasses all Redis connections** - No need to install or run Redis server
2. **Uses in-memory storage** for:
   - User sessions (filesystem fallback)
   - User data and authentication
   - Scan history
   - Rate limiting
   - Task results
3. **Uses threading** instead of Celery for image processing
4. **Provides detailed logging** for debugging

## Troubleshooting

### Common Issues

**Error: `Redis URL must specify one of the following schemes`**
- Solution: Set `REDIS_URL=` (empty) or `LOCAL_TESTING=true` in your `.env` file

**Error: `GEMINI_API_KEY not found`**
- Solution: Get API key from [Google AI Studio](https://makersuite.google.com/app/apikey)
- Add it to your `.env` file: `GEMINI_API_KEY=your_actual_key_here`

**Error: `ModuleNotFoundError: No module named 'flask'`**
- Solution: Activate virtual environment and install dependencies:
  ```bash
  source venv/bin/activate  # or venv\Scripts\activate on Windows
  pip install -r requirements.txt
  ```

**Images not processing**
- Check that you have a valid `GEMINI_API_KEY` in your `.env` file
- Ensure `LOCAL_TESTING=true` to use threading instead of Celery
- Look for error messages in the console output

### Logs to Check

The app provides detailed logging when running locally:
- `🔧 LOCAL_TESTING=true, forcing in-memory storage`
- `✅ UserService using in-memory storage`
- `🔧 Flask-Limiter using in-memory storage for local development`
- `⚠️ Redis unavailable (...), configuring filesystem sessions`

## Testing Features

### What Works in Local Mode
- ✅ Book scanning and AI detection
- ✅ User registration and login
- ✅ Premium subscriptions (with Stripe keys)
- ✅ Scan history for premium users
- ✅ Export functionality
- ✅ Your Library page
- ✅ All UI features

### Limitations in Local Mode
- ⚠️ No persistent data (restarts clear all data)
- ⚠️ Single-threaded image processing (slower than production)
- ⚠️ No background task queuing
- ⚠️ Email functionality requires SMTP configuration

## Production vs Local

| Feature | Local Testing | Production |
|---------|---------------|------------|
| Data Storage | In-Memory | Redis |
| Sessions | Filesystem | Redis |
| Task Processing | Threading | Celery + Redis |
| Rate Limiting | In-Memory | Redis |
| Data Persistence | No | Yes |

## Next Steps

After local testing works:
1. Test with local Redis server: `REDIS_URL=redis://localhost:6379`
2. Set up Stripe test keys for subscription testing
3. Configure SMTP for password reset testing
4. Deploy to production environment