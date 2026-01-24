# Configuration Examples

This directory contains example configurations for different deployment scenarios of the Multi-Cloud Cost Monitor.

## Configuration Files

### 1. `config.example.yaml`
**Purpose**: General example configuration with detailed comments
**Use Case**: Starting point for custom configurations
**Features**:
- All configuration options documented
- Secure credential management examples
- Provider setup instructions
- Threshold configuration examples

### 2. `development.yaml`
**Purpose**: Development and testing environment
**Use Case**: Local development, testing, debugging
**Features**:
- Debug logging enabled
- Lower cost thresholds for testing
- Memory-based caching
- Dashboard with debug mode
- Reduced API rate limiting
- Mock data support

### 3. `production.yaml`
**Purpose**: Production environment deployment
**Use Case**: Live production monitoring
**Features**:
- Enhanced security settings
- Disk-based caching for persistence
- Email alerting configuration
- SSL/TLS support
- Audit logging
- Backup configuration
- Performance monitoring

### 4. `icinga-monitoring.yaml`
**Purpose**: Icinga/Nagios monitoring integration
**Use Case**: Integration with existing monitoring systems
**Features**:
- Optimized for Icinga check plugins
- Proper exit codes and performance data
- Service template definitions
- Minimal resource usage
- Health check endpoints

### 5. `docker.yaml`
**Purpose**: Containerized deployments
**Use Case**: Docker, Kubernetes, container orchestration
**Features**:
- Container-appropriate logging (stdout/stderr)
- Health check endpoints for orchestration
- Environment variable configuration
- Kubernetes configuration examples
- Prometheus metrics support

## Quick Start

### 1. Choose Your Configuration
```bash
# Copy the appropriate example
cp config/development.yaml config/config.yaml        # For development
cp config/production.yaml config/config.yaml         # For production
cp config/icinga-monitoring.yaml config/config.yaml  # For monitoring
cp config/docker.yaml config/config.yaml             # For containers
```

### 2. Configure Cloud Provider Credentials

#### AWS Configuration
```yaml
# Option 1: Use AWS CLI profile
clouds:
  aws:
    profile: "my-profile"

# Option 2: Environment variables
# Set: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY
clouds:
  aws:
    region: "us-east-1"

# Option 3: IAM roles (recommended for production)
# No additional configuration needed
```

#### Azure Configuration
```yaml
# Service Principal (recommended)
# Set environment variables:
# AZURE_SUBSCRIPTION_ID, AZURE_TENANT_ID
# AZURE_CLIENT_ID, AZURE_CLIENT_SECRET
clouds:
  azure:
    enabled: true
```

#### GCP Configuration
```yaml
# Service Account (recommended)
# Set: GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
# Set: GCP_PROJECT_ID=your-project-id
clouds:
  gcp:
    enabled: true
```

### 3. Configure Thresholds
```yaml
# Global thresholds
monitoring:
  thresholds:
    warning: 1500.0   # Daily warning threshold in USD
    critical: 3000.0  # Daily critical threshold in USD

# Provider-specific thresholds
clouds:
  aws:
    thresholds:
      warning: 1000.0
      critical: 2000.0
```

## Environment-Specific Setup

### Development Environment
```bash
# 1. Copy development configuration
cp config/development.yaml config/config.yaml

# 2. Set up AWS CLI profile (recommended for dev)
aws configure --profile default

# 3. Start the dashboard
python -m src.main dashboard
```

### Production Environment
```bash
# 1. Copy production configuration
cp config/production.yaml config/config.yaml

# 2. Set up environment variables (secure)
export AWS_ACCESS_KEY_ID="your-key"  # pragma: allowlist secret
export AWS_SECRET_ACCESS_KEY="your-secret"  # pragma: allowlist secret
export AZURE_SUBSCRIPTION_ID="your-subscription"
# ... other credentials

# 3. Configure email alerts
# Edit config.yaml email settings

# 4. Start monitoring
python -m src.main check
```

### Docker Deployment
```bash
# 1. Create Docker image
docker build -t cost-monitor .

# 2. Run with environment variables
docker run -d \
  -e AWS_ACCESS_KEY_ID="your-key" \  # pragma: allowlist secret
  -e AWS_SECRET_ACCESS_KEY="your-secret" \  # pragma: allowlist secret
  -e AZURE_SUBSCRIPTION_ID="your-subscription" \
  -p 8050:8050 \
  -p 8000:8000 \
  cost-monitor

# 3. Or use Docker Compose
docker-compose up -d
```

### Kubernetes Deployment
```bash
# 1. Create ConfigMap
kubectl create configmap cost-monitor-config \
  --from-file=config/docker.yaml

# 2. Create Secret
kubectl create secret generic cost-monitor-secrets \
  --from-literal=aws-access-key-id="your-key" \
  --from-literal=aws-secret-access-key="your-secret"

# 3. Deploy
kubectl apply -f kubernetes/cost-monitor.yaml
```

### Icinga Integration
```bash
# 1. Copy monitoring configuration
cp config/icinga-monitoring.yaml /etc/cost-monitor/config.yaml

# 2. Install check plugin
sudo cp scripts/cost-monitor-icinga /usr/local/bin/
sudo chmod +x /usr/local/bin/cost-monitor-icinga

# 3. Configure Icinga service definitions
# See config/icinga-monitoring.yaml for examples
```

## Configuration Validation

### Test Configuration
```bash
# Validate configuration
python -m src.main config-info

# Test authentication
python -m src.main test-auth

# Test cost retrieval
python -m src.main costs --start-date 2024-12-01 --end-date 2024-12-02
```

### Health Checks
```bash
# Check application health
curl http://localhost:8000/api/health/ready

# Check individual components
curl http://localhost:8000/api/health/ready
curl http://localhost:8000/api/health/live
```

## Security Best Practices

### 1. Credential Management
- **Never** commit credentials to version control
- Use environment variables or secret management systems
- Rotate credentials regularly
- Use IAM roles when possible (AWS, Azure, GCP)

### 2. Network Security
- Restrict dashboard access to trusted networks
- Use SSL/TLS in production
- Configure firewall rules appropriately

### 3. Configuration Security
- Store sensitive configs outside the application directory
- Use file permissions (600) for config files
- Enable encryption for sensitive values

## Troubleshooting

### Common Issues

#### Authentication Failures
```bash
# Check credentials
python -m src.main test-auth

# Verify environment variables
env | grep -E "(AWS|AZURE|GCP)"

# Check IAM permissions (AWS example)
aws sts get-caller-identity
```

#### High API Costs
```bash
# Check cache configuration
python -m src.main config-info

# Enable caching if disabled
# Edit config.yaml:
cache:
  enabled: true
  ttl: 3600
```

#### Dashboard Not Accessible
```bash
# Check if running
curl http://localhost:8050

# Check logs
tail -f /var/log/cost-monitor/cost-monitor.log

# Verify configuration
python -m src.main config-info | grep dashboard
```

## Advanced Configuration

### Custom Alert Rules
```yaml
monitoring:
  alerts:
    custom_rules:
      - name: "weekend_spike"
        condition: "weekend AND cost > 500"
        level: "warning"
      - name: "service_anomaly"
        condition: "service_cost > average * 2"
        level: "critical"
```

### Multi-Environment Setup
```yaml
# Use environment-specific configurations
environments:
  dev:
    config_file: "config/development.yaml"
  staging:
    config_file: "config/staging.yaml"
  prod:
    config_file: "config/production.yaml"
```

### Integration with External Systems
```yaml
# Webhook alerts
monitoring:
  alerts:
    webhooks:
      - url: "https://hooks.slack.com/your-webhook"
        events: ["warning", "critical"]
      - url: "https://your-pagerduty-endpoint"
        events: ["critical"]

# External metrics
performance:
  metrics:
    exporters:
      - type: "prometheus"
        endpoint: "http://prometheus:9090"
      - type: "datadog"
        api_key: "your-datadog-key"  # pragma: allowlist secret
```

## Support

For additional help:
- Check the main project documentation
- Review the troubleshooting guide
- Open an issue on GitHub
- Contact the development team

## Contributing

To contribute new configuration examples:
1. Create a new configuration file following existing patterns
2. Document the use case and features
3. Add validation and testing
4. Update this README
5. Submit a pull request