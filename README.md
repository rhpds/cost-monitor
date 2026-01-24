# Multi-Cloud Cost Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A comprehensive Python-based system for monitoring and analyzing cloud costs across AWS, Azure, and GCP with real-time visualization, intelligent alerting, and enterprise integrations.

## Features

- **Multi-Cloud Support**: Native integration with AWS, Azure, and GCP billing APIs
- **Real-Time Dashboard**: Interactive Plotly/Dash web interface with filtering and drill-down
- **REST API**: FastAPI backend for programmatic access to cost data
- **Intelligent Alerting**: Configurable thresholds with multiple notification channels
- **Enterprise Integration**: Prometheus/Grafana and Icinga/Nagios monitoring support
- **Production Ready**: OpenShift/Kubernetes deployment with OAuth, scaling, and security
- **Advanced Caching**: Redis and disk-based caching for performance optimization

## Quick Start (OpenShift/Kubernetes)

### Prerequisites

- OpenShift CLI (`oc`) or Kubernetes CLI (`kubectl`)
- Access to an OpenShift/Kubernetes cluster
- Cloud provider credentials (AWS, Azure, and/or GCP)

### Production Deployment

```bash
# Clone the repository
git clone <repository-url>
cd cost-monitor

# Copy and configure the deployment template
cp openshift/local-config.template.yaml openshift/local-config.yaml

# Edit the configuration with your cloud credentials and settings
nano openshift/local-config.yaml

# Deploy using the automated script
./deploy.sh
```

The deployment automatically creates:
- FastAPI backend service with health checks
- Interactive Plotly/Dash dashboard
- PostgreSQL database and Redis cache
- OAuth proxy for authentication
- Network policies and RBAC
- Configurable resource limits and scaling

### Environment Overlays

Choose the appropriate overlay for your environment:

```bash
# Development
oc apply -k openshift/overlays/development

# Staging
oc apply -k openshift/overlays/staging

# Production (with HA and resource limits)
oc apply -k openshift/overlays/production
```

### Access the Application

After deployment, get the dashboard URL:

```bash
oc get route cost-monitor-dashboard-route -o jsonpath='{.spec.host}'
```

## Alternative Installation Methods

### Docker Deployment

```bash
# Start all services with Docker Compose
docker-compose up -d

# Access dashboard at http://localhost:8050
# API available at http://localhost:8000
```

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Copy configuration template
cp config/config.example.yaml config/config.local.yaml

# Configure cloud providers (edit config/config.local.yaml)
# Start the dashboard
python -m src.main dashboard

# Or start the API service
python -m src.main api
```

## Quick CLI Usage

```bash
# Start interactive dashboard (local development)
python -m src.main dashboard

# Get cost summary
python -m src.main costs --provider aws --days 7 --format json

# Check cost thresholds (monitoring)
python -m src.main check --threshold 1000 --critical 2000

# Test cloud authentication
python -m src.main test-auth

# Export Prometheus metrics
python -m src.main export-prometheus
```

## Documentation

### Setup & Configuration
- [Configuration Guide](docs/CONFIGURATION.md) - Cloud providers and system configuration
- [AWS Setup](docs/AWS_PERMISSIONS.md) - AWS IAM permissions and setup
- [Azure Setup](docs/AZURE_SETUP.md) - Azure service principal configuration
- [GCP Setup](docs/GCP_SETUP.md) - GCP service account and BigQuery setup
- [OpenShift OAuth Setup](docs/OAUTH-SETUP.md) - Authentication configuration

### Usage & API
- [Dashboard Features](docs/DASHBOARD.md) - Interactive web dashboard usage
- [API Reference](docs/API.md) - REST API endpoints and examples
- [CLI Usage](docs/CLI.md) - Command-line interface guide

### Operations & Monitoring
- [Monitoring & Alerting](docs/MONITORING.md) - Threshold alerts and integrations
- [Prometheus/Grafana Setup](docs/GRAFANA_PROMETHEUS_SETUP.md) - Metrics and dashboards
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions

### Development & Deployment
- [Development Guide](docs/DEVELOPMENT.md) - Local development and testing
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment options

## Architecture

The system consists of three main layers:

1. **User Interfaces**: Web Dashboard (Dash/Plotly), CLI Tool (Click), REST API (FastAPI)
2. **Data Processing**: Data Normalizer, Cache Manager (Redis/Disk), Alert Engine
3. **Provider Layer**: AWS (Cost Explorer), Azure (Billing Exports), GCP (BigQuery)

## Technology Stack

- **Backend**: Python 3.8+, FastAPI, asyncpg (PostgreSQL), Redis
- **Frontend**: Dash, Plotly, Bootstrap components
- **Cloud SDKs**: boto3 (AWS), azure-* (Azure), google-cloud-* (GCP)
- **Deployment**: Kubernetes/OpenShift with Kustomize, Docker
- **Monitoring**: Prometheus, Icinga/Nagios integration

## Cloud Provider Setup

### AWS
Requires Cost Explorer access and optionally Organizations API for account names.
See [AWS_PERMISSIONS.md](docs/AWS_PERMISSIONS.md) for detailed IAM setup.

### Azure
Uses Cost Management API with service principal authentication.
See [AZURE_SETUP.md](docs/AZURE_SETUP.md) for service principal setup.

### GCP
Uses BigQuery billing export with service account authentication.
See [CONFIGURATION.md](docs/CONFIGURATION.md) for GCP setup details.

## Security

- **Authentication**: OpenShift OAuth proxy, service accounts
- **Network Security**: Network policies, RBAC, TLS
- **Secrets Management**: Kubernetes secrets, environment variables
- **Audit**: Cost access logging and monitoring

## Monitoring Integration

### Prometheus/Grafana
Export comprehensive cost metrics for monitoring dashboards.

### Icinga/Nagios
Native check plugins with performance data and threshold monitoring.

### Custom Alerts
Configurable cost thresholds with email, webhook, and console notifications.

## Contributing

We welcome contributions! See the documentation in the `docs/` directory for development setup and guidelines.

### Development Setup

```bash
git clone <repository-url>
cd cost-monitor
pip install -r requirements.txt
python -m src.main dashboard  # Start dashboard for development
```

## Support

- **Documentation**: Comprehensive guides in the `docs/` directory
- **Configuration**: Examples in the `config/` directory
- **Issues**: Report bugs and feature requests via GitHub Issues

## License

This project is licensed under the MIT License - see the LICENSE file for details.