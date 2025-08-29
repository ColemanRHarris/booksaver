"""
Redis-based image storage service for sharing images between web and worker processes.
Solves the file system isolation issue in containerized deployments like Render.
"""

import os
import base64
import tempfile
import uuid
import mimetypes
from typing import Optional, Dict, Any
from datetime import timedelta, datetime, timezone
import redis
from core.logging_utils import get_safe_logger
from core.redis_utils import configure_redis_for_service


class InMemoryPipeline:
    """Mock Redis pipeline for in-memory storage."""
    
    def __init__(self, storage):
        self.storage = storage
        self.operations = []
    
    def hset(self, key: str, mapping: dict = None, **kwargs):
        """Queue hash set operation."""
        if mapping:
            self.operations.append(('hset', key, mapping))
        elif kwargs:
            self.operations.append(('hset', key, kwargs))
        return self
    
    def expire(self, key: str, ttl: int):
        """Queue expiration operation."""
        self.operations.append(('expire', key, ttl))
        return self
    
    def execute(self):
        """Execute all queued operations."""
        results = []
        for op_type, key, *args in self.operations:
            if op_type == 'hset':
                mapping = args[0]
                results.append(self.storage._hset_direct(key, mapping))
            elif op_type == 'expire':
                ttl = args[0]
                results.append(self.storage._expire_direct(key, ttl))
        self.operations.clear()
        return results


class InMemoryImageStorage:
    """In-memory image storage for local testing with Redis-compatible interface."""
    
    def __init__(self):
        # Support both regular keys and hash keys
        self._storage = {}  # key -> value (for regular keys)
        self._hashes = {}   # key -> {field: value} (for hash keys)
        self._expiry = {}   # key -> expires_at datetime
        self.logger = get_safe_logger(__name__)
        self.logger.info("🔧 InMemoryImageStorage initialized for local testing")
    
    def _is_expired(self, key: str) -> bool:
        """Check if a key is expired."""
        if key in self._expiry:
            return datetime.now(timezone.utc) > self._expiry[key]
        return False
    
    def _cleanup_expired_key(self, key: str):
        """Remove expired key from all storages."""
        if self._is_expired(key):
            self._storage.pop(key, None)
            self._hashes.pop(key, None)
            self._expiry.pop(key, None)
            return True
        return False
    
    # Redis-compatible methods
    def pipeline(self):
        """Create a pipeline for batched operations."""
        return InMemoryPipeline(self)
    
    def hset(self, key: str, mapping: dict = None, **kwargs):
        """Set hash fields."""
        if mapping:
            data = mapping
        else:
            data = kwargs
        
        if key not in self._hashes:
            self._hashes[key] = {}
        
        self._hashes[key].update(data)
        return len(data)
    
    def _hset_direct(self, key: str, mapping: dict):
        """Direct hash set for pipeline operations."""
        return self.hset(key, mapping)
    
    def hgetall(self, key: str) -> dict:
        """Get all hash fields."""
        if self._cleanup_expired_key(key):
            return {}
        return self._hashes.get(key, {}).copy()
    
    def expire(self, key: str, ttl: int) -> bool:
        """Set key expiration."""
        if key in self._storage or key in self._hashes:
            self._expiry[key] = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            return True
        return False
    
    def _expire_direct(self, key: str, ttl: int):
        """Direct expire for pipeline operations."""
        return self.expire(key, ttl)
    
    # Legacy methods for backward compatibility
    def set(self, key: str, data: bytes):
        """Store image data."""
        self._storage[key] = data
    
    def setex(self, key: str, ttl: int, data: bytes):
        """Store image data with expiration."""
        self._storage[key] = data
        self.expire(key, ttl)
    
    def get(self, key: str) -> Optional[bytes]:
        """Retrieve image data."""
        if self._cleanup_expired_key(key):
            return None
        return self._storage.get(key)
    
    def exists(self, key: str) -> bool:
        """Check if key exists and is not expired."""
        if self._cleanup_expired_key(key):
            return False
        return key in self._storage or key in self._hashes
    
    def delete(self, key: str) -> int:
        """Delete key."""
        deleted = 0
        if key in self._storage:
            del self._storage[key]
            deleted = 1
        if key in self._hashes:
            del self._hashes[key]
            deleted = 1
        if key in self._expiry:
            del self._expiry[key]
        return deleted
    
    def keys(self, pattern: str) -> list:
        """Get all keys matching pattern (simplified for local testing)."""
        all_keys = set(self._storage.keys()) | set(self._hashes.keys())
        # Clean up expired keys
        expired = [k for k in all_keys if self._cleanup_expired_key(k)]
        all_keys -= set(expired)
        
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return [k for k in all_keys if k.startswith(prefix)]
        return [k for k in all_keys if k == pattern]


class ImageStorageService:
    """Service for storing and retrieving image data via Redis."""
    
    def __init__(self, redis_client=None):
        """Initialize with Redis client or in-memory storage for local testing."""
        # Context-aware logger
        self.logger = get_safe_logger(__name__)
        
        if redis_client:
            # Use provided Redis client
            self.redis = redis_client
            self.using_redis = True
            self.logger.info("✅ ImageStorageService using provided Redis client")
        else:
            # Use centralized Redis configuration
            self.redis, self.using_redis = configure_redis_for_service(
                "ImageStorageService", decode_responses=False  # Binary mode for images
            )
            
            # If Redis not available, use in-memory storage
            if not self.using_redis:
                self.redis = InMemoryImageStorage()
                self.logger.info("🔧 ImageStorageService using in-memory storage")
        
        # Configuration
        self.key_prefix = "image_storage:"
        self.default_ttl = 3600  # 1 hour TTL for temporary images
        self.max_image_size = 10 * 1024 * 1024  # 10MB max
    
    def store_image(self, image_data: bytes, filename: str, ttl: int = None) -> str:
        """
        Store image data in Redis and return a unique key.
        
        Args:
            image_data: Raw image bytes
            filename: Original filename for metadata
            ttl: Time to live in seconds (default: 1 hour)
        
        Returns:
            Unique storage key for retrieving the image
        
        Raises:
            ValueError: If image is too large or invalid
        """
        try:
            # Validate image size
            if len(image_data) > self.max_image_size:
                raise ValueError(f"Image too large: {len(image_data)} bytes (max: {self.max_image_size})")
            
            # Generate unique key
            image_id = str(uuid.uuid4())
            storage_key = f"{self.key_prefix}{image_id}"
            
            # Detect MIME type
            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            
            # Prepare metadata
            metadata = {
                'filename': filename,
                'mime_type': mime_type,
                'size': len(image_data),
                'created_by': 'image_storage_service'
            }
            
            # Encode image data as base64 for Redis storage
            encoded_data = base64.b64encode(image_data).decode('utf-8')
            
            # Create storage payload
            payload = {
                'data': encoded_data,
                'metadata': metadata
            }
            
            # Store in Redis with TTL
            ttl_seconds = ttl or self.default_ttl
            pipeline = self.redis.pipeline()
            pipeline.hset(storage_key, mapping={
                'data': encoded_data,
                'filename': filename,
                'mime_type': mime_type,
                'size': str(len(image_data))
            })
            pipeline.expire(storage_key, ttl_seconds)
            pipeline.execute()
            
            self.logger.info(f"✅ Image stored in Redis: {image_id} ({len(image_data)} bytes, TTL: {ttl_seconds}s)")
            return image_id
            
        except Exception as e:
            self.logger.error(f"❌ Failed to store image in Redis: {e}")
            raise
    
    def retrieve_image(self, image_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve image data from Redis.
        
        Args:
            image_id: Unique image identifier returned by store_image
        
        Returns:
            Dictionary with 'data' (bytes) and 'metadata' (dict), or None if not found
        """
        try:
            storage_key = f"{self.key_prefix}{image_id}"
            
            # Get data from Redis
            image_hash = self.redis.hgetall(storage_key)
            if not image_hash:
                self.logger.warning(f"⚠️ Image not found in Redis: {image_id}")
                return None
            
            # Decode base64 data
            try:
                encoded_data = image_hash.get(b'data') or image_hash.get('data')
                if isinstance(encoded_data, bytes):
                    encoded_data = encoded_data.decode('utf-8')
                
                image_data = base64.b64decode(encoded_data)
            except Exception as decode_error:
                self.logger.error(f"❌ Failed to decode image data for {image_id}: {decode_error}")
                return None
            
            # Extract metadata
            metadata = {
                'filename': (image_hash.get(b'filename') or image_hash.get('filename', b'')).decode('utf-8') if isinstance(image_hash.get(b'filename') or image_hash.get('filename'), bytes) else image_hash.get('filename', ''),
                'mime_type': (image_hash.get(b'mime_type') or image_hash.get('mime_type', b'')).decode('utf-8') if isinstance(image_hash.get(b'mime_type') or image_hash.get('mime_type'), bytes) else image_hash.get('mime_type', ''),
                'size': int((image_hash.get(b'size') or image_hash.get('size', b'0')).decode('utf-8') if isinstance(image_hash.get(b'size') or image_hash.get('size'), bytes) else image_hash.get('size', '0'))
            }
            
            self.logger.info(f"✅ Image retrieved from Redis: {image_id} ({metadata['size']} bytes)")
            
            return {
                'data': image_data,
                'metadata': metadata
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to retrieve image from Redis: {e}")
            return None
    
    def create_temp_file(self, image_id: str) -> Optional[str]:
        """
        Retrieve image from Redis and create a temporary file.
        
        Args:
            image_id: Unique image identifier
        
        Returns:
            Path to temporary file, or None if image not found
        
        Note:
            Caller is responsible for cleaning up the temporary file
        """
        try:
            # Retrieve image data
            image_info = self.retrieve_image(image_id)
            if not image_info:
                return None
            
            # Create temporary file
            filename = image_info['metadata']['filename']
            suffix = os.path.splitext(filename)[1] or '.jpg'
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(image_info['data'])
                temp_path = temp_file.name
            
            self.logger.info(f"✅ Created temp file for {image_id}: {temp_path}")
            return temp_path
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create temp file for {image_id}: {e}")
            return None
    
    def delete_image(self, image_id: str) -> bool:
        """
        Delete image from Redis.
        
        Args:
            image_id: Unique image identifier
        
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            storage_key = f"{self.key_prefix}{image_id}"
            deleted = self.redis.delete(storage_key)
            
            if deleted:
                self.logger.info(f"✅ Image deleted from Redis: {image_id}")
            else:
                self.logger.warning(f"⚠️ Image not found for deletion: {image_id}")
            
            return bool(deleted)
            
        except Exception as e:
            self.logger.error(f"❌ Failed to delete image from Redis: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """
        Clean up expired images (Redis handles this automatically with TTL).
        This method is for manual cleanup if needed.
        
        Returns:
            Number of images cleaned up
        """
        try:
            # Get all image keys
            pattern = f"{self.key_prefix}*"
            keys = self.redis.keys(pattern)
            
            cleaned = 0
            for key in keys:
                # Check if key still exists (Redis TTL might have removed it)
                if not self.redis.exists(key):
                    cleaned += 1
            
            self.logger.info(f"🧹 Redis TTL auto-cleanup: {cleaned} expired images removed")
            return cleaned
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cleanup expired images: {e}")
            return 0


# Global service instance
image_storage_service = None


def get_image_storage_service() -> ImageStorageService:
    """Get the image storage service instance."""
    global image_storage_service
    if image_storage_service is None:
        try:
            # Try to use the same Redis client as the user service for consistency
            from services.user_service import get_user_service
            user_service = get_user_service()
            if hasattr(user_service, 'redis_client') and user_service.using_real_redis:
                # Create new Redis connection for binary operations using centralized config
                from core.redis_utils import get_redis_client
                redis_client, using_redis = get_redis_client(decode_responses=False)
                if using_redis and redis_client:
                    image_storage_service = ImageStorageService(redis_client)
                else:
                    image_storage_service = ImageStorageService()  # Will use in-memory storage
            else:
                image_storage_service = ImageStorageService()  # Will use centralized config
        except Exception as e:
            # Fallback to creating new service (will use centralized config)
            image_storage_service = ImageStorageService()
    
    return image_storage_service