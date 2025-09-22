# LinkedIn Job Scraper

A high-performance, production-ready web scraper for LinkedIn jobs built with Python. Designed to run on Railway with cron scheduling, featuring multithreaded processing, comprehensive monitoring with Grafana Loki, and PostgreSQL storage.

## 🚀 Features

- **Job Discovery**: Paginates LinkedIn job search results to collect job IDs with rate limiting
- **Multithreaded Extraction**: Concurrent processing of job details with configurable thread pools
- **PostgreSQL Storage**: Normalized database schema with job discovery and detail tables
- **Grafana Loki Monitoring**: Structured JSON logging with real-time metrics and dashboards
- **Docker Containerization**: Optimized for Railway deployment with cron scheduling
- **Error Handling**: Comprehensive retry logic, rate limiting detection, and graceful failure handling
- **Production Ready**: Health checks, logging, and monitoring for 24/7 operation

## 🏗️ Architecture

### Database Schema

#### `scraper_linkedin_jobs` (Discovery Table)
```sql
- id (PK): Job ID from LinkedIn
- country: Search country
- status: pending/completed/failed
- created_at, updated_at: Timestamps
```

#### `scraper_linkedin_job_details` (Extraction Table)
```sql
- id (FK): Links to jobs table
- job_title, company_name, location, country
- posted_time, published_date, applicant_count
- job_description, seniority_level, employment_type
- job_function, industries, url
- extract_date, status
```

### Processing Flow

1. **Discovery** (`main.py`): Sequential pagination of LinkedIn search results
2. **Extraction** (`job_extractor.py`): Multithreaded processing of individual job pages
3. **Monitoring**: Structured logs sent to Grafana Loki for real-time visibility

## 📋 Prerequisites

- **Python 3.13+**
- **PostgreSQL** database
- **Grafana Cloud** account (for monitoring)
- **Railway** account (for deployment)

## 🔧 Local Development

### Setup

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd scraper-linkedin
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment** (create `.env` file):
   ```bash
   # Database
   DATABASE_URL="postgresql://user:password@localhost:5432/dbname"

   # LinkedIn Search Configuration
   LINKEDIN_LOCATION="Chile"
   LINKEDIN_COUNTRY="Chile"
   LINKEDIN_F_TPR_VALUE="r86400"  # Last 24 hours

   # Processing Configuration
   LINKEDIN_MAX_WORKERS=4
   LINKEDIN_MAX_THREADS=2
   LINKEDIN_MAX_CONSECUTIVE_404=20
   LINKEDIN_MAX_RETRIES=5
   LINKEDIN_RETRY_DELAY=6
   LINKEDIN_DB_BATCH_SIZE=100

   # Monitoring (Grafana Loki)
   GRAFANA_LOKI_URL="https://logs-prod-us-central1.grafana.net"
   GRAFANA_USER_ID="your_user_id"  # Optional
   GRAFANA_API_KEY="your_api_key"

   # Logging Configuration
   LOG_EVENTS_ENABLED="true"  # Enable/disable database event logging
   LOKI_ENABLED="true"        # Enable/disable Loki logging
   LOG_DISCOVERY_DETAILS="false"  # Enable/disable detailed discovery iteration logs
   ```

### Running Locally

#### Full Pipeline (Recommended)
```bash
./run_scraper.sh
# Or manually:
# python main.py && python job_extractor.py
```

#### Individual Components
```bash
# Discovery only
python main.py

# Extraction only
python job_extractor.py
```

## 🐳 Docker Deployment

### Build and Run Locally
```bash
# Build image
docker build -t linkedin-scraper .

# Run container
docker run --env-file .env linkedin-scraper
```

### Railway Deployment

1. **Push to Git repository**:
   ```bash
   git add .
   git commit -m "Update LinkedIn scraper"
   git push origin main
   ```

2. **Connect to Railway**:
   - Go to Railway dashboard
   - Create new project from GitHub/GitLab
   - Connect your repository

3. **Configure Environment Variables**:
   - Add all variables from `.env` in Railway dashboard
   - Set `LINKEDIN_MAX_THREADS=2` for Railway (conservative)

4. **Setup Cron Scheduling**:
   - In Railway dashboard: Settings → Cron Schedules
   - Add schedule: `0 */4 * * *` (every 4 hours)
   - Command: `./run_scraper.sh`

## 📊 Monitoring & Observability

### Grafana Loki Setup

1. **Get Loki credentials** from Grafana Cloud:
   - Go to Grafana Cloud → Loki → Details
   - Copy URL and create API key

2. **Configure environment variables**:
   ```bash
   GRAFANA_LOKI_URL="https://logs-prod-us-central1.grafana.net"
   GRAFANA_API_KEY="your_api_key"
   ```

### Log Structure

All logs are sent as structured JSON:
```json
{
  "timestamp": "2025-09-21T01:18:28Z",
  "level": "INFO",
  "service": "linkedin-scraper",
  "event_type": "extraction_completed",
  "total_jobs": 254,
  "successful_jobs": 240,
  "failed_jobs": 14,
  "processing_time_seconds": 45.67,
  "jobs_per_second": 5.56
}
```

### Key Metrics to Monitor

#### Grafana Queries (LogQL)
```logql
# Jobs processed per hour
sum(rate({service="linkedin-scraper", event_type="extraction_completed"}[1h])) by (total_jobs)

# Success rate
rate({service="linkedin-scraper", event_type="extraction_completed"}[5m]) / rate({service="linkedin-scraper", event_type="extraction_started"}[5m]) * 100

# Error rate
sum(rate({service="linkedin-scraper", event_type="extraction_completed"}[5m])) by (failed_jobs)
```

#### Recommended Dashboard Panels
- **Jobs Processed**: Time series chart
- **Success Rate**: Gauge (target: >90%)
- **Processing Speed**: Jobs per second
- **Error Breakdown**: Pie chart by error type
- **Active Threads**: Current thread utilization

### Alerts
- **High failure rate**: `failed_jobs > 50` in last hour
- **No processing**: No logs for >2 hours
- **Slow processing**: `jobs_per_second < 2` for >30 minutes

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `DATABASE_URL` | PostgreSQL connection string | - | ✅ |
| `LINKEDIN_LOCATION` | Search location | Chile | ❌ |
| `LINKEDIN_COUNTRY` | Country for storage | Chile | ❌ |
| `LINKEDIN_MAX_THREADS` | Concurrent extraction threads | 2 | ❌ |
| `LINKEDIN_MAX_RETRIES` | HTTP request retries | 5 | ❌ |
| `LINKEDIN_RETRY_DELAY` | Delay between retries (sec) | 6 | ❌ |
| `GRAFANA_LOKI_URL` | Loki endpoint URL | - | ✅ |
| `GRAFANA_API_KEY` | Loki API key | - | ✅ |
| `LOG_EVENTS_ENABLED` | Enable/disable database event logging | true | ❌ |
| `LOKI_ENABLED` | Enable/disable Loki logging | true | ❌ |
| `LOG_DISCOVERY_DETAILS` | Enable/disable detailed discovery iteration logs | false | ❌ |

### Performance Tuning

#### For High Volume
```bash
LINKEDIN_MAX_THREADS=3
LINKEDIN_MAX_WORKERS=6
```

#### For Rate Limited Environments
```bash
LINKEDIN_MAX_THREADS=1
LINKEDIN_RETRY_DELAY=10
LINKEDIN_MAX_CONSECUTIVE_404=10
```

## 🔍 Troubleshooting

### Common Issues

#### Database Connection
```bash
# Test connection
python -c "import os; from models import SessionLocal; session = SessionLocal(); session.execute('SELECT 1'); print('DB OK')"
```

#### Loki Authentication
```bash
# Check logs locally
python -c "import logging; logging.basicConfig(level=logging.DEBUG); from main import setup_loki_logging; setup_loki_logging()"
```

#### Threading Issues
```bash
# Reduce threads for debugging
LINKEDIN_MAX_THREADS=1
```

### Debug Mode
```bash
# Enable debug logging
export PYTHONPATH=/app
python -c "import logging; logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')"
```

## 📈 Performance Benchmarks

### Typical Performance (Railway)
- **Discovery**: ~50 jobs/minute
- **Extraction**: ~5-8 jobs/minute per thread
- **Total throughput**: ~10-15 jobs/minute
- **Memory usage**: ~200-300MB
- **CPU usage**: 20-40% (2 threads)

### Scaling Recommendations

| Use Case | Threads | Workers | Expected Throughput |
|----------|---------|---------|-------------------|
| Development | 1 | 2 | 5 jobs/min |
| Production | 2-3 | 4-6 | 15-25 jobs/min |
| High Volume | 3-5 | 8-10 | 30-50 jobs/min |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## 📄 License

MIT License - see LICENSE file for details.

## 🆘 Support

For issues and questions:
- Check the troubleshooting section
- Review Grafana Loki logs
- Monitor Railway application logs
- Create an issue in the repository

---

**Built with ❤️ for reliable LinkedIn job data extraction**
