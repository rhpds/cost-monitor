# Monitoring & Alerting Guide

This document covers monitoring, alerting, and integration with external monitoring systems.

## Threshold Alerts

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

## Alert Types

The system supports various alert types:

- **DAILY_THRESHOLD** - Daily spending exceeds threshold
- **MONTHLY_THRESHOLD** - Monthly spending exceeds threshold
- **BUDGET_EXCEEDED** - Budget limit exceeded
- **COST_SPIKE** - Unusual spending spike detected
- **COST_TREND** - Increasing cost trend detected
- **SERVICE_ANOMALY** - Service cost anomaly detected

## Alert Levels

- **INFO** - Informational alerts
- **WARNING** - Warning threshold exceeded
- **CRITICAL** - Critical threshold exceeded

## Prometheus Integration

Export metrics for Grafana dashboards:

```bash
# Export current metrics
python -m src.main export-prometheus --output /tmp/cost_metrics.prom

# Push to Pushgateway
python -m src.main export-prometheus --pushgateway http://pushgateway:9091
```

See [GRAFANA_PROMETHEUS_SETUP.md](GRAFANA_PROMETHEUS_SETUP.md) for complete Grafana dashboard setup.

### Available Metrics

- `cloud_costs_total` - Total costs by provider and service
- `cloud_costs_daily` - Daily cost metrics
- `cloud_costs_monthly` - Monthly cost metrics
- `cost_monitor_cache_hits` - Cache hit rate metrics
- `cost_monitor_api_requests` - API request metrics

## Icinga/Nagios Integration

Monitor cost thresholds with Icinga:

```bash
# Check daily costs
python -m src.main check --provider aws --threshold 1000 --critical 2000

# Exit codes: 0=OK, 1=WARNING, 2=CRITICAL, 3=UNKNOWN
```

### Icinga Service Definition Example

```conf
define service {
    use                     generic-service
    host_name               cost-monitor
    service_description     Daily Cost Check
    check_command           check_cost_monitor!1000!2000
    check_interval          60
    retry_interval          10
    max_check_attempts      3
    notification_interval   1440
}
```

## Health Checks

The API provides health check endpoints for monitoring:

- `/api/health/ready` - Service readiness check
- `/api/health/live` - Service liveness check

These endpoints return HTTP 200 when healthy and appropriate error codes when unhealthy.

## Notification Channels

### Email Notifications

Configure SMTP settings for email alerts:

```yaml
notifications:
  email:
    enabled: true
    smtp_server: smtp.company.com
    smtp_port: 587
    use_tls: true
    username: alerts@company.com
    password: ${SMTP_PASSWORD}
    from: alerts@company.com
    to:
      - finance@company.com
      - ops@company.com
```

### Webhook Notifications

Send alerts to Slack, Teams, or custom webhooks:

```yaml
notifications:
  webhook:
    enabled: true
    url: "https://hooks.slack.com/services/YOUR_WORKSPACE_ID/YOUR_CHANNEL_ID/YOUR_WEBHOOK_TOKEN"
    headers:
      Content-Type: "application/json"
    template: |
      {
        "text": "Cost Alert: {{ alert.message }}",
        "channel": "#finance",
        "username": "Cost Monitor"
      }
```

## Logging

Configure logging for monitoring and debugging:

```yaml
logging:
  level: INFO
  handlers:
    - type: console
      level: INFO
    - type: file
      filename: /var/log/cost-monitor/app.log
      level: DEBUG
      rotation:
        max_size: 100MB
        backup_count: 10
```