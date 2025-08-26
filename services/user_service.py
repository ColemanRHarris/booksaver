"""
User service for managing user data in Redis.
Handles user registration, authentication, subscription tracking, and usage limits.
"""

import os
import json
import bcrypt
import redis
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from flask import current_app


class InMemoryRedis:
    """Simple in-memory Redis-like storage for local development."""
    
    def __init__(self):
        self._data = {}
        self._expiry = {}
    
    def hset(self, key: str, mapping: Dict[str, str]) -> int:
        """Set hash fields."""
        if key not in self._data:
            self._data[key] = {}
        self._data[key].update(mapping)
        return len(mapping)
    
    def hgetall(self, key: str) -> Dict[str, str]:
        """Get all hash fields."""
        return self._data.get(key, {}).copy()
    
    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        if key in self._expiry and datetime.now(timezone.utc).timestamp() > self._expiry[key]:
            del self._data[key]
            del self._expiry[key]
            return False
        return key in self._data
    
    def get(self, key: str) -> Optional[str]:
        """Get string value."""
        if not self.exists(key):
            return None
        return self._data.get(key)
    
    def incr(self, key: str) -> int:
        """Increment integer value."""
        current_val = self.get(key)
        new_val = (int(current_val) if current_val else 0) + 1
        self._data[key] = str(new_val)
        return new_val
    
    def expire(self, key: str, seconds: int) -> bool:
        """Set expiration time."""
        if key in self._data:
            self._expiry[key] = datetime.now(timezone.utc).timestamp() + seconds
            return True
        return False
    
    def lpush(self, key: str, value: str) -> int:
        """Push to left of list."""
        if key not in self._data:
            self._data[key] = []
        self._data[key].insert(0, value)
        return len(self._data[key])
    
    def ltrim(self, key: str, start: int, end: int) -> bool:
        """Trim list to range."""
        if key in self._data and isinstance(self._data[key], list):
            self._data[key] = self._data[key][start:end+1]
            return True
        return False
    
    def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get range from list."""
        if key not in self._data or not isinstance(self._data[key], list):
            return []
        
        if end == -1:
            return self._data[key][start:]
        return self._data[key][start:end+1]
    
    def delete(self, key: str) -> int:
        """Delete key."""
        deleted = 0
        if key in self._data:
            del self._data[key]
            deleted += 1
        if key in self._expiry:
            del self._expiry[key]
        return deleted


class UserService:
    def __init__(self, redis_client=None):
        """Initialize Redis connection using provided client or create new one."""
        if redis_client:
            # Use provided Redis client (from Flask app)
            self.redis_client = redis_client
            self.using_real_redis = True
            current_app.logger.info("✅ UserService using shared Redis client")
        else:
            # Fallback: create own Redis connection
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            try:
                if redis_url.startswith('memory://'):
                    redis_url = 'redis://localhost:6379'
                
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()  # Test connection
                self.using_real_redis = True
                current_app.logger.info(f"✅ UserService using Redis: {redis_url}")
            except Exception as e:
                # Only fall back to in-memory if Redis is truly unavailable
                current_app.logger.warning(f"⚠️ UserService Redis failed ({e}), using in-memory storage")
                self.redis_client = InMemoryRedis()
                self.using_real_redis = False
    
    def _hash_password(self, password: str) -> str:
        """Hash password using bcrypt."""
        return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    def _verify_password(self, password: str, hashed: str) -> bool:
        """Verify password against hash."""
        return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))
    
    def _get_user_key(self, email: str) -> str:
        """Get Redis key for user data."""
        return f"user:{email.lower()}"
    
    def _get_subscription_key(self, email: str) -> str:
        """Get Redis key for subscription data."""
        return f"subscription:{email.lower()}"
    
    def _get_usage_key(self, email: str, date: str = None) -> str:
        """Get Redis key for daily usage tracking."""
        if date is None:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        return f"usage:{email.lower()}:{date}"
    
    def _get_history_key(self, email: str) -> str:
        """Get Redis key for scan history."""
        return f"history:{email.lower()}"
    
    def _ensure_string_values(self, data: Dict[str, Any]) -> Dict[str, str]:
        """Convert all values in dict to strings for Redis compatibility."""
        string_data = {}
        for key, value in data.items():
            if value is None:
                string_data[key] = ''
            elif isinstance(value, bool):
                string_data[key] = 'true' if value else 'false'
            elif isinstance(value, (int, float)):
                string_data[key] = str(value)
            else:
                string_data[key] = str(value)
        return string_data
    
    def _get_session_key(self, session_id: str) -> str:
        """Get Redis key for session data."""
        return f"session:{session_id}"
    
    def register_user(self, email: str, password: str) -> bool:
        """Register a new user."""
        try:
            email = email.lower().strip()
            user_key = self._get_user_key(email)
            
            # Check if user already exists
            if self.redis_client.exists(user_key):
                return False
            
            # Create user data
            user_data = {
                'email': email,
                'password_hash': self._hash_password(password),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'subscription_tier': 'free',
                'is_active': True
            }
            
            # Store user data in Redis - ensure all values are strings
            self.redis_client.hset(user_key, mapping=self._ensure_string_values(user_data))
            
            # Initialize subscription data
            subscription_data = {
                'tier': 'free',
                'status': 'active',
                'created_at': datetime.now(timezone.utc).isoformat(),
                'stripe_customer_id': '',
                'stripe_subscription_id': ''
            }
            self.redis_client.hset(self._get_subscription_key(email), mapping=self._ensure_string_values(subscription_data))
            
            current_app.logger.info(f"✅ User registered: {email}")
            return True
            
        except Exception as e:
            current_app.logger.error(f"❌ User registration failed: {e}")
            return False
    
    def authenticate_user(self, email: str, password: str) -> Optional[Dict[str, Any]]:
        """Authenticate user and return user data if successful."""
        try:
            email = email.lower().strip()
            user_key = self._get_user_key(email)
            
            # Get user data
            user_data = self.redis_client.hgetall(user_key)
            if not user_data:
                return None
            
            # Verify password
            if not self._verify_password(password, user_data['password_hash']):
                return None
            
            # Check if user is active
            if not user_data.get('is_active', 'false').lower() == 'true':
                return None
            
            # Remove password hash from returned data
            user_data.pop('password_hash', None)
            return user_data
            
        except Exception as e:
            current_app.logger.error(f"❌ User authentication failed: {e}")
            return None
    
    def get_user(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user data without authentication."""
        try:
            email = email.lower().strip()
            user_key = self._get_user_key(email)
            user_data = self.redis_client.hgetall(user_key)
            
            if not user_data:
                return None
            
            # Remove sensitive data
            user_data.pop('password_hash', None)
            return user_data
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to get user: {e}")
            return None
    
    def get_subscription(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user subscription data."""
        try:
            email = email.lower().strip()
            subscription_key = self._get_subscription_key(email)
            return self.redis_client.hgetall(subscription_key)
        except Exception as e:
            current_app.logger.error(f"❌ Failed to get subscription: {e}")
            return None
    
    def update_subscription(self, email: str, subscription_data: Dict[str, Any]) -> bool:
        """Update user subscription data."""
        try:
            email = email.lower().strip()
            subscription_key = self._get_subscription_key(email)
            
            # Add updated_at timestamp
            subscription_data['updated_at'] = datetime.now(timezone.utc).isoformat()
            
            # Ensure all values are strings for Redis
            self.redis_client.hset(subscription_key, mapping=self._ensure_string_values(subscription_data))
            
            # Also update subscription_tier in user data
            if 'tier' in subscription_data:
                user_key = self._get_user_key(email)
                self.redis_client.hset(user_key, 'subscription_tier', subscription_data['tier'])
            
            current_app.logger.info(f"✅ Subscription updated for {email}")
            return True
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to update subscription: {e}")
            return False
    
    def get_daily_usage(self, email: str, date: str = None) -> int:
        """Get daily scan usage for user."""
        try:
            usage_key = self._get_usage_key(email, date)
            usage = self.redis_client.get(usage_key)
            return int(usage) if usage else 0
        except Exception as e:
            current_app.logger.error(f"❌ Failed to get usage: {e}")
            return 0
    
    def increment_usage(self, email: str) -> int:
        """Increment daily usage and return new count."""
        try:
            email = email.lower().strip()
            usage_key = self._get_usage_key(email)
            
            # Increment with expiration (reset at midnight UTC)
            count = self.redis_client.incr(usage_key)
            
            # Set expiration to end of day if this is the first increment
            if count == 1:
                # Calculate seconds until end of day (midnight UTC)
                now = datetime.now(timezone.utc)
                tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                seconds_until_midnight = int((tomorrow - now).total_seconds())
                self.redis_client.expire(usage_key, seconds_until_midnight)
            
            return count
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to increment usage: {e}")
            return 0
    
    def can_scan(self, email: str) -> bool:
        """Check if user can perform a scan based on their subscription and usage."""
        try:
            subscription = self.get_subscription(email)
            if not subscription:
                return False
            
            # Premium users have unlimited scans
            if subscription.get('tier') == 'premium':
                return True
            
            # Free users are limited to 1 scan per day
            daily_usage = self.get_daily_usage(email)
            return daily_usage < 1
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to check scan permission: {e}")
            return False
    
    def add_to_history(self, email: str, scan_result: Dict[str, Any]) -> bool:
        """Add scan result to user's history (premium feature)."""
        try:
            subscription = self.get_subscription(email)
            if not subscription or subscription.get('tier') != 'premium':
                return False
            
            email = email.lower().strip()
            history_key = self._get_history_key(email)
            
            # Add timestamp to scan result
            scan_result['scanned_at'] = datetime.now(timezone.utc).isoformat()
            
            # Add to list (newest first)
            self.redis_client.lpush(history_key, json.dumps(scan_result))
            
            # Keep only last 100 scans
            self.redis_client.ltrim(history_key, 0, 99)
            
            return True
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to add to history: {e}")
            return False
    
    def get_history(self, email: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get user's scan history (premium feature)."""
        try:
            subscription = self.get_subscription(email)
            if not subscription or subscription.get('tier') != 'premium':
                return []
            
            email = email.lower().strip()
            history_key = self._get_history_key(email)
            
            # Get recent scans
            history_items = self.redis_client.lrange(history_key, 0, limit - 1)
            
            return [json.loads(item) for item in history_items]
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to get history: {e}")
            return []
    
    def create_session(self, session_id: str, email: str, expires_in_hours: int = 24) -> bool:
        """Create a user session."""
        try:
            session_key = self._get_session_key(session_id)
            session_data = {
                'email': email.lower().strip(),
                'created_at': datetime.now(timezone.utc).isoformat(),
                'expires_at': (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat()
            }
            
            # Store session with expiration
            self.redis_client.hset(session_key, mapping=session_data)
            self.redis_client.expire(session_key, expires_in_hours * 3600)
            
            return True
            
        except Exception as e:
            current_app.logger.error(f"❌ Failed to create session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data."""
        try:
            session_key = self._get_session_key(session_id)
            return self.redis_client.hgetall(session_key)
        except Exception as e:
            current_app.logger.error(f"❌ Failed to get session: {e}")
            return None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a user session."""
        try:
            session_key = self._get_session_key(session_id)
            self.redis_client.delete(session_key)
            return True
        except Exception as e:
            current_app.logger.error(f"❌ Failed to delete session: {e}")
            return False


# Global user service instance - will be initialized with app context
user_service = None


def get_user_service() -> UserService:
    """Get the user service instance, creating it if needed."""
    global user_service
    if user_service is None:
        # Try to get Redis client from Flask app context
        from flask import current_app
        try:
            # Use the same Redis client as Flask-Session if available
            if hasattr(current_app, 'config') and current_app.config.get('SESSION_TYPE') == 'redis':
                session_redis = current_app.config.get('SESSION_REDIS')
                if session_redis:
                    # Create user Redis client from session Redis (with decode_responses=True)
                    import redis
                    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                    user_redis = redis.from_url(redis_url, decode_responses=True)
                    user_service = UserService(user_redis)
                else:
                    user_service = UserService()
            else:
                user_service = UserService()
        except Exception:
            # Fallback if no app context
            user_service = UserService()
    
    return user_service


def initialize_user_service_with_app(app):
    """Initialize user service with Flask app context."""
    global user_service
    with app.app_context():
        user_service = get_user_service()
        app.logger.info("🔧 UserService initialized with app context")