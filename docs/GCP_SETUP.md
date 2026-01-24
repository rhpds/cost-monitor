# GCP Setup Guide

This guide covers setting up Google Cloud Platform (GCP) integration for the Multi-Cloud Cost Monitor.

## Overview

The Cost Monitor integrates with GCP using:
- **Service Account** for authentication
- **BigQuery Billing Export** for detailed cost data
- **Cloud Billing API** for billing account access
- **BigQuery API** for querying export data

## Prerequisites

- GCP Project with billing enabled
- Cloud Billing Admin or Billing Account User role
- gcloud CLI installed and configured (optional but recommended)

## Step 1: Enable Required APIs

Enable the necessary Google Cloud APIs in your project:

```bash
# Enable APIs using gcloud CLI
gcloud services enable cloudbilling.googleapis.com
gcloud services enable bigquery.googleapis.com

# Or enable via Cloud Console:
# https://console.cloud.google.com/apis/library
```

## Step 2: Set Up Billing Export to BigQuery

### Create BigQuery Dataset

```bash
# Create dataset for billing export
bq mk --dataset --location=US your-project-id:billing_export

# Or via Cloud Console:
# BigQuery → Create Dataset → Name: billing_export → Location: US
```

### Configure Billing Export

1. **Go to Cloud Console:**
   - Navigate to [Billing Export](https://console.cloud.google.com/billing/export)
   - Select your billing account

2. **Set up BigQuery Export:**
   - Click "Edit Settings" for BigQuery Export
   - Project: `your-project-id`
   - Dataset: `billing_export`
   - Click "Save"

3. **Verify Export Setup:**
   ```bash
   # Check if export table exists (may take 24-48 hours for first data)
   bq ls billing_export

   # Look for tables like: gcp_billing_export_v1_XXXXXX_XXXX_XXXXXX
   ```

## Step 3: Create Service Account

### Create Service Account

```bash
# Create service account
gcloud iam service-accounts create cost-monitor \
    --display-name="Cost Monitor Service Account" \
    --description="Service account for multi-cloud cost monitoring"

# Get service account email
SA_EMAIL=$(gcloud iam service-accounts list \
    --filter="displayName:Cost Monitor Service Account" \
    --format="value(email)")

echo "Service Account: $SA_EMAIL"
```

### Grant Required Permissions

#### Billing Account Permissions

```bash
# Get your billing account ID
BILLING_ACCOUNT_ID=$(gcloud billing accounts list --format="value(name)" | head -1)

# Grant Billing Account Viewer role
gcloud billing accounts add-iam-policy-binding $BILLING_ACCOUNT_ID \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/billing.viewer"

# Grant BigQuery Job User role (for running queries)
gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigquery.jobUser"

# Grant BigQuery Data Viewer role for the billing dataset
bq show --format=prettyjson billing_export | \
    jq '.access += [{"role": "READER", "userByEmail": "'$SA_EMAIL'"}]' > /tmp/dataset_access.json

bq update --source /tmp/dataset_access.json billing_export
```

#### Alternative: Project-Level Permissions

If you prefer broader project-level permissions:

```bash
# Grant broader project-level access (less secure but simpler)
gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/bigquery.dataViewer"

gcloud projects add-iam-policy-binding your-project-id \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/billing.viewer"
```

### Create and Download Service Account Key

```bash
# Create service account key
gcloud iam service-accounts keys create ~/gcp-cost-monitor-key.json \
    --iam-account=$SA_EMAIL

# Secure the key file
chmod 600 ~/gcp-cost-monitor-key.json

echo "Service account key saved to: ~/gcp-cost-monitor-key.json"
echo "Keep this file secure and never commit it to version control!"
```

## Step 4: Configure Cost Monitor

### Environment Variables

Set up environment variables for authentication:

```bash
# Set environment variable for service account key
export GOOGLE_APPLICATION_CREDENTIALS="$HOME/gcp-cost-monitor-key.json"

# Set project ID
export GCP_PROJECT_ID="your-project-id"

# Optional: Set billing account ID explicitly
export GCP_BILLING_ACCOUNT_ID="012345-ABCDEF-GHIJKL"
```

### Configuration File

Add GCP configuration to your `config/config.local.yaml`:

```yaml
clouds:
  gcp:
    enabled: true
    project_id: "your-project-id"
    credentials_path: "/path/to/gcp-cost-monitor-key.json"
    bigquery_billing_dataset: "billing_export"
    billing_account_id: "012345-ABCDEF-GHIJKL"  # Optional, auto-detected if not specified

    # Optional: Cache settings
    cache:
      ttl: 3600  # 1 hour cache

    # Optional: Threshold settings
    thresholds:
      warning: 500.0
      critical: 1000.0
```

## Step 5: Test Setup

### Test Authentication

```bash
# Test GCP authentication
python -m src.main test-auth --provider gcp

# Should show:
# ✓ GCP authentication successful
```

### Test Cost Data Retrieval

```bash
# Get GCP costs for last 7 days
python -m src.main costs --provider gcp --days 7

# Get detailed cost breakdown
python -m src.main costs --provider gcp --days 30 --format json
```

### Verify BigQuery Access

```bash
# Test BigQuery access directly
gcloud auth activate-service-account --key-file ~/gcp-cost-monitor-key.json

# List billing export tables
bq ls billing_export

# Query recent billing data (if export data exists)
bq query --use_legacy_sql=false \
    "SELECT service.description, SUM(cost) as total_cost
     FROM \`your-project-id.billing_export.gcp_billing_export_v1_*\`
     WHERE _PARTITIONTIME >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY)
     GROUP BY service.description
     ORDER BY total_cost DESC
     LIMIT 10"
```

## Common Setup Issues

### No Billing Data Available

**Problem:** Error message "No billing data found"

**Solutions:**
1. **Wait for export data:** Initial billing export can take 24-48 hours
2. **Check export configuration:** Verify BigQuery export is enabled in Cloud Console
3. **Verify permissions:** Ensure service account has BigQuery Data Viewer access
4. **Check dataset location:** Ensure dataset is in US region (required for billing export)

### Authentication Errors

**Problem:** "DefaultCredentialsError" or "Permission denied"

**Solutions:**
1. **Check credentials path:**
   ```bash
   echo $GOOGLE_APPLICATION_CREDENTIALS
   ls -la $GOOGLE_APPLICATION_CREDENTIALS
   ```

2. **Verify service account permissions:**
   ```bash
   # Check billing account access
   gcloud billing accounts get-iam-policy $BILLING_ACCOUNT_ID

   # Check BigQuery permissions
   bq show billing_export
   ```

3. **Test authentication:**
   ```bash
   gcloud auth activate-service-account --key-file $GOOGLE_APPLICATION_CREDENTIALS
   gcloud auth list
   ```

### BigQuery Permission Issues

**Problem:** "Access denied" when querying billing data

**Solutions:**
1. **Check dataset permissions:**
   ```bash
   bq show --format=prettyjson billing_export | jq '.access'
   ```

2. **Re-grant permissions:**
   ```bash
   # Grant dataset-level access
   bq show --format=prettyjson billing_export | \
       jq '.access += [{"role": "READER", "userByEmail": "'$SA_EMAIL'"}]' > /tmp/access.json
   bq update --source /tmp/access.json billing_export
   ```

### Project or Billing Account Not Found

**Problem:** "Project not found" or "Billing account not found"

**Solutions:**
1. **Verify project ID:**
   ```bash
   gcloud projects list
   ```

2. **Check billing account ID:**
   ```bash
   gcloud billing accounts list
   ```

3. **Ensure service account has access:**
   ```bash
   # Check project-level permissions
   gcloud projects get-iam-policy your-project-id
   ```

## Security Best Practices

### Service Account Security

1. **Principle of Least Privilege:**
   - Only grant necessary roles (Billing Viewer, BigQuery Data Viewer)
   - Use dataset-level permissions instead of project-wide when possible

2. **Key Management:**
   - Store service account keys securely
   - Never commit keys to version control
   - Rotate keys regularly (every 90 days recommended)
   - Use environment variables, not hardcoded paths

3. **Monitoring:**
   - Enable audit logging for service account usage
   - Monitor for unexpected API calls
   - Set up alerts for failed authentication attempts

### Production Deployment

1. **Use Workload Identity (GKE):**
   ```yaml
   # For Kubernetes/OpenShift deployments
   apiVersion: v1
   kind: ServiceAccount
   metadata:
     annotations:
       iam.gke.io/gcp-service-account: cost-monitor@project.iam.gserviceaccount.com
   ```

2. **Use Secret Manager:**
   ```bash
   # Store credentials in Secret Manager instead of files
   gcloud secrets create cost-monitor-credentials --data-file=key.json
   ```

## Advanced Configuration

### Multiple Projects

For organizations with multiple GCP projects:

```yaml
clouds:
  gcp:
    enabled: true
    projects:
      - project_id: "project-1"
        credentials_path: "/path/to/project1-key.json"
        bigquery_billing_dataset: "billing_export"
      - project_id: "project-2"
        credentials_path: "/path/to/project2-key.json"
        bigquery_billing_dataset: "billing_data"
```

### Custom BigQuery Queries

For advanced cost analysis, you can customize BigQuery queries:

```yaml
clouds:
  gcp:
    bigquery:
      custom_queries:
        daily_costs: |
          SELECT
            FORMAT_DATE('%Y-%m-%d', DATE(usage_start_time)) as date,
            service.description as service,
            SUM(cost) as cost
          FROM `{project_id}.{dataset}.gcp_billing_export_v1_*`
          WHERE DATE(usage_start_time) BETWEEN @start_date AND @end_date
          GROUP BY date, service
          ORDER BY date, cost DESC
```

## Integration with Other Tools

### Terraform Setup

```hcl
# Create service account with Terraform
resource "google_service_account" "cost_monitor" {
  account_id   = "cost-monitor"
  display_name = "Cost Monitor Service Account"
  description  = "Service account for multi-cloud cost monitoring"
}

# Grant required roles
resource "google_project_iam_member" "billing_viewer" {
  project = var.project_id
  role    = "roles/billing.viewer"
  member  = "serviceAccount:${google_service_account.cost_monitor.email}"
}

resource "google_project_iam_member" "bigquery_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.cost_monitor.email}"
}

# Create and download key
resource "google_service_account_key" "cost_monitor_key" {
  service_account_id = google_service_account.cost_monitor.name
}
```

### Monitoring Integration

Configure Stackdriver/Cloud Monitoring alerts:

```bash
# Create alert policy for high costs
gcloud alpha monitoring policies create \
    --policy-from-file=gcp-cost-alert-policy.yaml
```

## Troubleshooting Commands

Useful commands for debugging GCP setup:

```bash
# Check current authentication
gcloud auth list
gcloud config list

# Test service account authentication
gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS

# List available billing accounts
gcloud billing accounts list

# Check BigQuery access
bq ls
bq ls billing_export

# Test cost monitor authentication
python -m src.main test-auth --provider gcp --verbose

# Check recent billing data
bq query --dry_run \
    "SELECT COUNT(*) FROM \`$GCP_PROJECT_ID.billing_export.gcp_billing_export_v1_*\`"
```

## Support

For additional help:
- [GCP Billing Documentation](https://cloud.google.com/billing/docs)
- [BigQuery Export Guide](https://cloud.google.com/billing/docs/how-to/export-data-bigquery)
- [Service Account Best Practices](https://cloud.google.com/iam/docs/best-practices-for-service-accounts)
- [Cost Monitor Troubleshooting](TROUBLESHOOTING.md)