# Development Guide

This guide covers local development setup, testing, and contribution guidelines for the Multi-Cloud Cost Monitor.

## Local Development Setup

### Prerequisites

- Python 3.8+
- PostgreSQL 13+
- Redis 6+
- Git

### Quick Setup

```bash
# Clone the repository
git clone <repository-url>
cd cost-monitor

# Install dependencies
pip install -r requirements.txt

# Copy configuration template
cp config/config.example.yaml config/config.local.yaml

# Set up database
createdb cost_monitor
psql cost_monitor < database/add_aws_accounts_table.sql

# Start Redis
redis-server

# Start the API service
python -m src.main api

# In another terminal, start the dashboard
python -m src.main dashboard
```

### Manual Local Setup

If you prefer manual setup:

```bash
# Install dependencies
pip install -r requirements.txt

# Copy configuration template
cp config/config.example.yaml config/config.local.yaml

# Edit configuration with your settings
nano config/config.local.yaml

# Set up database
createdb cost_monitor
psql cost_monitor < database/add_aws_accounts_table.sql

# Start Redis
redis-server

# Start the API service
python -m src.main api

# In another terminal, start the dashboard
python -m src.main dashboard
```

### Environment Variables

Create a `.env.local` file for development:

```bash
# Database
DATABASE_URL=postgresql://username:password@localhost:5432/cost_monitor

# Redis
REDIS_URL=redis://localhost:6379

# AWS
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_DEFAULT_REGION=us-east-1

# Azure
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret

# GCP
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# Development settings
DEBUG=true
LOG_LEVEL=DEBUG
```

## Docker Development

### Docker Compose Setup

For a complete local environment with dependencies:

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f api
docker-compose logs -f dashboard

# Stop services
docker-compose down
```

The Docker Compose setup includes:
- PostgreSQL database
- Redis cache
- FastAPI backend
- Dash dashboard
- pgAdmin for database management

### Individual Container Development

Build and run individual containers:

```bash
# Build API container
docker build -f dockerfiles/Dockerfile.data-service -t cost-monitor-api .

# Build dashboard container
docker build -f dockerfiles/Dockerfile.dashboard -t cost-monitor-dashboard .

# Run API container
docker run -p 8000:8000 \
    -e DATABASE_URL=postgresql://user:pass@host:5432/db \
    -e REDIS_URL=redis://host:6379 \
    cost-monitor-api

# Run dashboard container
docker run -p 8050:8050 \
    -e API_BASE_URL=http://api:8000 \
    cost-monitor-dashboard
```

### Docker Development Tips

- Use volume mounts for live code reloading:
  ```bash
  docker run -v $(pwd)/src:/app/src cost-monitor-api
  ```

- Override entrypoint for debugging:
  ```bash
  docker run --entrypoint /bin/bash -it cost-monitor-api
  ```

- Use Docker networks for service communication:
  ```bash
  docker network create cost-monitor
  docker run --network cost-monitor --name redis redis:alpine
  docker run --network cost-monitor -e REDIS_URL=redis://redis:6379 cost-monitor-api
  ```

## Project Structure

```
cost-monitor/
├── src/                           # Main application code
│   ├── main.py                    # CLI entry point and command definitions
│   ├── api/                       # FastAPI backend
│   │   ├── data_service.py        # API endpoints and business logic
│   │   └── aws_accounts.py        # AWS account name resolution
│   ├── providers/                 # Cloud provider implementations
│   │   ├── base.py                # Abstract provider interface
│   │   ├── aws.py                 # AWS Cost Explorer integration
│   │   ├── azure.py               # Azure billing exports
│   │   └── gcp.py                 # GCP BigQuery billing
│   ├── visualization/             # Dashboard interface
│   │   └── dashboard.py           # Plotly Dash application
│   ├── monitoring/                # Alerting and monitoring
│   │   ├── alerts.py              # Alert system
│   │   ├── icinga.py              # Icinga/Nagios integration
│   │   └── text_alerts.py         # Notification handlers
│   ├── utils/                     # Shared utilities
│   │   ├── auth.py                # Authentication helpers
│   │   ├── cache.py               # Caching implementation
│   │   ├── data_normalizer.py     # Data normalization
│   │   └── http_client.py         # HTTP client utilities
│   ├── config/                    # Configuration management
│   │   └── settings.py            # Dynaconf configuration loader
│   ├── export/                    # Data export modules
│   │   └── prometheus.py          # Prometheus metrics
│   └── models/                    # Data models
├── openshift/                     # Kubernetes/OpenShift manifests
├── config/                        # Configuration files
├── docs/                          # Documentation
├── tests/                         # Test suite
├── database/                      # Database schemas
├── dockerfiles/                   # Docker build files
└── entrypoints/                   # Container entrypoints
```

## Development Workflow

### Making Changes

1. **Create a feature branch:**
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes and test locally:**
   ```bash
   python -m src.main api &
   python -m src.main dashboard &
   # Test your changes
   kill %1 %2  # Stop background processes
   ```

3. **Run tests:**
   ```bash
   pytest
   pytest --cov=src  # With coverage
   ```

4. **Check code quality:**
   ```bash
   # Format code
   black src/

   # Check imports
   isort src/

   # Lint code
   flake8 src/

   # Type checking
   mypy src/
   ```

### Testing

#### Unit Tests

```bash
# Run all tests
pytest

# Run specific test file
pytest tests/test_providers.py

# Run specific test class
pytest tests/test_providers.py::TestAWSProvider

# Run specific test method
pytest tests/test_providers.py::TestAWSProvider::test_get_costs

# Run with coverage
pytest --cov=src --cov-report=html
```

#### Integration Tests

```bash
# Test with real cloud providers (requires credentials)
pytest tests/integration/ -m integration

# Test specific provider
pytest tests/integration/test_aws_integration.py
```

#### End-to-End Tests

```bash
# Test full application flow
pytest tests/e2e/

# Test API endpoints
pytest tests/e2e/test_api.py

# Test dashboard functionality
pytest tests/e2e/test_dashboard.py
```

### Adding New Cloud Providers

To add support for a new cloud provider:

1. **Create provider implementation:**
   ```python
   # src/providers/newcloud.py
   from .base import CloudProvider

   class NewCloudProvider(CloudProvider):
       def __init__(self, config):
           super().__init__(config)

       async def get_costs(self, start_date, end_date, granularity='daily'):
           # Implementation here
           pass
   ```

2. **Add to provider registry:**
   ```python
   # src/providers/__init__.py
   from .newcloud import NewCloudProvider

   PROVIDERS = {
       'aws': AWSProvider,
       'azure': AzureProvider,
       'gcp': GCPProvider,
       'newcloud': NewCloudProvider,  # Add here
   }
   ```

3. **Add configuration schema:**
   ```yaml
   # config/config.example.yaml
   clouds:
     newcloud:
       enabled: false
       # Provider-specific configuration
   ```

4. **Add tests:**
   ```python
   # tests/test_providers.py
   class TestNewCloudProvider:
       def test_get_costs(self):
           # Test implementation
           pass
   ```

### Adding New API Endpoints

1. **Add endpoint to FastAPI app:**
   ```python
   # src/api/data_service.py
   @app.get("/api/v1/new-endpoint")
   async def new_endpoint():
       return {"message": "Hello from new endpoint"}
   ```

2. **Add tests:**
   ```python
   # tests/test_api.py
   def test_new_endpoint():
       response = client.get("/api/v1/new-endpoint")
       assert response.status_code == 200
   ```

3. **Update API documentation:**
   ```markdown
   # docs/API.md
   ### New Endpoint
   Description of new endpoint...
   ```

## Debugging

### Local Debugging

Enable debug mode for detailed logging:

```bash
# Environment variable
export DEBUG=true
export LOG_LEVEL=DEBUG

# Or in configuration
python -m src.main dashboard --debug
```

### Dashboard Debugging

For dashboard development, enable Dash debug mode:

```python
# src/visualization/dashboard.py
if __name__ == '__main__':
    app.run_server(debug=True, dev_tools_hot_reload=True)
```

### API Debugging

Use FastAPI's automatic documentation:

- Local: http://localhost:8000/docs
- OpenAPI schema: http://localhost:8000/openapi.json

### Database Debugging

Connect to PostgreSQL for debugging:

```bash
# Local database
psql cost_monitor

# OpenShift database (via port forward)
oc port-forward svc/postgresql 5432:5432
psql -h localhost -p 5432 -U cost_monitor cost_monitor
```

### Cache Debugging

Monitor Redis cache:

```bash
# Local Redis
redis-cli monitor

# Check cache keys
redis-cli keys "cost_monitor:*"

# Clear cache
redis-cli flushall
```

## Performance Optimization

### Profiling

Profile application performance:

```bash
# Profile CLI commands
python -m cProfile -o profile.stats -m src.main costs
python -c "import pstats; pstats.Stats('profile.stats').sort_stats('cumulative').print_stats(20)"

# Profile API endpoints
pip install py-spy
py-spy record -o profile.svg -- python -m src.main api
```

### Memory Usage

Monitor memory usage:

```bash
# Memory profiling
pip install memory-profiler
python -m memory_profiler src/main.py costs

# Monitor during development
htop
free -h
```

### Database Optimization

Optimize database queries:

```sql
-- Enable query logging
ALTER SYSTEM SET log_statement = 'all';
ALTER SYSTEM SET log_duration = 'on';

-- Analyze slow queries
SELECT query, mean_time, calls
FROM pg_stat_statements
ORDER BY mean_time DESC;
```

## Code Standards

### Python Style

- Follow PEP 8
- Use Black for formatting
- Use isort for import organization
- Maximum line length: 88 characters
- Use type hints where possible

### Documentation

- Docstrings for all public functions
- API documentation in docs/API.md
- Configuration examples in config/
- README updates for new features

### Commit Messages

Use conventional commit format:

```
feat: add new cloud provider support
fix: resolve cache invalidation issue
docs: update API documentation
test: add integration tests for Azure
refactor: improve error handling
```

## Troubleshooting Development Issues

### Common Issues

**Module import errors:**
```bash
# Ensure you're in the project root
cd /path/to/cost-monitor

# Use module syntax
python -m src.main --help
```

**Database connection errors:**
```bash
# Check PostgreSQL is running
pg_isready -h localhost -p 5432

# Test connection
psql postgresql://username:password@localhost:5432/cost_monitor
```

**Cache connection errors:**
```bash
# Check Redis is running
redis-cli ping

# Test connection
redis-cli -u redis://localhost:6379 ping
```

**Cloud provider authentication errors:**
```bash
# Test authentication
python -m src.main test-auth --provider aws --verbose

# Check credentials
aws sts get-caller-identity
az account show
gcloud auth list
```

For more troubleshooting information, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).