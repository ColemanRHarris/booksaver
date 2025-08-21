import redis
import json
import hashlib
from datetime import datetime, timedelta
import os
from typing import Dict, List, Optional, Any

class SimpleDictCache:
    """Simple in-memory fallback for Redis when not available"""
    def __init__(self):
        self._data = {}
        
    def hgetall(self, key):
        return self._data.get(key, {})
    
    def hset(self, key, mapping):
        if key not in self._data:
            self._data[key] = {}
        self._data[key].update(mapping)
    
    def expire(self, key, seconds):
        # Simple implementation - just store expiry time
        pass  # For development, we'll skip expiration
    
    def delete(self, key):
        self._data.pop(key, None)
    
    def sadd(self, key, *values):
        if key not in self._data:
            self._data[key] = set()
        for value in values:
            self._data[key].add(value)
    
    def zcard(self, key):
        return len(self._data.get(key, {}))
    
    def zadd(self, key, mapping):
        if key not in self._data:
            self._data[key] = {}
        self._data[key].update(mapping)
    
    def zrem(self, key, *values):
        if key in self._data:
            for value in values:
                self._data[key].pop(value, None)
    
    def hget(self, key, field):
        data = self._data.get(key, {})
        value = data.get(field)
        return value.encode() if value else None
    
    def setex(self, key, seconds, value):
        self._data[key] = value
    
    def keys(self, pattern):
        # Simple pattern matching for "*" patterns
        if pattern.endswith('*'):
            prefix = pattern[:-1]
            return [key for key in self._data.keys() if key.startswith(prefix)]
        return [key for key in self._data.keys() if key == pattern]

class RecommendationEngine:
    def __init__(self, redis_client=None):
        print("🚀 Initializing Recommendation Engine...")
        
        if redis_client:
            print("✅ Using provided Redis client")
            self.redis = redis_client
        else:
            # Auto-detect local development environment
            redis_url = os.getenv('REDIS_URL')
            print(f"🔍 Environment check - REDIS_URL: {'SET' if redis_url else 'NOT SET'}")
            
            # Environment detection
            is_local = self._is_local_development()
            print(f"🏠 Environment detected: {'LOCAL DEVELOPMENT' if is_local else 'PRODUCTION/DEPLOYMENT'}")
            
            if not redis_url:
                # Check if we're in local development
                if is_local:
                    redis_url = 'memory://'  # Use in-memory cache locally
                    print("🔧 No REDIS_URL set, using in-memory cache for local development")
                else:
                    redis_url = 'redis://localhost:6379'  # Default fallback
                    print("⚠️ No REDIS_URL set in production, using localhost fallback")
            else:
                print(f"📡 Using REDIS_URL from environment: {redis_url}")
            
            # Initialize Redis connection based on URL
            if redis_url == 'memory://':
                print("🔧 Recommendation Engine: Setting up in-memory cache (local development)")
                try:
                    from fakeredis import FakeRedis
                    self.redis = FakeRedis()
                    print("✅ Using FakeRedis for in-memory caching")
                except ImportError:
                    # If fakeredis not available, use a simple dict-based fallback
                    self.redis = SimpleDictCache()
                    print("⚠️ FakeRedis not available, using SimpleDictCache fallback")
            else:
                print(f"📡 Recommendation Engine: Connecting to Redis at {redis_url}")
                try:
                    import redis as redis_lib
                    self.redis = redis_lib.from_url(redis_url)
                    # Test connection
                    self.redis.ping()
                    print("✅ Successfully connected to Redis")
                except Exception as e:
                    print(f"❌ Failed to connect to Redis: {e}")
                    print("🔧 Falling back to in-memory cache")
                    self.redis = SimpleDictCache()
        
        self.cache_ttl = 7 * 24 * 3600  # 7 days cache
        self.session_ttl = 30 * 24 * 3600  # 30 days for sessions
        
        print(f"⏰ Cache configuration:")
        print(f"   📦 Cache TTL: {self.cache_ttl}s ({self.cache_ttl/3600:.1f} hours)")
        print(f"   🗂️ Session TTL: {self.session_ttl}s ({self.session_ttl/86400:.1f} days)")
        print(f"   🔗 Cache backend: {type(self.redis).__name__}")
        print("🎉 Recommendation Engine initialized successfully!")
    
    def _is_local_development(self) -> bool:
        """Detect if running in local development environment"""
        # Check for common cloud platform environment variables
        if os.getenv('RENDER'):  # Render sets this env var
            return False
        if os.getenv('HEROKU'):  # Heroku sets this
            return False
        if os.getenv('RAILWAY_ENVIRONMENT'):  # Railway sets this
            return False
        if os.getenv('VERCEL'):  # Vercel sets this
            return False
        if os.getenv('AWS_EXECUTION_ENV'):  # AWS Lambda/ECS
            return False
        if os.getenv('GOOGLE_CLOUD_PROJECT'):  # Google Cloud
            return False
        if os.getenv('AZURE_FUNCTIONS_ENVIRONMENT'):  # Azure
            return False
        
        # Check for localhost/development indicators
        if os.getenv('FLASK_ENV') == 'development':
            return True
        if os.getenv('FLASK_DEBUG') == '1':
            return True
        if '127.0.0.1' in os.getenv('HOST', ''):
            return True
        if 'localhost' in os.getenv('HOST', ''):
            return True
        
        # Check if running on default Flask development port
        port = os.getenv('PORT', '')
        if port in ['5000', '10001']:  # Common Flask dev ports
            return True
        
        # Default to local if no cloud platform detected
        return True
    
    def _hash_url(self, url: str) -> str:
        """Create consistent hash for video URL with normalization"""
        original_url = url
        
        # Normalize URL for consistent caching
        normalized_url = self._normalize_url(url)
        
        if normalized_url != original_url:
            print(f"🔧 URL normalized: {original_url} → {normalized_url}")
        
        url_hash = hashlib.md5(normalized_url.encode('utf-8')).hexdigest()[:12]
        print(f"🔑 URL hash generated: {url_hash} for normalized URL: {normalized_url}")
        
        return url_hash
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL to ensure consistent caching across URL variations"""
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        
        try:
            # Parse the URL
            parsed = urlparse(url.strip())
            
            # Normalize scheme to https
            scheme = 'https'
            
            # Normalize domain - remove www prefix for consistency
            netloc = parsed.netloc.lower()
            if netloc.startswith('www.'):
                netloc = netloc[4:]
            
            # Handle TikTok URL variations
            if 'tiktok.com' in netloc:
                # Standardize TikTok domains
                if netloc in ['vm.tiktok.com', 'vt.tiktok.com', 'm.tiktok.com']:
                    # Keep these as-is since they're different services
                    pass
                else:
                    # Standardize to tiktok.com (without www)
                    netloc = 'tiktok.com'
            
            # Remove trailing slash from path
            path = parsed.path.rstrip('/')
            
            # Remove common tracking parameters
            if parsed.query:
                query_params = parse_qs(parsed.query)
                # Remove common tracking parameters
                tracking_params = ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 
                                 'fbclid', 'gclid', '_gl', 'ref', 'source']
                for param in tracking_params:
                    query_params.pop(param, None)
                
                # Rebuild query string
                if query_params:
                    query = urlencode(sorted(query_params.items()), doseq=True)
                else:
                    query = ''
            else:
                query = ''
            
            # Rebuild URL
            normalized = urlunparse((scheme, netloc, path, parsed.params, query, ''))
            
            return normalized
            
        except Exception as e:
            print(f"⚠️ URL normalization error for {url}: {e}")
            # Return original URL if normalization fails
            return url.strip()
    
    def get_cached_results(self, video_url: str) -> Optional[Dict[str, Any]]:
        """Check if we have cached results for this video URL"""
        try:
            url_hash = self._hash_url(video_url)
            cache_key = f"video_cache:{url_hash}"
            
            print(f"🔍 Cache lookup for URL: {video_url}")
            print(f"🔑 Generated cache key: {cache_key} (hash: {url_hash})")
            
            cached_data = self.redis.hgetall(cache_key)
            if not cached_data:
                print(f"❌ Cache MISS: No cached results found for {video_url[:50]}...")
                return None
            
            print(f"📦 Found cached data with keys: {list(cached_data.keys())}")
            
            # Check if cache is still valid (not expired)
            created_at_str = cached_data.get(b'created_at', cached_data.get('created_at', ''))
            if isinstance(created_at_str, bytes):
                created_at_str = created_at_str.decode()
            
            if not created_at_str:
                print(f"⚠️ Cache entry missing timestamp, treating as expired")
                self.redis.delete(cache_key)
                return None
                
            created_at = datetime.fromisoformat(created_at_str)
            cache_age = datetime.utcnow() - created_at
            
            print(f"⏰ Cache age: {cache_age.total_seconds():.1f}s (TTL: {self.cache_ttl}s)")
            
            if cache_age > timedelta(seconds=self.cache_ttl):
                print(f"🗑️ Cache EXPIRED: Deleting expired entry for {video_url[:50]}...")
                # Cache expired, delete it
                self.redis.delete(cache_key)
                self.redis.delete(f"url_mapping:{url_hash}")
                return None
            
            print(f"💾 Cache HIT: Returning cached results for {video_url[:50]}...")
            books_data = cached_data.get(b'books', cached_data.get('books', ''))
            if isinstance(books_data, bytes):
                books_data = books_data.decode()
            
            return json.loads(books_data)
            
        except Exception as e:
            print(f"⚠️ Cache lookup error for {video_url[:50]}...: {e}")
            import traceback
            print(f"🔍 Cache error traceback: {traceback.format_exc()}")
            return None
    
    def cache_results(self, video_url: str, video_type: str, results: Dict[str, Any]):
        """Cache book detection results for a video URL"""
        try:
            url_hash = self._hash_url(video_url)
            cache_key = f"video_cache:{url_hash}"
            
            print(f"💾 Caching results for URL: {video_url}")
            print(f"🔑 Cache key: {cache_key} (hash: {url_hash})")
            
            # Calculate data size for debugging
            books_json = json.dumps(results)
            data_size = len(books_json.encode('utf-8'))
            num_books = len(results.get('books', []))
            
            print(f"📊 Caching {num_books} books, data size: {data_size} bytes")
            
            cache_data = {
                "books": books_json,
                "created_at": datetime.utcnow().isoformat(),
                "video_type": video_type
            }
            
            # Store cache with TTL
            self.redis.hset(cache_key, mapping=cache_data)
            self.redis.expire(cache_key, self.cache_ttl)
            
            print(f"⏰ Set cache TTL to {self.cache_ttl} seconds ({self.cache_ttl/3600:.1f} hours)")
            
            # Store URL mapping for debugging
            self.redis.setex(f"url_mapping:{url_hash}", self.cache_ttl, video_url)
            
            print(f"✅ Successfully cached results for: {video_url[:50]}...")
            
        except Exception as e:
            print(f"⚠️ Cache store error for {video_url[:50]}...: {e}")
            import traceback
            print(f"🔍 Cache store error traceback: {traceback.format_exc()}")
    
    def store_video_session(self, session_id: str, video_url: str, video_type: str):
        """Store video processing session"""
        try:
            session_data = {
                "video_url": video_url,
                "video_type": video_type,
                "created_at": datetime.utcnow().isoformat(),
                "url_hash": self._hash_url(video_url)  # Link to cache
            }
            self.redis.hset(f"video_session:{session_id}", mapping=session_data)
            self.redis.expire(f"video_session:{session_id}", self.session_ttl)
        except Exception as e:
            print(f"⚠️ Session store error: {e}")
    
    def submit_feedback(self, session_id: str, book_isbn: str, book_title: str, book_authors: List[str], feedback: int):
        """Submit thumbs up/down feedback"""
        try:
            feedback_key = f"book_feedback:{session_id}:{book_isbn}"
            feedback_data = {
                "title": book_title,
                "authors": json.dumps(book_authors),
                "feedback": str(feedback),
                "created_at": datetime.utcnow().isoformat()
            }
            self.redis.hset(feedback_key, mapping=feedback_data)
            self.redis.expire(feedback_key, self.session_ttl)
            
            # Add to session books
            self.redis.sadd(f"session_books:{session_id}", book_isbn)
            self.redis.expire(f"session_books:{session_id}", self.session_ttl)
            
            # Update aggregated counts
            timestamp = datetime.utcnow().timestamp()
            if feedback == 1:
                self.redis.zadd(f"book_thumbs_up:{book_isbn}", {session_id: timestamp})
                # Remove from thumbs down if it was there
                self.redis.zrem(f"book_thumbs_down:{book_isbn}", session_id)
            elif feedback == -1:
                self.redis.zadd(f"book_thumbs_down:{book_isbn}", {session_id: timestamp})
                # Remove from thumbs up if it was there
                self.redis.zrem(f"book_thumbs_up:{book_isbn}", session_id)
        except Exception as e:
            print(f"⚠️ Feedback submit error: {e}")
    
    def get_book_feedback_counts(self, book_isbn: str) -> Dict[str, int]:
        """Get aggregated feedback counts for a book"""
        try:
            up_count = self.redis.zcard(f"book_thumbs_up:{book_isbn}")
            down_count = self.redis.zcard(f"book_thumbs_down:{book_isbn}")
            return {"up": up_count, "down": down_count}
        except Exception as e:
            print(f"⚠️ Feedback count error: {e}")
            return {"up": 0, "down": 0}
    
    def get_session_feedback(self, session_id: str, book_isbn: str) -> Optional[int]:
        """Get existing feedback for a book in this session"""
        try:
            feedback_key = f"book_feedback:{session_id}:{book_isbn}"
            feedback_data = self.redis.hget(feedback_key, "feedback")
            if feedback_data:
                return int(feedback_data.decode())
            return None
        except Exception as e:
            print(f"⚠️ Session feedback error: {e}")
            return None
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        try:
            cache_keys = self.redis.keys("video_cache:*")
            session_keys = self.redis.keys("video_session:*")
            feedback_keys = self.redis.keys("book_feedback:*")
            
            return {
                "cached_videos": len(cache_keys),
                "active_sessions": len(session_keys),
                "total_feedback": len(feedback_keys)
            }
        except Exception as e:
            print(f"⚠️ Cache stats error: {e}")
            return {"cached_videos": 0, "active_sessions": 0, "total_feedback": 0}

# Global instance
_recommendation_engine = None

def get_recommendation_engine() -> RecommendationEngine:
    """Get or create recommendation engine instance"""
    global _recommendation_engine
    if _recommendation_engine is None:
        _recommendation_engine = RecommendationEngine()
    return _recommendation_engine