# Configuration Guide

This document provides detailed configuration options for the Multi-Cloud Cost Monitor.

## Cloud Provider Setup

### AWS Configuration

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

See [AWS_PERMISSIONS.md](AWS_PERMISSIONS.md) for detailed IAM setup instructions.

### Azure Configuration

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

See [AZURE_SETUP.md](AZURE_SETUP.md) for detailed Azure service principal setup.

### GCP Configuration

```yaml
clouds:
  gcp:
    enabled: true
    project_id: your-billing-project
    credentials_path: /path/to/service-account.json
    bigquery_billing_dataset: billing_export
    billing_account_id: 012345-ABCDEF-GHIJKL
```

## Caching Configuration

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

## Dashboard Settings

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

## Database Configuration

```yaml
database:
  url: "postgresql://username:password@localhost:5432/cost_monitor"
  pool_size: 20
  max_overflow: 30
```

## Logging Configuration

```yaml
logging:
  level: INFO  # DEBUG, INFO, WARNING, ERROR, CRITICAL
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  handlers:
    - type: console
    - type: file
      filename: /var/log/cost-monitor/app.log
```

## Environment Variables

The following environment variables can override configuration settings:

- `AWS_ACCESS_KEY_ID` - AWS access key
- `AWS_SECRET_ACCESS_KEY` - AWS secret key
- `AZURE_TENANT_ID` - Azure tenant ID
- `AZURE_CLIENT_ID` - Azure client ID
- `AZURE_CLIENT_SECRET` - Azure client secret
- `GOOGLE_APPLICATION_CREDENTIALS` - Path to GCP service account JSON
- `DATABASE_URL` - PostgreSQL connection string
- `REDIS_URL` - Redis connection string
- `CACHE_TTL` - Default cache TTL in seconds