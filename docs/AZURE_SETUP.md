# Azure Cost Management Export Setup Guide

## Overview
This guide covers the manual Azure configuration required before deploying the cost monitoring provider.

## Prerequisites
- Azure subscription with Cost Management access
- Permissions to create service principals
- Access to create storage accounts and exports

## 1. Create Service Principal

```bash
# Create service principal
az ad sp create-for-rbac --name "cost-monitor-sp" --role "Cost Management Reader"

# Note the output:
# {
#   "appId": "CLIENT_ID",
#   "password": "CLIENT_SECRET",
#   "tenant": "TENANT_ID"
# }
```

## 2. Create Storage Account (if not using existing)

```bash
# Create resource group
az group create --name "cost-monitoring-rg" --location "eastus"

# Create storage account
az storage account create \
  --name "demobillingexports" \
  --resource-group "cost-monitoring-rg" \
  --location "eastus" \
  --sku "Standard_LRS"

# Create container
az storage container create \
  --name "demo-billing-exports-actual" \
  --account-name "demobillingexports"
```

## 3. Grant Storage Permissions

```bash
# Get service principal object ID
SP_ID=$(az ad sp show --id "CLIENT_ID" --query "objectId" -o tsv)

# Grant Storage Blob Data Reader role
az role assignment create \
  --assignee $SP_ID \
  --role "Storage Blob Data Reader" \
  --scope "/subscriptions/SUBSCRIPTION_ID/resourceGroups/cost-monitoring-rg/providers/Microsoft.Storage/storageAccounts/demobillingexports"
```

## 4. Configure Cost Management Export

### Via Azure Portal:
1. Navigate to **Cost Management + Billing**
2. Select your subscription or billing account
3. Go to **Cost Management** → **Exports**
4. Click **+ Add**
5. Configure export:
   - **Name**: `demo-billing-exports-actual`
   - **Export type**: `Actual costs (Usage and Purchases)`
   - **Scope**: Your subscription/billing account
   - **Recurrence**: `Monthly export of month-to-date costs`
   - **Storage**: Select your storage account and container
   - **Directory path**: `billingexportsactual/demo-billing-exports-actual/`

### Via Azure CLI:
```bash
# Create export (adjust scope and storage details)
az costmanagement export create \
  --name "demo-billing-exports-actual" \
  --scope "/subscriptions/SUBSCRIPTION_ID" \
  --storage-account-id "/subscriptions/SUBSCRIPTION_ID/resourceGroups/cost-monitoring-rg/providers/Microsoft.Storage/storageAccounts/demobillingexports" \
  --storage-container "demo-billing-exports-actual" \
  --storage-directory "billingexportsactual/demo-billing-exports-actual" \
  --type "ActualCost" \
  --recurrence-type "Monthly" \
  --format "Csv"
```

## 5. Verify Export Configuration

The export will create files in this structure:
```
billingexportsactual/
└── demo-billing-exports-actual/
    └── YYYYMMDD-YYYYMMDD/  # Date range
        └── {GUID}/         # Export run ID
            ├── part_1_0001.csv     # Main data file
            └── manifest.json       # Export metadata
```

## 6. Update Configuration

Edit your `config/config.yaml`:

```yaml
azure:
  enabled: true
  tenant_id: "${AZURE_TENANT_ID}"
  client_id: "${AZURE_CLIENT_ID}"
  client_secret: "${AZURE_CLIENT_SECRET}"
  export:
    storage_account: "demobillingexports"
    container: "demo-billing-exports-actual"
    export_name: "demo-billing-exports-actual"
```

## 7. Environment Variables

Set these in your deployment:

```bash
export CLOUDCOST__CLOUDS__AZURE__TENANT_ID="your_tenant_id"
export CLOUDCOST__CLOUDS__AZURE__CLIENT_ID="your_client_id"
export CLOUDCOST__CLOUDS__AZURE__CLIENT_SECRET="your_client_secret"
```

## Troubleshooting

### Export Not Found
- Verify export is created and has run at least once
- Check export scope matches your billing account
- Ensure export recurrence is set to Monthly

### Authentication Errors
- Verify service principal credentials are correct
- Check Cost Management Reader role is assigned
- Ensure Storage Blob Data Reader role on storage account

### No Data Returned
- Wait for export to run (monthly schedule)
- Check export contains data for requested date range
- Verify CSV files exist in expected directory structure