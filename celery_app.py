from celery import Celery
import os

# Determine broker URL based on environment
redis_url = os.getenv('REDIS_URL')
if redis_url:
    # Production: Use Redis
    broker_url = redis_url
    backend_url = redis_url
    broker_transport_options = {}
    print(f"🔗 Using Redis broker: {redis_url[:50]}...")
else:
    # Local development: Use filesystem broker
    import tempfile
    broker_url = 'filesystem://'
    backend_url = 'cache+memory://'
    broker_transport_options = {
        'data_folder_in': os.path.join(tempfile.gettempdir(), 'celery_in'),
        'data_folder_out': os.path.join(tempfile.gettempdir(), 'celery_out'),
        'data_folder_processed': os.path.join(tempfile.gettempdir(), 'celery_processed'),
    }
    # Create directories if they don't exist
    for folder in broker_transport_options.values():
        os.makedirs(folder, exist_ok=True)
    print("📁 Using filesystem broker for local development")

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
    task_always_eager=not bool(redis_url),  # False in production (Redis), True locally
    broker_transport_options=broker_transport_options,
)

if __name__ == '__main__':
    celery_app.start()