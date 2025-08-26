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
from datetime import timedelta
import redis
from core.logging_utils import get_safe_logger


class ImageStorageService:
    """Service for storing and retrieving image data via Redis."""
    
    def __init__(self, redis_client=None):
        """Initialize with Redis client."""
        if redis_client:
            self.redis = redis_client
        else:
            # Create Redis connection
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
            self.redis = redis.from_url(redis_url, decode_responses=False)  # Binary mode for images
        
        # Configuration
        self.key_prefix = "image_storage:"
        self.default_ttl = 3600  # 1 hour TTL for temporary images
        self.max_image_size = 10 * 1024 * 1024  # 10MB max
        
        # Context-aware logger
        self.logger = get_safe_logger(__name__)
    
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
            # Try to use the same Redis client as the user service
            from services.user_service import get_user_service
            user_service = get_user_service()
            if hasattr(user_service, 'redis_client') and user_service.using_real_redis:
                # Create new Redis connection for binary operations
                redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
                redis_client = redis.from_url(redis_url, decode_responses=False)
                image_storage_service = ImageStorageService(redis_client)
            else:
                image_storage_service = ImageStorageService()
        except Exception:
            # Fallback to creating new service
            image_storage_service = ImageStorageService()
    
    return image_storage_service