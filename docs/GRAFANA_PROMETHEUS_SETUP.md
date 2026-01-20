# Grafana + Prometheus Integration Guide

This guide explains how to set up cost monitoring with Grafana and Prometheus using the simplified batch export approach.

## Overview

The cost monitor now exports metrics in Prometheus format that can be:
1. **Pushed to Prometheus Pushgateway** (recommended for Rundeck batch jobs)
2. **Saved to files** for direct Prometheus scraping
3. **Visualized in Grafana** using the pre-built dashboard template

## Quick Setup

### 1. Export Metrics to Prometheus

```bash
# Option 1: Push to Pushgateway (recommended for batch processing)
cost-monitor export-prometheus --pushgateway-url http://prometheus-pushgateway:9091

# Option 2: Save to file for scraping
cost-monitor export-prometheus --output /var/lib/prometheus/cost-metrics.prom

# Option 3: Print to stdout for debugging
cost-monitor export-prometheus
```

### 2. Set Up Rundeck Batch Job

**Job Configuration:**
- **Command**: `cost-monitor export-prometheus --pushgateway-url http://your-pushgateway:9091`
- **Schedule**: `*/15 * * * *` (every 15 minutes)
- **Timeout**: 5 minutes
- **Retry**: Once after 2 minutes

**Example Rundeck Job Definition:**
```xml
<joblist>
  <job>
    <name>Cost Monitor Prometheus Export</name>
    <group>monitoring</group>
    <description>Export multi-cloud cost metrics to Prometheus</description>
    <executionEnabled>true</executionEnabled>
    <scheduleEnabled>true</scheduleEnabled>
    <schedule>
      <time hour='*' minute='*/15' seconds='0'/>
    </schedule>
    <sequence>
      <command>
        <exec>cost-monitor export-prometheus --pushgateway-url http://prometheus-pushgateway:9091</exec>
      </command>
    </sequence>
    <timeout>PT5M</timeout>
    <retry>1</retry>
    <retryDelay>PT2M</retryDelay>
  </job>
</joblist>
```

### 3. Configure Prometheus

**prometheus.yml:**
```yaml
global:
  scrape_interval: 1m

scrape_configs:
  # Scrape from Pushgateway
  - job_name: 'pushgateway'
    static_configs:
      - targets: ['pushgateway:9091']
    scrape_interval: 1m
    honor_labels: true

  # OR scrape from file (if using file export)
  - job_name: 'cost-monitor-file'
    file_sd_configs:
      - files:
        - '/var/lib/prometheus/cost-metrics.prom'
    scrape_interval: 1m
```

### 4. Import Grafana Dashboard

1. **Download the template**: Copy `grafana-dashboard-prometheus.json` from the project root
2. **Import into Grafana**:
   - Go to Grafana UI
   - Click `+` → `Import`
   - Upload the JSON file
   - Configure the Prometheus datasource
3. **Configure datasource**: Point to your Prometheus server that scrapes the cost metrics

## Dashboard Features

The Grafana dashboard includes:

- **📊 Total Cost Overview** with threshold-based color coding
- **🥧 Provider Breakdown** (AWS, Azure, GCP pie chart)
- **📈 Cost Trends** (30-day time series)
- **🏆 Top Services** (bar chart of highest costs)
- **🌍 Regional Distribution**
- **📋 Account/Subscription Table** with sorting
- **📊 Cost Growth Rate** monitoring
- **⏰ Data Freshness** indicators
- **📊 Week-over-week Comparisons**

## Exported Metrics

```prometheus
# Total cost across all providers
cloud_cost_total{currency="USD"} 19030.36

# Per-provider costs
cloud_cost_provider_total{provider="aws",currency="USD"} 17832.30
cloud_cost_provider_total{provider="azure",currency="USD"} 977.11
cloud_cost_provider_total{provider="gcp",currency="USD"} 220.95

# Service breakdown (normalized across providers)
cloud_cost_service_total{provider="aws",service="Compute",currency="USD"} 748.95
cloud_cost_service_total{provider="azure",service="Object Storage",currency="USD"} 141.35

# Account/subscription breakdown
cloud_cost_account_total{provider="azure",account_id="...",account_name="pool-01-306",currency="USD"} 8.33

# Daily cost trends
cloud_cost_daily_total{date="2025-12-08",currency="USD"} 18938.45
cloud_cost_daily_provider_total{date="2025-12-08",provider="aws",currency="USD"} 17832.30

# Operational metrics
cloud_cost_last_update_timestamp 1765311656
cloud_cost_data_range_days 1
```

## Alerting Examples

### Prometheus Alert Rules

```yaml
groups:
  - name: cost_monitoring
    rules:
      # High total cost
      - alert: HighCloudCosts
        expr: cloud_cost_total > 20000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Cloud costs exceed $20,000"
          description: "Total cloud costs: ${{ $value }}"

      # Provider cost spike
      - alert: ProviderCostSpike
        expr: increase(cloud_cost_provider_total[1h]) > 100
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "{{ $labels.provider }} cost spike detected"
          description: "{{ $labels.provider }} costs increased by ${{ $value }} in the last hour"

      # Stale data
      - alert: StaleGloudCostData
        expr: (time() - cloud_cost_last_update_timestamp) > 3600
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Cloud cost data is stale"
          description: "Cost data hasn't been updated in {{ $value }} seconds"
```

## Troubleshooting

### Common Issues

1. **No data in Grafana**:
   - Check Prometheus targets are up
   - Verify pushgateway is receiving data: `curl http://pushgateway:9091/metrics`
   - Check cost-monitor export logs

2. **Rundeck job failures**:
   - Check cloud provider credentials
   - Verify pushgateway URL is accessible
   - Check job timeout settings

3. **Missing metrics**:
   - Verify cloud providers are configured and enabled
   - Check authentication: `cost-monitor test-auth`
   - Review export command parameters

### Validation Commands

```bash
# Test cloud authentication
cost-monitor test-auth

# Test metric export
cost-monitor export-prometheus --days 1

# Check pushgateway
curl http://pushgateway:9091/metrics | grep cloud_cost

# Validate Prometheus ingestion
curl http://prometheus:9090/api/v1/query?query=cloud_cost_total
```

## Migration from API-based Setup

If you were previously using the API server approach:

1. **Stop the API server** (no longer needed)
2. **Remove API datasources** from Grafana
3. **Set up Prometheus** to scrape metrics instead
4. **Import the new dashboard** template
5. **Configure Rundeck** for batch metric exports

The new approach is simpler, more reliable, and better suited for production environments.