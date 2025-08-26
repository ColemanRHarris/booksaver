# Application Context Fix for Celery Workers

## Problem Description

The application was experiencing "Working outside of application context" errors on Render deployment with error pattern:

```
[2025-08-26 14:15:59,315] ERROR in tasks: Image processing failed: Working outside of application context.
```

### Root Cause Analysis

1. **Flask Context Dependency**: Services (`image_storage.py`, `user_service.py`, `stripe_service.py`) used `current_app.logger` which requires Flask application context
2. **Celery Worker Isolation**: Celery workers run in separate processes without Flask application context initialized
3. **Context Mismatch**: When Celery tasks called these services, Flask's `current_app` was not available

## Solution: Context-Aware Logging

### Architecture Changes

**Before (Problematic)**:
```python
from flask import current_app

# This fails in Celery workers
current_app.logger.info("Message")  # ❌ RuntimeError: Working outside of application context
```

**After (Fixed)**:
```python
from core.logging_utils import get_safe_logger

class MyService:
    def __init__(self):
        self.logger = get_safe_logger(__name__)  # ✅ Works in both contexts
    
    def my_method(self):
        self.logger.info("Message")  # ✅ Safe in Flask and Celery
```

### Implementation Details

#### 1. Context-Aware Logger Utility (`core/logging_utils.py`)

**Key Features:**
- **Automatic Context Detection**: Tries Flask's `current_app.logger` first, falls back to standalone logger
- **Consistent Formatting**: Same log format in both Flask and Celery contexts
- **Error Handling**: Gracefully handles `ImportError` and `RuntimeError` exceptions
- **Performance**: Minimal overhead with cached logger instances

```python
class ContextAwareLogger:
    def _get_logger(self):
        try:
            from flask import current_app
            if current_app:
                return current_app.logger  # Use Flask logger when available
        except (ImportError, RuntimeError):
            pass  # Fall back to standalone logger
        
        return self._standalone_logger
```

#### 2. Service Updates

**Updated Services:**
- `services/image_storage.py` - 15 logger calls converted
- `services/user_service.py` - 15 logger calls converted  
- `services/stripe_service.py` - 50+ logger calls converted

**Pattern Used:**
```python
class SomeService:
    def __init__(self):
        # Replace: self.current_app dependency
        # With: self.logger = get_safe_logger(__name__)
        self.logger = get_safe_logger(__name__)
    
    def some_method(self):
        # Replace: current_app.logger.info("message")
        # With: self.logger.info("message")
        self.logger.info("message")
```

#### 3. Graceful Flask Integration

The `get_user_service()` function was updated to handle context errors gracefully:

```python
def get_user_service() -> UserService:
    try:
        from flask import current_app
        # Try to use Flask context when available
        # ... Flask integration logic ...
    except (ImportError, RuntimeError):
        # Fall back to standalone service for Celery workers
        return UserService()
```

### Benefits

✅ **Eliminates Context Errors**: Services work in both Flask routes and Celery workers  
✅ **No Functionality Loss**: Same logging behavior, just context-safe  
✅ **Consistent Format**: Identical log format across all contexts  
✅ **Performance**: Minimal overhead with smart context detection  
✅ **Future-Proof**: Prevents similar issues with other Flask-dependent code  
✅ **Clean Architecture**: Better separation between web and background processing  

### Compatibility

**Flask Routes**: Continue to use Flask's built-in logger when available  
**Celery Workers**: Automatically use standalone logging without Flask dependency  
**Local Development**: Works with both threading and Celery execution modes  
**Production**: Resolves Render deployment container isolation issues  

### Testing Results

```bash
✅ All services import successfully without Flask context
✅ Context-aware logger works in standalone mode
✅ Service instantiation succeeds without Flask context  
✅ Logging calls work correctly in both contexts
✅ Tasks module imports without Flask dependencies
```

## Files Modified

1. `core/logging_utils.py` - ✨ **NEW** Context-aware logging utility
2. `services/image_storage.py` - Replaced `current_app.logger` with `self.logger`
3. `services/user_service.py` - Replaced `current_app.logger` with `self.logger`  
4. `services/stripe_service.py` - Replaced 50+ `current_app.logger` calls with `self.logger`

## Deployment Instructions

1. **Deploy the updated code** to Render (no configuration changes needed)
2. **Monitor logs** for absence of "Working outside of application context" errors
3. **Verify functionality** - all logging should continue working normally in both Flask routes and Celery workers

The fix maintains full backward compatibility while eliminating the Flask context dependency that was causing Celery worker failures.