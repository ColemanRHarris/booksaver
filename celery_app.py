from celery import Celery
import os

# Determine broker URL based on environment
redis_url = os.getenv('REDIS_URL')
if redis_url and not redis_url.startswith('memory://'):
    # Production: Use Redis
    broker_url = redis_url
    backend_url = redis_url
    broker_transport_options = {}
    print(f"🔗 Using Redis broker: {redis_url[:50]}...")
else:
    # Local development: Use simple RPC backend (always available)
    broker_url = 'memory://'
    backend_url = 'rpc://'  # RPC backend is always available and works well for local dev
    broker_transport_options = {}
    print("🔧 Using in-memory broker with RPC backend for local development")

# Create Celery app
celery_app = Celery(
    'booksaver',
    broker=broker_url,
    backend=backend_url,
    include=['tasks']
)

# Configure Celery settings
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minute timeout
    task_soft_time_limit=240,  # 4 minute soft timeout
    worker_prefetch_multiplier=1,
    task_always_eager=not bool(redis_url and not redis_url.startswith('memory://')),  # True for local development
    broker_transport_options=broker_transport_options,
)

# Additional configuration for local development
if not redis_url or redis_url.startswith('memory://'):
    # No additional configuration needed for RPC backend
    pass

if __name__ == '__main__':
    celery_app.start()