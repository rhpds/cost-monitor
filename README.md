# Multi-Cloud Cost Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

A comprehensive Python tool for monitoring costs across AWS, Azure, and GCP with support for visualization, alerting, and Icinga integration.

## 🎯 Features

- **📊 Multi-Cloud Support**: Monitor costs across AWS, Azure, and GCP from a single interface
- **🎨 Interactive Dashboard**: Real-time Plotly-based web dashboard with cost visualizations
- **📈 Grafana Integration**: Export dashboards to Grafana with Prometheus metrics
- **⚠️ Intelligent Alerting**: Configurable thresholds with console, email, and webhook notifications
- **🔍 Icinga Integration**: Native Nagios/Icinga check plugins with performance data
- **⚙️ Flexible Configuration**: YAML configuration with environment variable overrides
- **📈 Cost Analytics**: Service breakdowns, regional analysis, and trend forecasting
- **💾 Smart Caching**: Reduce cloud provider calls and costs with intelligent caching strategies
- **🐳 Container Ready**: Docker and Kubernetes deployment support
- **🔐 Secure by Default**: Multiple authentication methods and security best practices

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/your-org/cost-monitor.git
cd cost-monitor

# Install dependencies
pip install -r requirements.txt

# Install the package
pip install -e .

# Note: Flask may be included in requirements.txt for optional web server functionality
```

### Basic Configuration

```bash
# Copy example configuration
cp config/config.example.yaml config/config.yaml

# Edit configuration with your cloud credentials
vim config/config.yaml
```

### Set Up Cloud Providers

#### AWS Setup

**Option 1: Automated Setup (Recommended)**
```bash
# Run the AWS credentials script - automatically sets up full permissions
./scripts/create-aws-credentials.sh

# Creates IAM user with Cost Explorer + Organizations permissions
# Enables account name resolution and all cost monitoring features
```

**Option 2: Manual Setup**
```bash
# Use AWS CLI
aws configure

# Or environment variables
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_DEFAULT_REGION="us-east-1"
```

> **💡 Tip**: Option 2 requires you to manually set up IAM permissions. Use Option 1 for automatic IAM user creation with proper permissions.

#### Azure Setup

**Step 1: Create Service Principal**
```bash
# Create service principal and save the output
az ad sp create-for-rbac --name "cost-monitor" --skip-assignment

# Note the output: you'll need appId, password, and tenant
```

**Step 2: Grant Cost Management Permissions (CRITICAL for comprehensive cost data)**
```bash
# Get the service principal Object ID
OBJECT_ID=$(az ad sp show --id "YOUR_APP_ID" --query "id" --output tsv)

# For comprehensive cost monitoring, grant access to ALL management groups
# Replace with your actual management group IDs
az role assignment create \
  --assignee "$OBJECT_ID" \
  --role "Cost Management Reader" \
  --scope "/providers/Microsoft.Management/managementGroups/your-mg-1"

az role assignment create \
  --assignee "$OBJECT_ID" \
  --role "Cost Management Reader" \
  --scope "/providers/Microsoft.Management/managementGroups/your-mg-2"

# Also grant subscription-level access for individual subscriptions
az role assignment create \
  --assignee "$OBJECT_ID" \
  --role "Cost Management Reader" \
  --scope "/subscriptions/your-subscription-id"
```

**Step 3: Grant Storage Permissions (for export data)**
```bash
# Grant Storage Blob Data Reader permissions for export data access
./scripts/setup-azure-export-permissions.sh
```

**Step 4: Configure Environment Variables**
```bash
export AZURE_SUBSCRIPTION_ID="your_subscription_id"
export AZURE_TENANT_ID="your_tenant_id"
export AZURE_CLIENT_ID="your_client_id"
export AZURE_CLIENT_SECRET="your_client_secret"
```

> **⚠️ IMPORTANT**: Without management group permissions, you'll only see costs from individual subscriptions (typically <$100/day instead of realistic $1000s/day). Management group access is **required** for comprehensive enterprise cost monitoring.

> **💡 TIP**: RBAC permissions can take 5-30 minutes to propagate for management groups. If you get "Unauthorized" errors initially, wait and retry.

#### GCP Setup
```bash
# Create service account and download key
gcloud iam service-accounts create cost-monitor --display-name "Cost Monitor"
gcloud iam service-accounts keys create key.json --iam-account cost-monitor@PROJECT_ID.iam.gserviceaccount.com

# Set environment variable
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
export GCP_PROJECT_ID="your_project_id"
```

### First Run

```bash
# Test authentication
cost-monitor test-auth

# Check current costs
cost-monitor check

# View detailed cost data
cost-monitor costs --start-date 2024-11-01 --end-date 2024-12-01

# Start the dashboard using the service management script
./service.sh start
```

Visit `http://localhost:8050` to access the interactive dashboard (or your configured port).

## 🎛️ Service Management

A convenient service management script is provided to easily control the dashboard service:

### Quick Start
```bash
# Start the dashboard service
./service.sh start

# Check service status
./service.sh status

# Stop the service
./service.sh stop

# Restart the service (useful after configuration changes)
./service.sh restart

# View recent logs
./service.sh logs

# Follow logs in real-time
./service.sh logs -f

# Clear all cached data
./service.sh clear-cache

# Clear provider-specific cache (new!)
./service.sh clear-cache aws    # Clear only AWS cache
./service.sh clear-cache gcp    # Clear only GCP cache
./service.sh clear-cache azure  # Clear only Azure cache

# Get help
./service.sh help
```

### Service Management Features
- **🚀 Easy Start/Stop/Restart** - Simple commands for service control
- **📊 Status Monitoring** - Shows running processes and dashboard URL
- **📋 Log Management** - View and follow log files
- **🧹 Cache Management** - Clear all cached data or provider-specific cache
- **🎯 Provider-Specific Operations** - Clear cache for specific providers (AWS, GCP, Azure)
- **🔧 Auto-Detection** - Automatically detects configured port and project directory
- **📁 Configuration-Aware** - Reads cache directory from your config file
- **🎨 Colored Output** - Easy-to-read status messages
- **💾 PID Tracking** - Proper process management with PID files

## 📖 Usage

### Command Line Interface

```bash
# Basic cost checking
cost-monitor check --provider aws --warning 1000 --critical 2000

# Retrieve cost data
cost-monitor costs --start-date 2024-12-01 --end-date 2024-12-05 --format json

# View active alerts
cost-monitor alerts --level critical

# Start interactive dashboard
cost-monitor dashboard --host 0.0.0.0 --port 8080

# Display configuration
cost-monitor config-info

# Reload configuration
cost-monitor reload
```

### Dashboard Features

- **Cost Trends**: Daily and monthly cost visualizations
- **Provider Comparison**: Side-by-side cost analysis
- **Service Breakdown**: Top services by cost across providers
- **Regional Distribution**: Geographic cost analysis
- **Real-time Alerts**: Live threshold monitoring
- **Interactive Controls**: Filter by date range, provider, and currency

### Grafana Integration

Integrate with Grafana using Prometheus metrics for comprehensive cost monitoring:

#### Prometheus Export for Grafana
```bash
# Export metrics to Prometheus for Grafana visualization
cost-monitor export-prometheus --output /var/lib/prometheus/cost-metrics.txt

# Push metrics to Prometheus Pushgateway for batch processing (Rundeck)
cost-monitor export-prometheus --pushgateway-url http://prometheus-pushgateway:9091

# Export specific providers with custom settings
cost-monitor export-prometheus --provider aws --days 30 --currency USD
```

#### Grafana Dashboard Setup
1. **Import Dashboard**: Use the provided `grafana-dashboard-prometheus.json` file
   - In Grafana: `+ → Import → Upload JSON file`
   - Select the `grafana-dashboard-prometheus.json` file from the project root
2. **Configure Prometheus Datasource**: Point to your Prometheus server that scrapes the cost metrics
3. **Automated Updates**: Set up Rundeck or cron jobs to regularly export metrics to Prometheus

#### Features Preserved in Grafana
- **Same Visualizations**: Cost trends, provider breakdown, service breakdown, account tables
- **Color Consistency**: AWS orange, Azure blue, GCP green color scheme maintained
- **Log Scaling**: Multi-cloud cost comparisons with logarithmic scaling
- **Interactive Filtering**: Provider selection, time range pickers, dynamic updates
- **Performance Features**: Maintains ≥$100 service filtering and cost-level badges

📖 **See [Grafana Integration Guide](docs/GRAFANA_INTEGRATION.md) for detailed setup instructions**

### Icinga/Nagios Integration

```bash
# Daily cost check
/usr/local/bin/cost-monitor-icinga daily --provider aws --warning 1000 --critical 2000

# Monthly budget check
/usr/local/bin/cost-monitor-icinga monthly --budget 30000 --provider azure

# Service-specific check
/usr/local/bin/cost-monitor-icinga service --provider gcp --service "Compute Engine" --warning 500 --critical 1000
```

## 🔧 Configuration

### Port Configuration

The dashboard port is fully configurable through the configuration file:

```yaml
dashboard:
  host: "0.0.0.0"        # Bind to all interfaces (use "127.0.0.1" for localhost only)
  port: 8050             # Default port (change to any available port)
```

**Examples:**
```yaml
# Use port 3000
dashboard:
  port: 3000

# Use port 9000 with localhost only
dashboard:
  host: "127.0.0.1"
  port: 9000
```

After changing the port, restart the service:
```bash
./service.sh restart
```

The service script automatically detects the configured port and displays the correct URL.

### Cache Configuration

The caching system is fully configurable and supports provider-specific cache management:

```yaml
cache:
  enabled: true                          # Enable/disable caching globally
  type: "disk"                          # Cache type: "disk" or "memory"
  ttl: 3600                             # Default TTL in seconds (1 hour)
  directory: "~/.cache/cost-monitor"    # Cache directory (customizable)
  max_size: "100MB"                     # Maximum cache size

  # Provider-specific TTL overrides
  aws:
    ttl: 3600      # AWS Cost Explorer updates 3-4 times daily
  azure:
    ttl: 3600      # Azure Cost Management updates hourly
  gcp:
    ttl: 3600      # GCP billing updates hourly
```

**Cache Directory Structure:**
```
~/.cache/cost-monitor/
├── aws/           # AWS-specific cache files
├── azure/         # Azure-specific cache files
└── gcp/           # GCP-specific cache files
```

**Cache Management:**
```bash
# Clear all provider cache
./service.sh clear-cache

# Clear specific provider cache
./service.sh clear-cache aws
./service.sh clear-cache gcp
./service.sh clear-cache azure

# Custom cache directory (change in config.yaml)
cache:
  directory: "/custom/cache/path"
```

### Environment-Specific Configurations

| Configuration File | Purpose | Use Case |
|-------------------|---------|----------|
| `config.example.yaml` | Example with all options | Starting template |
| `development.yaml` | Development settings | Local development |
| `production.yaml` | Production deployment | Live monitoring |
| `icinga-monitoring.yaml` | Monitoring integration | Icinga/Nagios setup |
| `docker.yaml` | Container deployment | Docker/Kubernetes |

### Key Configuration Sections

```yaml
# Cloud provider settings
clouds:
  aws:
    enabled: true
    region: "us-east-1"
    thresholds:
      warning: 1000.0
      critical: 2000.0

# Global monitoring
monitoring:
  thresholds:
    warning: 2500.0
    critical: 5000.0

# Dashboard settings
dashboard:
  enabled: true
  host: "0.0.0.0"
  port: 8050               # Configurable port (default: 8050)
  debug: false            # Enable debug mode for development
  auto_refresh: true      # Auto-refresh dashboard data
  refresh_interval: 300   # Refresh interval in seconds

# Caching configuration
cache:
  enabled: true              # Enable/disable caching
  type: "disk"              # Cache type (disk or memory)
  ttl: 3600                 # Time-to-live in seconds
  directory: "~/.cache/cost-monitor"  # Cache directory (configurable)
```

See the [Configuration Guide](config/README.md) for detailed setup instructions.

## 🏗️ Deployment

### Docker Deployment

```bash
# Build image
docker build -t cost-monitor .

# Run with environment variables
docker run -d \
  -e AWS_ACCESS_KEY_ID="your_key" \
  -e AZURE_SUBSCRIPTION_ID="your_subscription" \
  -p 8050:8050 \
  cost-monitor

# Or use Docker Compose
docker-compose up -d
```

### Kubernetes Deployment

```bash
# Create ConfigMap
kubectl create configmap cost-monitor-config --from-file=config/docker.yaml

# Create Secret
kubectl create secret generic cost-monitor-secrets \
  --from-literal=aws-access-key-id="your_key" \
  --from-literal=azure-client-secret="your_secret"

# Deploy
kubectl apply -f kubernetes/
```

### Systemd Service

```bash
# Copy service file
sudo cp scripts/cost-monitor.service /etc/systemd/system/

# Enable and start
sudo systemctl enable cost-monitor
sudo systemctl start cost-monitor
```

## 🔍 Monitoring Integration

### Icinga/Nagios Commands

```bash
# Define check commands in Icinga
define command {
    command_name    check_aws_daily_cost
    command_line    /usr/local/bin/cost-monitor-icinga daily --provider aws --warning $ARG1$ --critical $ARG2$
}

# Define services
define service {
    use                     generic-service
    host_name               monitoring-server
    service_description     AWS Daily Cost
    check_command           check_aws_daily_cost!1000!2000
    check_interval          60
    retry_interval          10
}
```

### Prometheus Metrics

```bash
# Scrape metrics endpoint
curl http://localhost:9090/metrics

# Example metrics
cost_monitor_total_cost{provider="aws",currency="USD"} 1234.56
cost_monitor_threshold_status{provider="aws",level="warning"} 0
cost_monitor_provider_requests_total{provider="azure"} 45
```

## 🔐 Security

### Best Practices

1. **Credential Management**
   - Use IAM roles when possible
   - Store secrets in environment variables or secret managers
   - Never commit credentials to version control
   - Rotate credentials regularly

2. **Network Security**
   - Restrict dashboard access to trusted networks
   - Use SSL/TLS in production
   - Configure firewall rules appropriately

3. **Configuration Security**
   - Set proper file permissions (600) for config files
   - Use encryption for sensitive configuration values
   - Audit configuration changes

### Required Permissions

#### AWS IAM Policy
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ce:GetDimensionValues"
            ],
            "Resource": "*"
        }
    ]
}
```

**Required Actions Explained:**
- `ce:GetCostAndUsage` - Core action for retrieving cost data
- `ce:GetDimensionValues` - Get available services, regions for filtering

#### Azure RBAC
- **Role**: Storage Blob Data Reader
- **Scope**: Storage Account level (for Cost Management exports)
- **Note**: Azure provider uses export data from Azure Blob Storage instead of real-time calls

#### GCP IAM
- **Role**: Billing Account Viewer
- **Additional**: BigQuery Data Viewer (for detailed billing export)

## 🐛 Troubleshooting

### Common Issues

#### Authentication Errors
```bash
# Test all providers
cost-monitor test-auth

# Check specific provider
aws sts get-caller-identity
az account show
gcloud auth list
```

#### High Cloud Provider Costs
```bash
# Enable caching
cache:
  enabled: true
  ttl: 3600

# Check cache statistics
cost-monitor config-info | grep cache
```

#### Dashboard Not Loading
```bash
# Check service status
./service.sh status

# Check if service is running and get the correct port
curl http://localhost:$(grep -E "^\s*port:" config/config.yaml | head -1 | sed 's/.*port:\s*//' | tr -d ' ')/

# Check logs using service script
./service.sh logs

# Follow logs in real-time
./service.sh logs -f

# Verify port availability (replace 8050 with your configured port)
netstat -tlnp | grep 8050

# Restart service if needed
./service.sh restart
```

#### Service Management Issues
```bash
# If service won't start
./service.sh status     # Check current status
./service.sh logs       # Check for error messages
./service.sh stop       # Force stop if needed
./service.sh start      # Start fresh

# If multiple instances are running
./service.sh stop       # Stops all instances
./service.sh start      # Starts single new instance

# If port is already in use
netstat -tlnp | grep :8050                    # Find process using port
sudo kill $(lsof -t -i:8050)                  # Kill process using port
# Or change port in config/config.yaml and restart

# Clear all cache if data seems stale
./service.sh clear-cache
./service.sh restart

# Clear specific provider cache if only one provider has issues
./service.sh clear-cache aws     # Clear just AWS cache
./service.sh clear-cache gcp     # Clear just GCP cache
./service.sh clear-cache azure   # Clear just Azure cache
./service.sh restart
```

#### Account Breakdown Issues
```bash
# If AWS accounts are sparse/limited (common issue after fixes)
./service.sh clear-cache aws    # Clear only AWS cache to get fresh data
./service.sh restart            # Restart with fresh AWS data

# If GCP projects not showing in breakdown
./service.sh clear-cache gcp    # Clear only GCP cache
./service.sh restart            # Restart with fresh GCP data

# If all providers have account issues
./service.sh clear-cache        # Clear all provider cache
./service.sh restart            # Restart with fresh data

# Check provider authentication
cost-monitor test-auth

# Verify configuration and enabled providers
cat config/config.yaml | grep -A 10 "clouds:"
grep "enabled.*true" config/config.yaml

# Check if accounts have costs in the selected date range
# Account breakdown only shows accounts with non-zero costs
```

#### Recent Bug Fixes
```bash
# If using older cached data before recent fixes:
# - AWS account breakdown parsing was fixed for LINKED_ACCOUNT grouping
# - GCP project information was fixed to always include project.id
# Clear cache to get benefits of these fixes:

./service.sh clear-cache aws    # Get fixed AWS account parsing
./service.sh clear-cache gcp    # Get fixed GCP project information
./service.sh restart
```

### Debug Mode
```bash
# Enable debug logging
cost-monitor --verbose check

# Use development configuration
cp config/development.yaml config/config.yaml
```

## 📊 Prometheus Metrics

The cost monitor exports comprehensive Prometheus metrics for monitoring and alerting:

### Exported Metrics

```prometheus
# Total costs across all providers
cloud_cost_total{currency="USD"} 19030.36

# Cost breakdown by provider
cloud_cost_provider_total{provider="aws",currency="USD"} 17832.30
cloud_cost_provider_total{provider="azure",currency="USD"} 977.11
cloud_cost_provider_total{provider="gcp",currency="USD"} 220.95

# Service-level costs with normalized service names
cloud_cost_service_total{provider="aws",service="Compute",currency="USD"} 748.95
cloud_cost_service_total{provider="azure",service="Object Storage",currency="USD"} 141.35

# Account/subscription/project breakdown
cloud_cost_account_total{provider="azure",account_id="431c23bf-...",account_name="pool-01-306",currency="USD"} 8.33

# Daily cost trends for time-series analysis
cloud_cost_daily_total{date="2025-12-08",currency="USD"} 18938.45
cloud_cost_daily_provider_total{date="2025-12-08",provider="aws",currency="USD"} 17832.30

# Operational metrics
cloud_cost_last_update_timestamp 1765311656
cloud_cost_data_range_days 1
```

### Rundeck Integration

```bash
# Recommended Rundeck job for batch processing
cost-monitor export-prometheus --pushgateway-url http://prometheus-pushgateway:9091

# Schedule: Every 15 minutes (*/15 * * * *)
# Timeout: 5 minutes
# On failure: Retry once after 2 minutes
```

## 🤝 Contributing

We welcome contributions! Please see our [Contributing Guide](CONTRIBUTING.md) for details.

### Development Setup

```bash
# Clone and install in development mode
git clone https://github.com/your-org/cost-monitor.git
cd cost-monitor
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black src/
isort src/

# Type checking
mypy src/
```

## 📝 Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and breaking changes.

## 🆘 Support

- 📖 [Documentation](docs/)
- 📊 [Grafana Integration Guide](docs/GRAFANA_INTEGRATION.md)
- 🐛 [Issue Tracker](https://github.com/your-org/cost-monitor/issues)
- 💬 [Discussions](https://github.com/your-org/cost-monitor/discussions)
- 📧 Email: support@cost-monitor.com

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- AWS Cost Explorer
- Azure Cost Management
- Google Cloud Billing
- Plotly Dashboard Framework
- Icinga Monitoring System

---

**Made with ❤️ by the Cost Monitor Team**