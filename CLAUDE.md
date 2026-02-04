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
oc get route dashboard-route -n cost-monitor -o jsonpath='{.spec.host}'
```

## Git Branching and Deployment Strategy

### Branch Structure

The project uses a two-branch deployment model to separate development and production environments:

- **`main` branch** → **`cost-monitor-dev` namespace**
  - All development work and pull requests merge here
  - OpenShift BuildConfigs watch this branch and trigger automatic builds
  - Used for testing and validation before promoting to production
  - Developers can push directly to main for rapid iteration

- **`production` branch** → **`cost-monitor` namespace**
  - Production-ready, stable code only
  - OpenShift BuildConfigs watch this branch for production deployments
  - Tagged with semantic versions (v1.0.0, v1.1.0, etc.) for release tracking
  - Receives code via merge from main after validation in dev

### Automatic Build Triggers

Both namespaces have BuildConfigs configured to automatically trigger builds when their respective branches are updated:

- **Dev namespace**: Builds automatically when code is pushed to `main`
- **Prod namespace**: Builds automatically when code is pushed to `production`

#### GitHub Webhook Setup

The `./deploy.sh` script automatically generates secure webhook secrets and provides the webhook URLs at the end of deployment. To enable automatic builds on git push:

**1. Deploy the application:**
```bash
./deploy.sh  # for production
./deploy.sh dev  # for development
```

The script will output webhook URLs like:
```
🪝 GitHub Webhook Configuration:
Webhook 1 - cost-data-service:
   Payload URL: https://api.cluster.example.com:6443/.../webhooks/abc123/github
Webhook 2 - cost-monitor-dashboard:
   Payload URL: https://api.cluster.example.com:6443/.../webhooks/xyz789/github
```

**2. Configure webhooks in GitHub:**
- Navigate to: `https://github.com/rhpds/cost-monitor/settings/hooks`
- Click "Add webhook"
- Paste the Payload URL from deployment output
- Set Content type: `application/json`
- Select Events: `Just the push event`
- Click "Add webhook"
- Repeat for both BuildConfigs (cost-data-service and cost-monitor-dashboard)

**3. Verify webhook delivery:**
- After adding, GitHub will send a test ping
- Check that webhook shows a green checkmark ✓
- If you see a 403 error, verify the RoleBinding exists:
  ```bash
  oc get rolebinding webhook-access-unauthenticated -n <namespace>
  ```

**Security Note:**
OpenShift 4.16+ requires explicit RBAC permissions for unauthenticated webhook access. The deployment automatically creates a namespace-scoped RoleBinding that allows GitHub webhooks to trigger builds without exposing other cluster resources. This RoleBinding is defined in `openshift/base/security/webhook-rolebinding.yaml` and grants the `system:webhook` ClusterRole to the `system:unauthenticated` group within the namespace only.

#### Automatic Deployment Rollouts

The deployment script configures **ImageStream triggers** on Deployments to enable automatic rollouts when new images are built. This creates a fully automated CI/CD pipeline:

**How it works:**
1. Git push → GitHub webhook triggers BuildConfig
2. BuildConfig builds new image → Pushes to ImageStream
3. ImageStream update detected → Deployment automatically rolls out new pods
4. No manual `oc rollout restart` required

**Technical implementation:**
The deployment script runs:
```bash
oc set triggers deploy/cost-data-service --from-image=cost-data-service:latest -c cost-data-service
oc set triggers deploy/dashboard-service --from-image=cost-monitor-dashboard:latest -c dashboard
```

This sets the `image.openshift.io/triggers` annotation on each Deployment, which tells OpenShift to watch the specified ImageStreamTag and automatically update the deployment when a new image is pushed.

**Benefits:**
- ✅ Fully automated deployment pipeline
- ✅ Faster iteration cycles
- ✅ Consistent deployment behavior
- ✅ No manual intervention needed after code push

### Deployment Workflow

#### Deploying to Development

```bash
# 1. Make changes and commit to main
git checkout main
git add .
git commit -m "Your changes"
git push origin main

# 2. OpenShift automatically triggers builds in cost-monitor-dev
# Monitor build progress:
oc get builds -n cost-monitor-dev -w

# 3. Deployments automatically rollout when builds complete (no manual action needed)
# Monitor rollout progress:
oc get pods -n cost-monitor-dev -w

# 4. Verify deployment
oc rollout status deployment/cost-data-service -n cost-monitor-dev
```

#### Promoting to Production

```bash
# 1. Merge validated main branch to production
git checkout production
git merge main

# 2. Create release tag (semantic versioning)
git tag -a v1.1.0 -m "Release v1.1.0 - Azure background refresh fix"
git push origin production
git push origin v1.1.0

# 3. OpenShift automatically triggers builds in cost-monitor (production)
# Monitor build progress:
oc get builds -n cost-monitor -w

# 4. Deployments automatically rollout when builds complete (no manual action needed)
# Monitor rollout progress:
oc get pods -n cost-monitor -w

# 5. Verify production deployment
oc rollout status deployment/cost-data-service -n cost-monitor
```

#### Manual Build Trigger (if automatic triggers fail)

```bash
# Development
oc start-build cost-data-service -n cost-monitor-dev
oc start-build cost-monitor-dashboard -n cost-monitor-dev

# Production
oc start-build cost-data-service -n cost-monitor
oc start-build cost-monitor-dashboard -n cost-monitor
```

#### Hotfix Workflow

For urgent production fixes:

```bash
# 1. Create hotfix from production branch
git checkout production
git checkout -b hotfix/critical-bug-fix

# 2. Make the fix and test locally
# ... make changes ...
git commit -m "Fix critical bug"

# 3. Merge to production
git checkout production
git merge hotfix/critical-bug-fix
git tag -a v1.1.1 -m "Hotfix v1.1.1 - Critical bug fix"
git push origin production
git push origin v1.1.1

# 4. Backport to main
git checkout main
git merge hotfix/critical-bug-fix
git push origin main

# 5. Clean up
git branch -d hotfix/critical-bug-fix
```

### BuildConfig Details

The BuildConfigs are configured as follows:

```yaml
# Development (cost-monitor-dev)
spec:
  source:
    git:
      ref: main
      uri: https://github.com/rhpds/cost-monitor.git

# Production (cost-monitor)
spec:
  source:
    git:
      ref: production
      uri: https://github.com/rhpds/cost-monitor.git
```

Both configs include automatic triggers for:
- GitHub webhooks (when configured)
- ConfigChange (when BuildConfig is updated)
- ImageChange (when base Python image updates)

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

## Local Development Environment

### Prerequisites for Local Development

- Access to an OpenShift cluster with the cost-monitor application deployed
- OpenShift CLI (`oc`) installed and logged in
- `config/.secrets.yaml` file with cloud provider credentials

### Development Environment Setup

The project includes `scripts/dev-local-to-ocp.sh` for local development that connects to OpenShift services:

```bash
# Start all development services (API, Dashboard, and tunnels)
./scripts/dev-local-to-ocp.sh cost-monitor-dev start all

# Start individual components
./scripts/dev-local-to-ocp.sh cost-monitor-dev start api
./scripts/dev-local-to-ocp.sh cost-monitor-dev start dashboard
./scripts/dev-local-to-ocp.sh cost-monitor-dev start postgres-tunnel
./scripts/dev-local-to-ocp.sh cost-monitor-dev start redis-tunnel

# Check status of all services
./scripts/dev-local-to-ocp.sh cost-monitor-dev status all

# Stop all services
./scripts/dev-local-to-ocp.sh cost-monitor-dev stop all
```

### Accessing PostgreSQL Database

#### Method 1: Via Tunnel (Recommended)
```bash
# Start PostgreSQL tunnel
./scripts/dev-local-to-ocp.sh cost-monitor-dev start postgres-tunnel

# Connect via tunnel (if you have psql installed locally)
export PGPASSWORD=$(oc get secret postgresql-credentials -n cost-monitor-dev -o jsonpath='{.data.password}' | base64 -d)
psql -h localhost -p 5432 -U $(oc get secret postgresql-credentials -n cost-monitor-dev -o jsonpath='{.data.username}' | base64 -d) -d $(oc get secret postgresql-credentials -n cost-monitor-dev -o jsonpath='{.data.database}' | base64 -d)
```

#### Method 2: Direct Pod Access
```bash
# Get credentials
export PGUSER=$(oc get secret postgresql-credentials -n cost-monitor-dev -o jsonpath='{.data.username}' | base64 -d)
export PGDATABASE=$(oc get secret postgresql-credentials -n cost-monitor-dev -o jsonpath='{.data.database}' | base64 -d)

# Execute SQL directly on the pod
oc exec postgresql-0 -n cost-monitor-dev -- psql -U "$PGUSER" -d "$PGDATABASE" -c "
SELECT
    date,
    COUNT(*) as records,
    SUM(cost::numeric) as total_cost
FROM cost_data_points
WHERE provider_id = 1 AND date >= '2026-02-01'
GROUP BY date ORDER BY date DESC LIMIT 5;
"
```

### Common Database Queries

```sql
-- Check provider IDs (1=AWS, 2=Azure, 3=GCP)
SELECT provider_id, COUNT(*) as records FROM cost_data_points GROUP BY provider_id;

-- Check recent AWS cost data
SELECT date, COUNT(*) as services, SUM(cost::numeric) as total_cost
FROM cost_data_points
WHERE provider_id = 1 AND date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY date ORDER BY date;

-- Find top cost services for specific date
SELECT service_name, SUM(cost::numeric) as total_cost
FROM cost_data_points
WHERE provider_id = 1 AND date = '2026-02-01'
GROUP BY service_name ORDER BY total_cost DESC LIMIT 10;

-- Check data collection timestamps
SELECT date, MIN(collected_at), MAX(collected_at), COUNT(*)
FROM cost_data_points
WHERE provider_id = 1 AND date = '2026-02-01'
GROUP BY date;
```

### Caching Architecture

The application uses a **simplified caching architecture** with PostgreSQL as the single source of truth:

#### 1. PostgreSQL Database (Primary Storage)
- **Location**: PostgreSQL database with `cost_data_points` table
- **Function**: Single source of truth for all cost data with collection timestamps
- **Persistence**: All collected data is permanently stored with `collected_at` metadata
- **Optimization**: Indexed by date, provider, and collection timestamp for fast queries

#### 2. Redis Cache (API Performance)
- **Location**: Redis server (configured via `REDIS_URL`)
- **Function**: Caches API responses for dashboard performance
- **TTL**: 30 minutes for API responses
- **Auto-Clear**: Automatically cleared on `force_refresh=true` API calls
- **Clear manually**:
  ```bash
  oc exec redis-<pod-name> -n cost-monitor-dev -- redis-cli -a "<password>" flushall
  ```

#### 3. Async Background Refresh
- **Strategy**: Serve data immediately, refresh in background if stale
- **Trigger**: Automatic when data is older than 24 hours
- **User Awareness**: API responses include freshness metadata:
  ```json
  {
    "data_freshness": "stale_data_refreshing",
    "background_refresh_triggered": true,
    "refresh_status": "Background refresh started for aws, azure, gcp",
    "freshness_metadata": {
      "aws": {
        "status": "stale",
        "last_collected": "2026-01-30T00:21:54.786092+00:00",
        "data_age_hours": 113.7,
        "is_stale": true
      }
    }
  }
  ```

#### Cache Troubleshooting
```bash
# Force refresh with automatic cache clearing
curl "http://localhost:8000/api/v1/costs/summary?force_refresh=true&start_date=2026-02-01&end_date=2026-02-01&provider=aws"

# Clear Redis cache manually
oc exec redis-<pod-name> -n cost-monitor-dev -- redis-cli -a "$(oc get secret redis-credentials -n cost-monitor-dev -o jsonpath='{.data.password}' | base64 -d)" flushall

# Check data freshness without cache
curl "http://localhost:8000/api/v1/costs/summary?start_date=2026-02-01&end_date=2026-02-01" | jq '.data_freshness, .freshness_metadata'
```

### Data Collection Behavior

**Important**: The cost monitor uses **hybrid data collection** with async background refresh:

- **Immediate response**: API serves existing data from PostgreSQL immediately for fast response
- **Background refresh**: Automatically triggered when data is older than 24 hours
- **User awareness**: API responses include freshness status and collection timestamps
- **Provider delays** (affects refresh timing):
  - AWS: 2-day delay before data is considered complete
  - Azure/GCP: 1-day delay
- **Force refresh**: Use `force_refresh=true` to bypass cache and trigger immediate collection
- **Data persistence**: All collected data permanently stored in PostgreSQL with collection metadata

### Troubleshooting Common Issues

#### Missing/Incomplete Cost Data
1. Check if data exists in database: Use SQL queries above
2. Verify collection timestamps: Look for gaps in `collected_at` field
3. Force refresh: Use API endpoint with `force_refresh=true`
4. Clear caches: Remove cached data and trigger re-collection
5. Check provider authentication: `python -m src.main test-auth`

#### Development Environment Issues
```bash
# Check all services status
./scripts/dev-local-to-ocp.sh cost-monitor-dev status all

# View service logs
./scripts/dev-local-to-ocp.sh cost-monitor-dev logs api
./scripts/dev-local-to-ocp.sh cost-monitor-dev logs dashboard

# Restart problematic services
./scripts/dev-local-to-ocp.sh cost-monitor-dev restart api
```

## Code Quality Standards

This project enforces strict code quality standards through automated pre-commit hooks. All code must pass these standards before being committed.

### Python Code Standards

**Formatting (Black)**:
- Maximum line length: 88 characters
- Use double quotes for strings
- Consistent indentation (4 spaces)
- Proper spacing around operators and commas
- Function arguments wrapped appropriately for readability

**Import Organization (isort)**:
- Imports grouped in order: standard library, third-party, local
- Alphabetical sorting within each group
- Proper spacing between import groups
- Multi-line imports formatted consistently

**Linting (Ruff)**:
- No unused variables or imports
- No undefined names
- Proper exception handling
- PEP 8 compliance
- No dead code

**Type Checking (mypy)**:
- Type hints for function parameters and return values
- Proper typing for complex data structures
- No type errors or inconsistencies

### Pre-Commit Hook Process

The project uses automated pre-commit hooks that will:
1. **Check and fix formatting issues** (Black, isort)
2. **Identify and fix linting problems** (Ruff)
3. **Validate type annotations** (mypy)
4. **Detect security issues** (secrets detection)
5. **Run basic smoke tests** (API endpoints)

**Important**: If any tool modifies your code during commit:
1. The commit will fail (this is intentional)
2. Re-stage the modified files: `git add .`
3. Commit again: `git commit -m "message"`

### Development Best Practices

**Code Structure**:
- Clean up unused variables immediately after code changes
- Remove debugging statements before committing
- Maintain consistent indentation within files
- Write self-documenting code with clear variable names

**File Modifications**:
- When editing existing files, preserve the existing style
- Don't mix formatting changes with functional changes
- Remove any temporary/debugging code before committing

**Error Prevention**:
- Run `pre-commit run --all-files` before committing to catch issues early
- Use proper line length to avoid Black reformatting
- Clean up all unused imports and variables
- Follow existing patterns in the codebase

### Quality Gates

All code must pass:
- ✅ **Formatting**: Black, isort compliance
- ✅ **Linting**: Ruff error-free
- ✅ **Type Safety**: mypy validation
- ✅ **Security**: No hardcoded secrets
- ✅ **Functionality**: Basic smoke tests
- ✅ **Standards**: Consistent with existing codebase

These standards ensure code quality, maintainability, and team collaboration effectiveness.

## Support and Contributing

- **Issues**: Report bugs and feature requests via GitHub Issues
- **Documentation**: Comprehensive guides in the `docs/` directory
- **Configuration**: Examples in the `config/` directory
- **Local Development**: Use direct Python commands for local testing

## License

This project is licensed under the MIT License - see the LICENSE file for details.