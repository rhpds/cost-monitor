# Multi-Cloud Cost Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-71%20passing-brightgreen.svg)](tests/)
[![Code Quality](https://img.shields.io/badge/quality-pre--commit--enabled-brightgreen.svg)](.pre-commit-config.yaml)

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
oc get route dashboard-route -n cost-monitor -o jsonpath='{.spec.host}'
```

## Git Branching and Deployment Strategy

The project uses a two-branch strategy for managing deployments:

### Branch Structure

- **`main`** - Development branch
  - All development work happens here
  - Automatically triggers builds in `cost-monitor-dev` namespace
  - Used for testing and validation before production

- **`production`** - Production branch
  - Stable, production-ready code
  - Automatically triggers builds in `cost-monitor` namespace
  - Tagged with semantic versions (v1.0.0, v1.1.0, etc.)

### Deployment Workflow

**Development Deployment:**
```bash
# Push changes to main
git push origin main

# Dev builds trigger automatically in cost-monitor-dev namespace
# Monitor build progress:
oc get builds -n cost-monitor-dev -w

# Deployments automatically rollout when builds complete (no manual action needed)
oc get pods -n cost-monitor-dev -w
```

**Production Deployment:**
```bash
# 1. Merge main to production
git checkout production
git merge main
git push origin production

# 2. Create release tag
git tag -a v1.1.0 -m "Release v1.1.0 - Description of changes"
git push origin v1.1.0

# 3. Production builds trigger automatically in cost-monitor namespace
# Monitor build progress:
oc get builds -n cost-monitor -w

# 4. Deployments automatically rollout when builds complete (no manual action needed)
oc get pods -n cost-monitor -w
```

**Manual Build Trigger (if needed):**
```bash
# Dev
oc start-build cost-data-service -n cost-monitor-dev
oc start-build cost-monitor-dashboard -n cost-monitor-dev

# Prod
oc start-build cost-data-service -n cost-monitor
oc start-build cost-monitor-dashboard -n cost-monitor
```

### GitHub Webhook Configuration

The deployment script automatically generates webhook secrets for GitHub integration. To enable automatic builds on git push:

**1. Run the deployment script** which will output webhook URLs at the end:
```bash
./deploy.sh
```

**2. Configure webhooks in GitHub:**
- Go to your repository: `https://github.com/rhpds/cost-monitor/settings/hooks`
- Add webhook for cost-data-service BuildConfig
- Add webhook for cost-monitor-dashboard BuildConfig
- Use the URLs provided by the deployment script
- Set Content type: `application/json`
- Select Events: `Just the push event`

**3. Verify webhook setup:**
- Webhooks will show a green checkmark if successful
- Failed webhooks (403 error) indicate missing RBAC permissions

**Note:** OpenShift 4.16+ requires a RoleBinding to allow unauthenticated webhook access. This is automatically created during deployment and is namespace-scoped for security.

**4. Automatic rollouts enabled:**
The deployment script configures ImageStream triggers so deployments automatically rollout when builds complete. This means:
- Git push → GitHub webhook → Build starts → Build completes → **Deployment auto-rollouts** ✅
- No manual `oc rollout restart` needed
- Uses OpenShift's `image.openshift.io/triggers` annotation on Deployments

## Parsec Integration

[Parsec](https://github.com/rhpds/parsec) is a natural language cloud cost investigation tool that uses Claude to answer cost questions. It integrates with cost-monitor as a data source.

- **Parsec queries cost-monitor**: Parsec's `query_cost_monitor` tool calls the cost-data-service REST API (`/api/v1/costs/summary`, `/api/v1/costs/aws/breakdown`, etc.) for aggregated cost data. This is a server-to-server call within the OpenShift cluster.
- **Cost-monitor links to Parsec**: The dashboard header includes a "Parsec AI Explorer" button for deeper natural language investigation.
- **Shared cluster**: Both apps deploy to the same OpenShift cluster (`cost-monitor-dev`/`cost-monitor` and `parsec-dev`/`parsec` namespaces).
- **Shared auth**: Both use the same group-based authorization pattern (OAuth proxy + app-level OpenShift group checks).

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
- [Testing Strategy](docs/TESTING.md) - Comprehensive testing approach and workflows
- [Deployment Guide](docs/DEPLOYMENT.md) - Production deployment options

## Architecture

The system consists of three main layers:

1. **User Interfaces**: Web Dashboard (Dash/Plotly), CLI Tool (Click), REST API (FastAPI)
2. **Data Processing**: Data Normalizer, Cache Manager (Redis/Disk), Alert Engine
3. **Provider Layer**: AWS (Cost Explorer), Azure (Billing Exports), GCP (BigQuery)

## Technology Stack

- **Backend**: Python 3.11+, FastAPI, asyncpg (PostgreSQL), Redis
- **Frontend**: Dash, Plotly, Bootstrap components
- **Cloud SDKs**: boto3 (AWS), azure-* (Azure), google-cloud-* (GCP)
- **Deployment**: Kubernetes/OpenShift with Kustomize, Docker
- **Monitoring**: Prometheus, Icinga/Nagios integration

## Testing & Quality Assurance

The project maintains **100% test reliability** with comprehensive quality gates:

### 🧪 **Multi-Tier Test Strategy**
- **71/71 Integration Tests** - Complete API, database, and workflow coverage
- **Pre-commit Smoke Tests** - Critical functionality validation in <1 second
- **Fast Development Tests** - Quick iteration feedback in ~3 seconds
- **Full Coverage Tests** - Comprehensive validation with coverage reporting

### 🛡️ **Automated Quality Gates**
- **Secret Scanning**: detect-secrets + gitleaks prevent credential leaks
- **Code Formatting**: black + isort automatic formatting
- **Comprehensive Linting**: ruff + mypy with type safety
- **Dead Code Detection**: vulture removes unused code
- **Critical Testing**: Pre-commit hooks ensure core functionality

### 🚀 **Developer Experience**
```bash
# Quick development commands
./scripts/dev.sh test-smoke   # Pre-commit tests (~1s)
./scripts/dev.sh test-fast    # Quick iteration (~3s)
./scripts/dev.sh test-all     # Full suite (71 tests, ~6s)
./scripts/dev.sh quality      # Complete quality check

# Automatic on every commit
git commit  # Runs security + quality + tests automatically
```

See [TESTING.md](TESTING.md) for complete testing strategy and workflows.

## Cloud Provider Setup

### AWS
Requires Cost Explorer access and optionally Organizations API for account names.
See [AWS_PERMISSIONS.md](docs/AWS_PERMISSIONS.md) for detailed IAM setup.

### Azure
Uses Cost Management API with service principal authentication.
See [AZURE_SETUP.md](docs/AZURE_SETUP.md) for service principal setup.

### GCP
Uses BigQuery billing export with service account authentication.
See [GCP_SETUP.md](docs/GCP_SETUP.md) for detailed GCP setup instructions.

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
