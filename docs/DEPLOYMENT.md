# Deployment Guide - BookSaver to Render

This guide covers deploying the BookSaver application to Render with Celery background tasks.

## 🏗️ Architecture Overview

The app consists of 3 services on Render:
1. **Redis** - Message broker for Celery tasks
2. **Web App** - Flask application serving the website
3. **Worker** - Celery worker processing TikTok videos

## 📋 Prerequisites

1. GitHub repository with your code
2. Render account (free tier works)
3. Optional: Google Books API key for better search results

## 🚀 Deployment Steps

### Option A: Using render.yaml (Recommended)

1. **Push to GitHub**
   ```bash
   git add .
   git commit -m "Deploy: Add Render configuration"
   git push origin main
   ```

2. **Deploy to Render**
   - Go to [Render Dashboard](https://dashboard.render.com)
   - Click "New" → "Blueprint"
   - Connect your GitHub repository
   - Render will automatically detect `render.yaml` and create all services

3. **Set Environment Variables**
   After deployment, go to each service and set:
   - `GOOGLE_BOOKS_KEY` (optional) - Your Google Books API key
   - `SECRET_KEY` is auto-generated

### Option B: Manual Service Creation

#### 1. Create Redis Service
- Service Type: **Redis**
- Name: `booksaver-redis`
- Plan: **Free**

#### 2. Create Web Service
- Service Type: **Web Service**
- Runtime: **Python 3**
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn -w 2 -b 0.0.0.0:$PORT app:app`
- Environment Variables:
  - `REDIS_URL`: Connection string from Redis service
  - `SECRET_KEY`: Generate a random string
  - `GOOGLE_BOOKS_KEY`: (optional) Your API key

#### 3. Create Worker Service
- Service Type: **Background Worker**
- Runtime: **Python 3**
- Build Command: `pip install -r requirements.txt`
- Start Command: `celery -A celery_app worker --loglevel=info --concurrency=1`
- Environment Variables: Same as Web Service

## 🔧 Configuration Details

### Redis Configuration
- **Plan**: Free (25MB, 30 connections)
- **Persistence**: 4 hours (sufficient for task queues)
- **Access**: Internal only (secure)

### Web Service Configuration
- **Plan**: Free (512MB RAM, sleeps after 15min inactivity)
- **Workers**: 2 Gunicorn workers
- **Health Check**: `/` endpoint
- **Auto-deploy**: Enabled on git push

### Worker Service Configuration
- **Plan**: Free (512MB RAM)
- **Concurrency**: 1 worker process
- **Tasks**: TikTok video processing
- **Timeout**: 5 minutes per task

## 🔍 Monitoring & Debugging

### Logs
- **Web logs**: View requests, errors, task submissions
- **Worker logs**: Monitor task processing, video downloads
- **Redis logs**: Connection status, memory usage

### Health Checks
- Web service: Automatic health checks on `/`
- Worker service: Process-based monitoring
- Redis: Connection monitoring

### Common Issues

1. **Worker not processing tasks**
   - Check Redis connection in worker logs
   - Verify REDIS_URL environment variable
   - Restart worker service

2. **Memory issues**
   - Video processing is memory-intensive
   - Consider upgrading to paid plan for larger videos
   - Monitor memory usage in service metrics

3. **Task timeouts**
   - Default 5-minute limit per task
   - Large videos may need longer processing
   - Implement task chunking for very large files

## 📊 Performance Considerations

### Free Tier Limitations
- **Web**: Sleeps after 15 minutes of inactivity
- **Worker**: Always running (doesn't sleep)
- **Redis**: 25MB storage limit
- **Bandwidth**: 100GB/month across all services

### Optimization Tips
1. **Video Processing**: Limit frame extraction for faster processing
2. **Caching**: Consider implementing result caching
3. **Error Handling**: Graceful degradation for failed downloads
4. **Resource Monitoring**: Watch memory and CPU usage

## 🔐 Security

### Environment Variables
- `SECRET_KEY`: Auto-generated, keep secure
- `REDIS_URL`: Internal connection, no external access
- `GOOGLE_BOOKS_KEY`: Optional, rate-limited by Google

### Network Security
- Redis: Internal network only
- Web: HTTPS enforced by Render
- Worker: No external network access needed

## 💰 Cost Estimation

### Free Tier (Suitable for MVP)
- **Redis**: Free (25MB)
- **Web**: Free (512MB, sleeps)
- **Worker**: Free (512MB)
- **Total**: $0/month

### Paid Tier (Production Ready)
- **Redis**: $7/month (Starter)
- **Web**: $7/month (Starter)
- **Worker**: $7/month (Starter)
- **Total**: ~$21/month

## 🚦 Going Live

### Domain Setup
1. Use provided Render URL: `https://your-app.onrender.com`
2. Or connect custom domain in service settings

### Environment Variables to Set
```bash
# Required
REDIS_URL=redis://...  # Auto-set by Render
SECRET_KEY=your-secret-key  # Auto-generated

# Optional
GOOGLE_BOOKS_KEY=your-api-key  # For better search results
```

### Final Checklist
- [ ] All services deployed and running
- [ ] Redis connected to both web and worker
- [ ] Environment variables configured
- [ ] Test TikTok processing end-to-end
- [ ] Monitor logs for errors
- [ ] Set up custom domain (optional)

## 🔄 Updates & Maintenance

### Deployment Updates
- Push to GitHub → Automatic redeploy
- Zero-downtime deployments
- Rollback available in Render dashboard

### Monitoring
- Service health in Render dashboard
- Application logs for debugging
- Performance metrics and alerts

---

**Need Help?** Check Render's documentation or create an issue in the GitHub repository.