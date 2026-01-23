# Multi-Cloud Cost Monitor

A comprehensive Python-based system for monitoring and analyzing cloud costs across AWS, Azure, and GCP with real-time visualization, intelligent alerting, and enterprise integrations.

## 🎯 Overview

This cost monitoring solution provides unified visibility into multi-cloud spending through an interactive dashboard, REST API, and monitoring integrations. It aggregates cost data from multiple cloud providers, normalizes it into a common format, and presents actionable insights through various interfaces.

### Key Features

- **Multi-Cloud Support**: Native integration with AWS, Azure, and GCP billing APIs
- **Real-Time Dashboard**: Interactive Plotly/Dash web interface with filtering and drill-down
- **REST API**: FastAPI backend for programmatic access to cost data
- **Intelligent Alerting**: Configurable thresholds with multiple notification channels
- **Enterprise Integration**: Prometheus/Grafana and Icinga/Nagios monitoring support
- **Flexible Deployment**: Docker, Kubernetes, OpenShift ready with multiple configuration options
- **Advanced Caching**: Redis and disk-based caching for performance optimization

## 🏗 Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────┐
│                    User Interfaces                         │
├─────────────────┬─────────────────┬─────────────────────────┤
│  Web Dashboard  │    CLI Tool     │    REST API             │
│   (Dash/Plotly) │   (Click)      │    (FastAPI)            │
└─────────────────┴─────────────────┴─────────────────────────┘
           │                │                      │
           └────────────────┼──────────────────────┘
                           │
┌─────────────────────────────────────────────────────────────┐
│                 Data Processing Layer                       │
├─────────────────┬─────────────────┬─────────────────────────┤
│  Data Normalizer│  Cache Manager  │  Alert Engine           │
│  (Multi-cloud)  │ (Redis/Disk)    │ (Threshold Monitor)     │
└─────────────────┴─────────────────┴─────────────────────────┘
           │
┌─────────────────────────────────────────────────────────────┐
│                  Provider Layer                             │
├─────────────────┬─────────────────┬─────────────────────────┤
│   AWS Provider  │ Azure Provider  │   GCP Provider          │
│ (Cost Explorer) │(Billing Exports)│  (BigQuery)             │
└─────────────────┴─────────────────┴─────────────────────────┘
           │               │                 │
┌─────────────────┬─────────────────┬─────────────────────────┐
│   AWS APIs      │   Azure APIs    │    GCP APIs             │
│                 │                 │                         │
└─────────────────┴─────────────────┴─────────────────────────┘
```

### Technology Stack

- **Backend**: Python 3.8+, FastAPI, asyncpg (PostgreSQL), Redis
- **Frontend**: Dash, Plotly, Bootstrap components
- **Cloud SDKs**: boto3 (AWS), azure-* (Azure), google-cloud-* (GCP)
- **Data Processing**: pandas, tenacity (retry logic)
- **Configuration**: Dynaconf (flexible configuration management)
- **Monitoring**: Prometheus client, Icinga/Nagios integration
- **Deployment**: Docker, Kubernetes/OpenShift with Kustomize

## 🚀 Quick Start

### Prerequisites

- Python 3.8+
- Cloud provider credentials (AWS, Azure, and/or GCP)
- PostgreSQL 13+ (for persistence)
- Redis 6+ (for caching)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd cost-monitor

# Install dependencies
pip install -r requirements.txt

# Copy configuration template
cp config/config.example.yaml config/config.local.yaml

# Configure cloud providers (edit config/config.local.yaml)
# Add your cloud credentials and settings

# Run the dashboard
python -m src.main dashboard

# Or start the API service
python -m src.main api
```

### Docker Deployment

```bash
# Start all services with Docker Compose
docker-compose up -d

# Access dashboard at http://localhost:8050
# API available at http://localhost:8000
```

## 📊 Dashboard Features

### Cost Visualization
- **Daily/Monthly Trends**: Time-series charts with provider breakdowns
- **Service Analysis**: Cost breakdown by cloud services with filtering
- **Geographic Distribution**: Regional cost analysis
- **Account/Project Views**: Multi-account and project-level breakdowns

### Interactive Controls
- **Date Range Picker**: Flexible time period selection with presets
- **Provider Filtering**: Toggle between All/AWS/Azure/GCP views
- **Metric Selection**: Switch between different cost metric types
- **Auto-Refresh**: Configurable real-time data updates

### Performance Features
- **Smart Caching**: Figure-level caching with invalidation
- **Lazy Loading**: Paginated data loading for large datasets
- **Log Scale**: Automatic scale detection for mixed-magnitude data
- **Mobile Responsive**: Optimized for mobile and tablet viewing

## 🔧 Configuration

### Cloud Provider Setup

**AWS Configuration**:
```yaml
clouds:
  aws:
    enabled: true
    region: us-east-1
    access_key_id: ${AWS_ACCESS_KEY_ID}
    secret_access_key: ${AWS_SECRET_ACCESS_KEY}
    # Optional: Use IAM roles or AWS profiles
    profile: default
```

**Azure Configuration**:
```yaml
clouds:
  azure:
    enabled: true
    tenant_id: ${AZURE_TENANT_ID}
    client_id: ${AZURE_CLIENT_ID}
    client_secret: ${AZURE_CLIENT_SECRET}
    export:
      storage_account: billing-exports
      container: cost-exports
      export_name: monthly-actual
```

**GCP Configuration**:
```yaml
clouds:
  gcp:
    enabled: true
    project_id: your-billing-project
    credentials_path: /path/to/service-account.json
    bigquery_billing_dataset: billing_export
    billing_account_id: 012345-ABCDEF-GHIJKL
```

### Caching Configuration

```yaml
cache:
  enabled: true
  type: "redis"  # or "disk" or "memory"
  redis_url: "redis://localhost:6379"
  ttl: 3600  # seconds

  # Provider-specific cache TTL
  aws:
    ttl: 3600
  azure:
    ttl: 7200    # Azure data updates less frequently
  gcp:
    ttl: 3600
```

### Dashboard Settings

```yaml
dashboard:
  enabled: true
  host: "0.0.0.0"
  port: 8050
  debug: false
  auto_refresh: true
  refresh_interval: 300  # seconds
  default_range_days: 30
  max_accounts_display: 20
```

## 📈 Monitoring & Alerting

### Threshold Alerts

Configure cost thresholds for automated alerting:

```yaml
monitoring:
  thresholds:
    daily:
      warning: 1000.00
      critical: 2000.00
    monthly:
      warning: 25000.00
      critical: 50000.00

  # Alert channels
  notifications:
    email:
      enabled: true
      smtp_server: smtp.company.com
      from: alerts@company.com
      to: ["finance@company.com", "ops@company.com"]

    webhook:
      enabled: true
      url: "https://hooks.slack.com/services/..."
```

### Prometheus Integration

Export metrics for Grafana dashboards:

```bash
# Export current metrics
python -m src.main export-prometheus --output /tmp/cost_metrics.prom

# Push to Pushgateway
python -m src.main export-prometheus --pushgateway http://pushgateway:9091
```

### Icinga/Nagios Integration

Monitor cost thresholds with Icinga:

```bash
# Check daily costs
python -m src.main check --provider aws --threshold 1000 --critical 2000

# Exit codes: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
```

## 🔌 API Reference

### Core Endpoints

- `GET /api/health/ready` - Service readiness check
- `GET /api/health/live` - Service liveness check
- `GET /api/v1/costs/summary` - Cost summary with breakdowns
- `GET /api/v1/costs/daily` - Daily cost trends
- `GET /api/v1/costs/services` - Service-level breakdown
- `GET /api/v1/costs/accounts` - Account/project breakdown

### Query Parameters

- `start_date` / `end_date` - Date range (YYYY-MM-DD)
- `provider` - Filter by provider (aws/azure/gcp)
- `granularity` - Data granularity (daily/monthly)
- `force_refresh` - Bypass cache (true/false)

### Example Usage

```bash
# Get cost summary for last 7 days
curl "http://localhost:8000/api/v1/costs/summary?start_date=2025-01-16&end_date=2025-01-23"

# AWS-only costs with fresh data
curl "http://localhost:8000/api/v1/costs/summary?provider=aws&force_refresh=true"
```

## 🛠 CLI Usage

### Available Commands

```bash
# Start interactive dashboard
python -m src.main dashboard

# Get cost data
python -m src.main costs --provider aws --days 7

# Check thresholds (monitoring)
python -m src.main check --threshold 1000

# Test cloud authentication
python -m src.main test-auth

# Export Prometheus metrics
python -m src.main export-prometheus

# View active alerts
python -m src.main alerts
```

### Output Formats

```bash
# JSON output
python -m src.main costs --format json

# Table format (default)
python -m src.main costs --format table

# CSV export
python -m src.main costs --format csv > costs.csv
```

## 🏭 Production Deployment

### OpenShift/Kubernetes

```bash
# Deploy with Kustomize
kubectl apply -k openshift/overlays/production

# Or using OpenShift CLI
oc apply -k openshift/overlays/production
```

### Configuration Management

Use environment-specific overlays:

- `openshift/overlays/development/` - Development environment
- `openshift/overlays/staging/` - Staging environment
- `openshift/overlays/production/` - Production environment

### Security Considerations

- **Secrets Management**: Use Kubernetes secrets for cloud credentials
- **Network Policies**: Restrict inter-service communication
- **RBAC**: Configure appropriate service account permissions
- **TLS**: Enable HTTPS for external routes
- **Audit Logging**: Enable audit logs for cost access

## 📝 Development

### Local Development

Use the test harness for local development:

```bash
# Start local development environment
./test-harness.sh start

# View logs
./test-harness.sh logs api
./test-harness.sh logs dashboard

# Stop services
./test-harness.sh stop
```

### Code Structure

```
src/
├── main.py                    # CLI entry point
├── api/
│   └── data_service.py        # FastAPI backend
├── providers/                 # Cloud provider implementations
│   ├── base.py                # Abstract provider interface
│   ├── aws.py                 # AWS Cost Explorer integration
│   ├── azure.py               # Azure billing exports
│   └── gcp.py                 # GCP BigQuery billing
├── visualization/
│   └── dashboard.py           # Plotly Dash dashboard
├── monitoring/                # Alerting and monitoring
├── utils/                     # Common utilities
├── config/                    # Configuration management
└── export/                    # Data export modules
```

### Testing

```bash
# Run test suite
pytest

# Test with coverage
pytest --cov=src

# Test specific provider
pytest tests/test_providers.py::TestAWSProvider
```

## 🔍 Troubleshooting

### Common Issues

**Authentication Errors**:
- Verify cloud credentials are properly configured
- Check IAM/service principal permissions
- Test authentication with `python -m src.main test-auth`

**Cache Issues**:
- Clear cache: `redis-cli FLUSHALL` (Redis) or delete cache directory
- Disable cache temporarily: Set `cache.enabled: false`
- Check cache connectivity and permissions

**Performance Issues**:
- Monitor cache hit rates in logs
- Adjust cache TTL settings per provider
- Consider increasing Redis memory limits
- Use smaller date ranges for testing

**Dashboard Not Loading**:
- Check FastAPI service is running (`/api/health/ready`)
- Verify database connectivity
- Check for JavaScript console errors
- Restart dashboard service

### Debug Logging

Enable debug logging for troubleshooting:

```yaml
# config/config.local.yaml
logging:
  level: DEBUG

dashboard:
  debug: true
```

### Support

For issues and feature requests:
- Check existing documentation in `docs/` directory
- Review configuration examples in `config/` directory
- Enable debug logging for detailed error information
- Test individual components with CLI commands

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgments

- Built with Python ecosystem: FastAPI, Dash, Plotly, pandas
- Cloud SDKs: boto3 (AWS), azure-sdk (Azure), google-cloud (GCP)
- Infrastructure: PostgreSQL, Redis, Docker, Kubernetes/OpenShift
- Monitoring: Prometheus, Grafana, Icinga/Nagios integration