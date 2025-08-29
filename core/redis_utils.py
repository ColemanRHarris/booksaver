"""
Redis utilities for BookSaver application.
Handles Redis URL validation, connection management, and local testing support.
"""

import os
import redis
from typing import Optional, Tuple
from core.logging_utils import get_safe_logger

logger = get_safe_logger(__name__)


def is_local_testing_mode() -> bool:
    """Check if we're in local testing mode."""
    return os.getenv('LOCAL_TESTING', '').lower() in ('true', '1', 'yes')


def is_valid_redis_url(url: str) -> bool:
    """Check if a URL has a valid Redis scheme."""
    if not url:
        return False
    return url.startswith(('redis://', 'rediss://', 'unix://'))


def should_use_redis() -> bool:
    """
    Determine if Redis should be used based on environment configuration.
    
    Returns:
        bool: True if Redis should be used, False if in-memory storage should be used
    """
    # Force in-memory mode if LOCAL_TESTING is enabled
    if is_local_testing_mode():
        logger.info("🧪 LOCAL_TESTING=true, forcing in-memory storage")
        return False
    
    redis_url = os.getenv('REDIS_URL')
    
    # No Redis URL configured
    if not redis_url:
        logger.info("🔧 No REDIS_URL configured, using in-memory storage")
        return False
    
    # Skip memory:// URLs (legacy configuration)
    if redis_url.startswith('memory://'):
        logger.info("🔧 REDIS_URL=memory://, using in-memory storage")
        return False
    
    # Invalid Redis URL scheme
    if not is_valid_redis_url(redis_url):
        logger.warning(f"⚠️ Invalid REDIS_URL scheme: {redis_url}, using in-memory storage")
        return False
    
    return True


def get_redis_client(decode_responses: bool = True) -> Tuple[Optional[redis.Redis], bool]:
    """
    Get a Redis client if Redis should be used, otherwise return None.
    
    Args:
        decode_responses: Whether to decode Redis responses to strings
        
    Returns:
        Tuple of (redis_client, is_using_redis):
        - redis_client: Redis client instance or None
        - is_using_redis: True if using real Redis, False if should use in-memory
    """
    if not should_use_redis():
        return None, False
    
    redis_url = os.getenv('REDIS_URL')
    
    try:
        client = redis.from_url(redis_url, decode_responses=decode_responses)
        # Test connection
        client.ping()
        logger.info(f"✅ Redis connection successful: {redis_url[:50]}...")
        return client, True
    except Exception as e:
        logger.warning(f"⚠️ Redis connection failed ({e}), falling back to in-memory storage")
        return None, False


def get_redis_url_for_external_services() -> Optional[str]:
    """
    Get Redis URL for external services like Celery, Flask-Limiter, etc.
    Returns None if Redis shouldn't be used.
    """
    if not should_use_redis():
        return None
    
    redis_url = os.getenv('REDIS_URL')
    if is_valid_redis_url(redis_url):
        return redis_url
    
    return None


def log_redis_configuration():
    """Log the current Redis configuration for debugging."""
    redis_url = os.getenv('REDIS_URL', 'Not set')
    local_testing = is_local_testing_mode()
    will_use_redis = should_use_redis()
    
    logger.info("🔧 Redis Configuration:")
    logger.info(f"   REDIS_URL: {redis_url}")
    logger.info(f"   LOCAL_TESTING: {local_testing}")
    logger.info(f"   Will use Redis: {will_use_redis}")
    
    if will_use_redis:
        client, success = get_redis_client()
        if success:
            logger.info("   ✅ Redis connection test: SUCCESS")
        else:
            logger.info("   ❌ Redis connection test: FAILED")


# For backwards compatibility
def configure_redis_for_service(service_name: str, decode_responses: bool = True):
    """
    Configure Redis for a specific service with proper fallback.
    
    Args:
        service_name: Name of the service for logging
        decode_responses: Whether to decode responses
        
    Returns:
        Tuple of (redis_client_or_none, is_using_redis)
    """
    client, is_redis = get_redis_client(decode_responses=decode_responses)
    
    if is_redis:
        logger.info(f"✅ {service_name} using Redis")
    else:
        logger.info(f"🔧 {service_name} using in-memory storage")
    
    return client, is_redis