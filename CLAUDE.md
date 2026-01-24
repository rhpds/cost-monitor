# Multi-Cloud Cost Monitor

A comprehensive Python-based system for monitoring and analyzing cloud costs across AWS, Azure, and GCP with real-time visualization, intelligent alerting, and enterprise integrations.

## Overview

This cost monitoring solution provides unified visibility into multi-cloud spending through an interactive dashboard, REST API, and monitoring integrations. It aggregates cost data from multiple cloud providers, normalizes it into a common format, and presents actionable insights through various interfaces.

### Key Features

- **Multi-Cloud Support**: Native integration with AWS, Azure, and GCP billing APIs
- **Real-Time Dashboard**: Interactive Plotly/Dash web interface with filtering and drill-down
- **REST API**: FastAPI backend for programmatic access to cost data
- **Intelligent Alerting**: Configurable thresholds with multiple notification channels
- **Enterprise Integration**: Prometheus/Grafana and Icinga/Nagios monitoring support
- **Production Ready**: OpenShift/Kubernetes deployment with OAuth, scaling, and security

## Quick Start (OpenShift/Kubernetes)

### Prerequisites

- OpenShift CLI (`oc`) or Kubernetes CLI (`kubectl`)
- Access to an OpenShift/Kubernetes cluster
- Cloud provider credentials (AWS, Azure, and/or GCP)

### Deployment

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

After deployment, access the dashboard via the OpenShift route:

```bash
# Get the dashboard URL
oc get route cost-monitor-dashboard-route -o jsonpath='{.spec.host}'
```

## Alternative Installation Methods

For non-production use, see:
- [Local Development Setup](docs/DEVELOPMENT.md) - Docker Compose and local Python setup
- [Docker Deployment](docs/DEVELOPMENT.md#docker-deployment) - Standalone Docker containers

## Documentation

### Setup & Configuration
- [Configuration Guide](docs/CONFIGURATION.md) - Detailed configuration options
- [AWS Setup](docs/AWS_PERMISSIONS.md) - AWS IAM permissions and setup
- [Azure Setup](docs/AZURE_SETUP.md) - Azure service principal configuration
- [OpenShift OAuth Setup](docs/oauth-setup.md) - Authentication configuration

### Usage & API
- [Dashboard Features](docs/DASHBOARD.md) - Interactive dashboard usage
- [API Reference](docs/API.md) - REST API endpoints and examples
- [CLI Usage](docs/CLI.md) - Command-line interface

### Operations & Monitoring
- [Monitoring & Alerting](docs/MONITORING.md) - Threshold alerts and integrations
- [Prometheus/Grafana Setup](docs/GRAFANA_PROMETHEUS_SETUP.md) - Metrics and dashboards
- [Troubleshooting](docs/TROUBLESHOOTING.md) - Common issues and solutions
- [Development Guide](docs/DEVELOPMENT.md) - Local development and testing

## Architecture

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
```

## Technology Stack

- **Backend**: Python 3.8+, FastAPI, asyncpg (PostgreSQL), Redis
- **Frontend**: Dash, Plotly, Bootstrap components
- **Cloud SDKs**: boto3 (AWS), azure-* (Azure), google-cloud-* (GCP)
- **Deployment**: Kubernetes/OpenShift with Kustomize, Docker
- **Monitoring**: Prometheus, Icinga/Nagios integration

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

## Support and Contributing

- **Issues**: Report bugs and feature requests via GitHub Issues
- **Documentation**: Comprehensive guides in the `docs/` directory
- **Configuration**: Examples in the `config/` directory
- **Local Development**: Use direct Python commands for local testing

## License

This project is licensed under the MIT License - see the LICENSE file for details.