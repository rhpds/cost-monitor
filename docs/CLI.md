# CLI Usage Guide

The Cost Monitor provides a comprehensive command-line interface for managing and monitoring cloud costs.

## Installation

The CLI is included with the main application:

```bash
# For local development
pip install -r requirements.txt

# Or use in container
docker run -it cost-monitor python -m src.main --help
```

## Available Commands

### Dashboard

Start the interactive web dashboard:

```bash
# Start dashboard on default port (8050)
python -m src.main dashboard

# Start on custom host/port
python -m src.main dashboard --host 0.0.0.0 --port 8080

# Enable debug mode
python -m src.main dashboard --debug
```

**Options:**
- `--host` - Host to bind to (default: 127.0.0.1)
- `--port` - Port to bind to (default: 8050)
- `--debug` - Enable debug mode
- `--no-auto-refresh` - Disable automatic data refresh

### API Service

Start the FastAPI backend service:

```bash
# Start API service
python -m src.main api

# Start with custom configuration
python -m src.main api --config /path/to/config.yaml
```

**Options:**
- `--host` - Host to bind to (default: 127.0.0.1)
- `--port` - Port to bind to (default: 8000)
- `--config` - Configuration file path

### Cost Data Retrieval

Get cost data from command line:

```bash
# Get costs for all providers (last 30 days)
python -m src.main costs

# Get AWS costs for last 7 days
python -m src.main costs --provider aws --days 7

# Get costs for specific date range
python -m src.main costs --start-date 2025-01-01 --end-date 2025-01-24

# Get monthly aggregated costs
python -m src.main costs --granularity monthly
```

**Options:**
- `--provider` - Cloud provider (aws/azure/gcp)
- `--days` - Number of days from today (default: 30)
- `--start-date` - Start date (YYYY-MM-DD)
- `--end-date` - End date (YYYY-MM-DD)
- `--granularity` - Data granularity (daily/monthly)
- `--format` - Output format (table/json/csv)
- `--force-refresh` - Bypass cache

**Output Formats:**

```bash
# Table format (default)
python -m src.main costs --format table

# JSON output
python -m src.main costs --format json

# CSV export
python -m src.main costs --format csv > costs.csv
```

### Threshold Monitoring

Check cost thresholds for monitoring systems:

```bash
# Check daily costs against threshold
python -m src.main check --threshold 1000

# Check with warning and critical thresholds
python -m src.main check --threshold 1000 --critical 2000

# Check specific provider
python -m src.main check --provider aws --threshold 500

# Check monthly threshold
python -m src.main check --granularity monthly --threshold 25000
```

**Options:**
- `--provider` - Cloud provider to check (aws/azure/gcp)
- `--threshold` - Warning threshold amount
- `--critical` - Critical threshold amount
- `--granularity` - Check period (daily/monthly)

**Exit Codes:**
- `0` - OK (below threshold)
- `1` - WARNING (above warning threshold)
- `2` - CRITICAL (above critical threshold)
- `3` - UNKNOWN (error occurred)

### Authentication Testing

Test cloud provider authentication:

```bash
# Test all configured providers
python -m src.main test-auth

# Test specific provider
python -m src.main test-auth --provider aws

# Verbose output
python -m src.main test-auth --verbose
```

**Options:**
- `--provider` - Test specific provider (aws/azure/gcp)
- `--verbose` - Show detailed authentication information

### Prometheus Metrics Export

Export metrics for Prometheus/Grafana:

```bash
# Export to file
python -m src.main export-prometheus --output /tmp/cost_metrics.prom

# Push to Pushgateway
python -m src.main export-prometheus --pushgateway http://pushgateway:9091

# Export with custom job name
python -m src.main export-prometheus --pushgateway http://pushgateway:9091 --job cost-monitor
```

**Options:**
- `--output` - Output file path
- `--pushgateway` - Pushgateway URL for pushing metrics
- `--job` - Job name for Pushgateway (default: cost_monitor)

### Alert Management

View and manage active alerts:

```bash
# List all active alerts
python -m src.main alerts

# Show alerts for specific provider
python -m src.main alerts --provider aws

# Show only critical alerts
python -m src.main alerts --level critical
```

**Options:**
- `--provider` - Filter by provider (aws/azure/gcp)
- `--level` - Filter by alert level (info/warning/critical)

## Global Options

All commands support these global options:

- `--config` - Configuration file path (default: config/config.yaml)
- `--verbose` - Enable verbose logging
- `--quiet` - Suppress non-error output
- `--log-level` - Set log level (DEBUG/INFO/WARNING/ERROR)

## Configuration

The CLI uses the same configuration as the main application. Configuration precedence:

1. Command-line arguments
2. Environment variables
3. Configuration file
4. Default values

### Environment Variables

Override configuration with environment variables:

```bash
export AWS_ACCESS_KEY_ID=your-key-id
export AWS_SECRET_ACCESS_KEY=your-secret-key
export DATABASE_URL=postgresql://user:pass@host:5432/db
export REDIS_URL=redis://localhost:6379

python -m src.main costs
```

### Configuration File

Specify custom configuration file:

```bash
python -m src.main costs --config /path/to/custom-config.yaml
```

## Examples

### Daily Cost Monitoring Script

```bash
#!/bin/bash
# daily-cost-check.sh

# Check if daily costs exceed $1000
python -m src.main check --threshold 1000 --critical 2000

case $? in
    0)
        echo "Daily costs are within normal range"
        ;;
    1)
        echo "WARNING: Daily costs exceed $1000"
        # Send warning notification
        ;;
    2)
        echo "CRITICAL: Daily costs exceed $2000"
        # Send critical alert
        ;;
    3)
        echo "UNKNOWN: Error checking costs"
        ;;
esac
```

### Weekly Cost Report

```bash
#!/bin/bash
# weekly-report.sh

# Generate weekly cost report
python -m src.main costs \
    --days 7 \
    --format csv \
    --granularity daily > "weekly-costs-$(date +%Y%m%d).csv"

echo "Weekly cost report generated"
```

### Provider Authentication Check

```bash
#!/bin/bash
# check-auth.sh

providers=("aws" "azure" "gcp")

for provider in "${providers[@]}"; do
    echo "Checking $provider authentication..."
    if python -m src.main test-auth --provider $provider --quiet; then
        echo "✓ $provider authentication successful"
    else
        echo "✗ $provider authentication failed"
    fi
done
```

### Automated Metrics Export

```bash
#!/bin/bash
# export-metrics.sh

# Export metrics to Prometheus pushgateway every 5 minutes
while true; do
    python -m src.main export-prometheus \
        --pushgateway http://pushgateway:9091 \
        --job cost-monitor-cron

    if [ $? -eq 0 ]; then
        echo "$(date): Metrics exported successfully"
    else
        echo "$(date): Failed to export metrics"
    fi

    sleep 300  # 5 minutes
done
```

## Integration with Monitoring Systems

### Icinga/Nagios Check Command

```bash
# /usr/local/bin/check_cost_monitor
#!/bin/bash

python -m src.main check \
    --provider "$1" \
    --threshold "$2" \
    --critical "$3"
```

### Systemd Service for Continuous Monitoring

```ini
# /etc/systemd/system/cost-monitor-check.service
[Unit]
Description=Cost Monitor Threshold Check
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/check_cost_monitor aws 1000 2000
User=cost-monitor
StandardOutput=journal

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/cost-monitor-check.timer
[Unit]
Description=Run cost monitor check hourly

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

## Troubleshooting

### Common Issues

**Command not found:**
```bash
# Ensure you're in the correct directory
cd /path/to/cost-monitor

# Use full module path
python -m src.main --help
```

**Configuration errors:**
```bash
# Test configuration
python -m src.main test-auth --verbose

# Check configuration file
python -m src.main --config config/config.yaml costs --dry-run
```

**Permission errors:**
```bash
# Check file permissions
ls -la config/config.yaml

# Ensure proper environment variables
env | grep -E "(AWS|AZURE|GOOGLE)"
```

For more troubleshooting information, see [TROUBLESHOOTING.md](TROUBLESHOOTING.md).