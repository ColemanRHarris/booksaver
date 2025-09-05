"""
File-based image storage service for temporary image storage.
Simplified storage for the streamlined BookSaver application.
"""

import os
import base64
import tempfile
import uuid
import mimetypes
import json
import time
import shutil
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path
from core.logging_utils import get_safe_logger


class ImageStorageService:
    """Service for storing and retrieving image data via file system."""
    
    def __init__(self, storage_dir=None):
        """Initialize with storage directory."""
        # Use system temp directory or provided directory
        if storage_dir:
            self.storage_dir = Path(storage_dir)
        else:
            self.storage_dir = Path(tempfile.gettempdir()) / "booksaver_images"
        
        # Create storage directory if it doesn't exist
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuration
        self.default_ttl = 3600  # 1 hour TTL for temporary images
        self.max_image_size = 10 * 1024 * 1024  # 10MB max
        
        # Context-aware logger
        self.logger = get_safe_logger(__name__)
        
        self.logger.info(f"📁 Image storage initialized at: {self.storage_dir}")
    
    def store_image(self, image_data: bytes, filename: str, ttl: int = None) -> str:
        """
        Store image data in file system and return a unique key.
        
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
            
            # Detect MIME type and file extension
            mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            
            # Determine file extension
            if filename and '.' in filename:
                ext = '.' + filename.split('.')[-1].lower()
            else:
                # Default extension based on MIME type
                ext = '.jpg' if 'image' in mime_type else '.bin'
            
            # Create file paths
            image_file = self.storage_dir / f"{image_id}{ext}"
            metadata_file = self.storage_dir / f"{image_id}.json"
            
            # Prepare metadata
            metadata = {
                'filename': filename,
                'mime_type': mime_type,
                'size': len(image_data),
                'created_by': 'image_storage_service',
                'created_at': datetime.now().isoformat(),
                'expires_at': (datetime.now() + timedelta(seconds=ttl or self.default_ttl)).isoformat(),
                'image_id': image_id
            }
            
            # Write image data to file
            with open(image_file, 'wb') as f:
                f.write(image_data)
            
            # Write metadata to JSON file
            with open(metadata_file, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            ttl_seconds = ttl or self.default_ttl
            self.logger.info(f"✅ Image stored in filesystem: {image_id} ({len(image_data)} bytes, TTL: {ttl_seconds}s)")
            return image_id
            
        except Exception as e:
            self.logger.error(f"❌ Failed to store image in filesystem: {e}")
            raise
    
    def retrieve_image(self, image_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve image data from filesystem.
        
        Args:
            image_id: Unique image identifier returned by store_image
        
        Returns:
            Dictionary with 'data' (bytes) and 'metadata' (dict), or None if not found
        """
        try:
            # Find the image file (try common extensions)
            image_file = None
            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.bin']:
                candidate = self.storage_dir / f"{image_id}{ext}"
                if candidate.exists():
                    image_file = candidate
                    break
            
            if not image_file:
                self.logger.warning(f"⚠️ Image file not found: {image_id}")
                return None
            
            # Load metadata
            metadata_file = self.storage_dir / f"{image_id}.json"
            if not metadata_file.exists():
                self.logger.warning(f"⚠️ Metadata file not found: {image_id}")
                return None
            
            # Check if expired
            with open(metadata_file, 'r') as f:
                metadata = json.load(f)
            
            expires_at = datetime.fromisoformat(metadata.get('expires_at', ''))
            if datetime.now() > expires_at:
                self.logger.info(f"🗑️ Image expired, cleaning up: {image_id}")
                self._cleanup_expired_image(image_id, image_file, metadata_file)
                return None
            
            # Read image data
            with open(image_file, 'rb') as f:
                image_data = f.read()
            
            self.logger.info(f"✅ Image retrieved from filesystem: {image_id} ({len(image_data)} bytes)")
            
            return {
                'data': image_data,
                'metadata': metadata
            }
            
        except Exception as e:
            self.logger.error(f"❌ Failed to retrieve image from filesystem: {e}")
            return None
    
    def create_temp_file(self, image_id: str) -> Optional[str]:
        """
        Find existing image file or create a copy in system temp directory.
        
        Args:
            image_id: Unique image identifier
        
        Returns:
            Path to temporary file, or None if image not found
        
        Note:
            Caller is responsible for cleaning up the temporary file
        """
        try:
            # Find the image file
            image_file = None
            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.bin']:
                candidate = self.storage_dir / f"{image_id}{ext}"
                if candidate.exists():
                    image_file = candidate
                    break
            
            if not image_file:
                self.logger.warning(f"⚠️ Image file not found for temp creation: {image_id}")
                return None
            
            # Check if expired
            metadata_file = self.storage_dir / f"{image_id}.json"
            if metadata_file.exists():
                with open(metadata_file, 'r') as f:
                    metadata = json.load(f)
                
                expires_at = datetime.fromisoformat(metadata.get('expires_at', ''))
                if datetime.now() > expires_at:
                    self.logger.info(f"🗑️ Image expired, cannot create temp file: {image_id}")
                    self._cleanup_expired_image(image_id, image_file, metadata_file)
                    return None
            
            # For our simplified use case, just return the path to the stored file
            # This avoids unnecessary copying since we're in local development
            temp_path = str(image_file)
            
            self.logger.info(f"✅ Temp file path for {image_id}: {temp_path}")
            return temp_path
            
        except Exception as e:
            self.logger.error(f"❌ Failed to create temp file for {image_id}: {e}")
            return None
    
    def delete_image(self, image_id: str) -> bool:
        """
        Delete image from filesystem.
        
        Args:
            image_id: Unique image identifier
        
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            deleted = False
            
            # Find and delete image file
            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.bin']:
                image_file = self.storage_dir / f"{image_id}{ext}"
                if image_file.exists():
                    image_file.unlink()
                    deleted = True
                    break
            
            # Delete metadata file
            metadata_file = self.storage_dir / f"{image_id}.json"
            if metadata_file.exists():
                metadata_file.unlink()
                deleted = True
            
            if deleted:
                self.logger.info(f"✅ Image deleted from filesystem: {image_id}")
            else:
                self.logger.warning(f"⚠️ Image not found for deletion: {image_id}")
            
            return deleted
            
        except Exception as e:
            self.logger.error(f"❌ Failed to delete image from filesystem: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """
        Clean up expired images from filesystem.
        
        Returns:
            Number of images cleaned up
        """
        try:
            cleaned = 0
            current_time = datetime.now()
            
            # Find all metadata files
            for metadata_file in self.storage_dir.glob("*.json"):
                try:
                    with open(metadata_file, 'r') as f:
                        metadata = json.load(f)
                    
                    expires_at = datetime.fromisoformat(metadata.get('expires_at', ''))
                    if current_time > expires_at:
                        image_id = metadata.get('image_id')
                        if image_id:
                            # Find and delete the corresponding image file
                            for ext in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.bin']:
                                image_file = self.storage_dir / f"{image_id}{ext}"
                                if image_file.exists():
                                    image_file.unlink()
                                    break
                            
                            # Delete metadata file
                            metadata_file.unlink()
                            cleaned += 1
                            
                except Exception as e:
                    self.logger.warning(f"⚠️ Error cleaning up {metadata_file}: {e}")
            
            if cleaned > 0:
                self.logger.info(f"🧹 Filesystem cleanup: {cleaned} expired images removed")
            
            return cleaned
            
        except Exception as e:
            self.logger.error(f"❌ Failed to cleanup expired images: {e}")
            return 0
    
    def _cleanup_expired_image(self, image_id: str, image_file: Path, metadata_file: Path):
        """Helper method to clean up a specific expired image."""
        try:
            image_file.unlink()
            metadata_file.unlink()
            self.logger.info(f"🗑️ Cleaned up expired image: {image_id}")
        except Exception as e:
            self.logger.error(f"❌ Failed to cleanup expired image {image_id}: {e}")


# Global service instance
image_storage_service = None


def get_image_storage_service() -> ImageStorageService:
    """Get the image storage service instance."""
    global image_storage_service
    if image_storage_service is None:
        # Create file-based storage service
        image_storage_service = ImageStorageService()
    
    return image_storage_service