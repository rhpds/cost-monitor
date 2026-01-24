# OpenShift Deployment Guide

This guide explains how to deploy the cost monitoring application to OpenShift with proper credential management.

## Prerequisites

1. OpenShift cluster access with project admin permissions
2. Cloud provider credentials (AWS, Azure, GCP)
3. `oc` CLI configured and connected to your cluster

## 1. Create Project/Namespace

```bash
oc new-project cost-monitor
# or use existing namespace
# oc project cost-monitor
```

## 2. Set Up Secrets

### AWS Credentials
```bash
oc create secret generic aws-credentials \
  --from-literal=access-key-id="YOUR_AWS_ACCESS_KEY_ID" \
  --from-literal=secret-access-key="YOUR_AWS_SECRET_ACCESS_KEY" \
  -n cost-monitor
```

Required AWS IAM permissions:
- `ce:GetCosts`
- `ce:GetDimensions`
- `ce:GetUsageAndCosts`

### Azure Credentials
```bash
oc create secret generic azure-credentials \
  --from-literal=client-id="YOUR_AZURE_CLIENT_ID" \
  --from-literal=client-secret="YOUR_AZURE_CLIENT_SECRET" \ # pragma: allowlist secret
  --from-literal=tenant-id="YOUR_AZURE_TENANT_ID" \
  --from-literal=subscription-id="YOUR_AZURE_SUBSCRIPTION_ID" \
  --from-literal=storage-account="YOUR_STORAGE_ACCOUNT_NAME" \
  --from-literal=export-name="YOUR_EXPORT_NAME" \
  --from-literal=container="YOUR_CONTAINER_NAME" \
  -n cost-monitor
```

Required Azure permissions:
- Service principal with "Cost Management Reader" role

### GCP Credentials
```bash
# Create secret from service account JSON file
oc create secret generic gcp-credentials \
  --from-file=service-account.json=/path/to/your/gcp-service-account.json \
  -n cost-monitor
```

Required GCP permissions:
- "Billing Account Viewer" role
- "Cloud Billing API" enabled

### Database Credentials
```bash
oc create secret generic postgresql-credentials \
  --from-literal=username="cost_monitor_user" \
  --from-literal=password="$(openssl rand -base64 32)" \
  --from-literal=admin-password="$(openssl rand -base64 32)" \
  --from-literal=database="cost_monitor" \
  -n cost-monitor
```

### Redis Credentials
```bash
oc create secret generic redis-credentials \
  --from-literal=password="$(openssl rand -base64 32)" \
  -n cost-monitor
```

## 3. Deploy Application

```bash
# Deploy all components
oc apply -k openshift/base/ -n cost-monitor

# Check deployment status
oc get pods -n cost-monitor
oc get routes -n cost-monitor
```

## 4. Verify Deployment

```bash
# Check health endpoints
oc get routes -n cost-monitor
curl https://$(oc get route health-route -o jsonpath='{.spec.host}' -n cost-monitor)/health/api/health/ready

# Access dashboard
echo "Dashboard URL: https://$(oc get route dashboard-route -o jsonpath='{.spec.host}' -n cost-monitor)/"
```

## 5. Troubleshooting

### Check Pod Logs
```bash
# Data service logs
oc logs deployment/cost-data-service -n cost-monitor

# Dashboard logs
oc logs deployment/dashboard-service -n cost-monitor

# Database logs
oc logs statefulset/postgresql -n cost-monitor
```

### Common Issues

1. **Provider Registration Errors**
   - Ensure provider implementations are imported in `src/providers/__init__.py`

2. **Configuration Warnings**
   - Check environment variables use dynaconf format: `CLOUDCOST__CLOUDS__PROVIDER__SETTING`

3. **Authentication Failures**
   - Verify cloud provider credentials and permissions
   - Check secret values: `oc get secret SECRETNAME -o yaml | base64 -d`

4. **Database Connection Issues**
   - Verify PostgreSQL is running: `oc get pods | grep postgresql`
   - Check database credentials match between services

## Configuration

The application uses dynaconf for configuration management. Environment variables should use the format:
`CLOUDCOST__CLOUDS__[PROVIDER]__[SETTING]`

Examples:
- `CLOUDCOST__CLOUDS__AWS__ACCESS_KEY_ID`
- `CLOUDCOST__CLOUDS__AZURE__SUBSCRIPTION_ID`
- `CLOUDCOST__CLOUDS__GCP__PROJECT_ID`

This eliminates configuration warnings and ensures proper integration with the config system.