"""
User service for managing user data in Redis.
Handles user registration, authentication, subscription tracking, and usage limits.
"""

import os
import json
import bcrypt
import redis
import secrets
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from core.logging_utils import get_safe_logger


class InMemoryRedis:
    """Simple in-memory Redis-like storage for local development."""
    
    def __init__(self):
        self._data = {}
        self._expiry = {}
    
    def hset(self, key: str, field: str = None, value: str = None, mapping: Dict[str, str] = None) -> int:
        """Set hash fields - supports both single field/value and mapping formats."""
        if key not in self._data:
            self._data[key] = {}
        
        if mapping:
            self._data[key].update(mapping)
            return len(mapping)
        elif field is not None and value is not None:
            self._data[key][field] = value
            return 1
        else:
            raise TypeError("Must provide either field/value or mapping")
    
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
        # Context-aware logger
        self.logger = get_safe_logger(__name__)
        
        if redis_client:
            # Use provided Redis client (from Flask app)
            self.redis_client = redis_client
            self.using_real_redis = True
            self.logger.info("✅ UserService using shared Redis client")
        else:
            # Fallback: create own Redis connection
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            try:
                if redis_url.startswith('memory://'):
                    redis_url = 'redis://localhost:6379'
                
                self.redis_client = redis.from_url(redis_url, decode_responses=True)
                self.redis_client.ping()  # Test connection
                self.using_real_redis = True
                self.logger.info(f"✅ UserService using Redis: {redis_url}")
            except Exception as e:
                # Only fall back to in-memory if Redis is truly unavailable
                self.logger.warning(f"⚠️ UserService Redis failed ({e}), using in-memory storage")
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
    
    def _get_reset_token_key(self, token: str) -> str:
        """Get Redis key for password reset token."""
        return f"reset_token:{token}"
    
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
            
            self.logger.info(f"✅ User registered: {email}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ User registration failed: {e}")
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
            self.logger.error(f"❌ User authentication failed: {e}")
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
            self.logger.error(f"❌ Failed to get user: {e}")
            return None
    
    def get_subscription(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user subscription data."""
        try:
            email = email.lower().strip()
            subscription_key = self._get_subscription_key(email)
            return self.redis_client.hgetall(subscription_key)
        except Exception as e:
            self.logger.error(f"❌ Failed to get subscription: {e}")
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
            
            self.logger.info(f"✅ Subscription updated for {email}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to update subscription: {e}")
            return False
    
    def get_daily_usage(self, email: str, date: str = None) -> int:
        """Get daily scan usage for user."""
        try:
            usage_key = self._get_usage_key(email, date)
            usage = self.redis_client.get(usage_key)
            return int(usage) if usage else 0
        except Exception as e:
            self.logger.error(f"❌ Failed to get usage: {e}")
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
            self.logger.error(f"❌ Failed to increment usage: {e}")
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
            self.logger.error(f"❌ Failed to check scan permission: {e}")
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
            self.logger.error(f"❌ Failed to add to history: {e}")
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
            self.logger.error(f"❌ Failed to get history: {e}")
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
            self.logger.error(f"❌ Failed to create session: {e}")
            return False
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session data."""
        try:
            session_key = self._get_session_key(session_id)
            return self.redis_client.hgetall(session_key)
        except Exception as e:
            self.logger.error(f"❌ Failed to get session: {e}")
            return None
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a user session."""
        try:
            session_key = self._get_session_key(session_id)
            self.redis_client.delete(session_key)
            return True
        except Exception as e:
            self.logger.error(f"❌ Failed to delete session: {e}")
            return False
    
    def create_password_reset_token(self, email: str) -> Optional[str]:
        """Create a secure password reset token for the user."""
        try:
            email = email.lower().strip()
            
            # Check if user exists
            user_key = self._get_user_key(email)
            if not self.redis_client.exists(user_key):
                self.logger.warning(f"⚠️ Password reset requested for non-existent user: {email}")
                return None
            
            # Generate cryptographically secure token
            raw_token = secrets.token_urlsafe(32)
            
            # Hash the token for storage (prevents token theft if Redis is compromised)
            token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
            
            # Store token data with 1 hour expiration
            token_data = {
                'email': email,
                'created_at': datetime.now(timezone.utc).isoformat(),
                'expires_at': (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            }
            
            token_key = self._get_reset_token_key(token_hash)
            self.redis_client.hset(token_key, mapping=self._ensure_string_values(token_data))
            self.redis_client.expire(token_key, 3600)  # 1 hour
            
            self.logger.info(f"✅ Password reset token created for {email}")
            return raw_token  # Return unhashed token for email
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create reset token: {e}")
            return None
    
    def validate_reset_token(self, token: str) -> Optional[str]:
        """Validate a password reset token and return the associated email."""
        try:
            if not token:
                return None
            
            # Hash the provided token to match stored hash
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            token_key = self._get_reset_token_key(token_hash)
            
            # Get token data
            token_data = self.redis_client.hgetall(token_key)
            if not token_data:
                return None
            
            # Check if token has expired
            expires_at = datetime.fromisoformat(token_data['expires_at'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                # Clean up expired token
                self.redis_client.delete(token_key)
                return None
            
            return token_data['email']
            
        except Exception as e:
            self.logger.error(f"❌ Failed to validate reset token: {e}")
            return None
    
    def reset_password_with_token(self, token: str, new_password: str) -> bool:
        """Reset user's password using a valid reset token."""
        try:
            # Validate token and get email
            email = self.validate_reset_token(token)
            if not email:
                return False
            
            # Hash the provided token to get the key
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            token_key = self._get_reset_token_key(token_hash)
            
            # Update user password
            user_key = self._get_user_key(email)
            new_password_hash = self._hash_password(new_password)
            
            self.redis_client.hset(user_key, 'password_hash', new_password_hash)
            self.redis_client.hset(user_key, 'password_updated_at', datetime.now(timezone.utc).isoformat())
            
            # Delete the used token (one-time use)
            self.redis_client.delete(token_key)
            
            self.logger.info(f"✅ Password reset successful for {email}")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to reset password: {e}")
            return False
    
    def cleanup_expired_reset_tokens(self) -> int:
        """Clean up expired password reset tokens (maintenance method)."""
        try:
            # This would be called periodically by a background job
            # Redis TTL should handle most cleanup automatically
            cleaned = 0
            # Implementation could scan for reset_token:* keys and check expiration
            self.logger.info(f"🧹 Cleaned up {cleaned} expired reset tokens")
            return cleaned
        except Exception as e:
            self.logger.error(f"❌ Failed to cleanup reset tokens: {e}")
            return 0


# Global user service instance - will be initialized with app context
user_service = None


def get_user_service() -> UserService:
    """Get the user service instance, creating it if needed."""
    global user_service
    if user_service is None:
        # Try to get Redis client from Flask app context
        try:
            from flask import current_app
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
        except (ImportError, RuntimeError):
            # ImportError: Flask not available
            # RuntimeError: Working outside of application context
            # Fallback to standalone UserService
            user_service = UserService()
    
    return user_service


def initialize_user_service_with_app(app):
    """Initialize user service with Flask app context."""
    global user_service
    with app.app_context():
        user_service = get_user_service()
        app.logger.info("🔧 UserService initialized with app context")