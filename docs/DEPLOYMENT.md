# Cost Monitor Deployment Guide

This guide walks you through deploying the Cost Monitor application to OpenShift with the enhanced deployment system.

## Prerequisites

- OpenShift CLI (`oc`) installed and logged into your cluster
- `yq` tool installed for YAML processing
- Access to your cloud provider credentials (AWS, Azure, GCP)

## Quick Start

### 1. Setup Local Configuration

Copy the template and customize for your environment:

```bash
cp openshift/local-config.template.yaml openshift/local/local-config.yaml
```

Edit `openshift/local/local-config.yaml` with your actual values:

```yaml
deployment:
  namespace: "cost-monitor"
  cluster_domain: "apps.your-cluster.example.com"  # Your actual cluster domain
  image_registry: "your-registry-url"              # Your OpenShift image registry

git:
  repository: "https://github.com/your-org/cost-monitor.git"  # Your actual repo
  branch: "main"

secrets:
  postgresql:
    username: "cost_monitor_user"
    password: "your-secure-password"  # pragma: allowlist secret
    # ... fill in all other credentials
```

### 2. Deploy the Application

Run the enhanced deployment script:

```bash
# Test deployment (dry run)
./deploy.sh local true

# Actual deployment
./deploy.sh local false
```

The script will:

1. ✅ Validate prerequisites (`oc`, `yq`, local config)
2. 🔧 Generate local overlay from templates
3. 📁 Create namespace if needed
4. 🔐 Create secrets from your local configuration
5. 🔨 Update buildconfigs with your repository URL
6. 🎯 Deploy all resources using Kustomize
7. ⏳ Wait for all services to be ready
8. 🌐 Display access URLs

### 3. Access the Application

After successful deployment:

- **Dashboard**: `https://cost-monitor.your-domain.com`
- **API**: `https://cost-api.your-domain.com/api`
- **Health**: `https://cost-health.your-domain.com/health`

## Security Features

- ✅ **Local config is git-ignored**: Your credentials never get committed
- ✅ **Template-based overlays**: Generic templates in git, customized locally
- ✅ **Automated secret creation**: Secrets generated from your local config
- ✅ **Environment isolation**: Each environment has its own overlay

## File Structure

```
openshift/
├── base/                          # Base Kubernetes manifests (generic)
├── overlays/
│   └── local-template/           # Template for local development (committed)
├── local/                        # Local environment (git-ignored)
│   ├── local-config.yaml        # Your local configuration (git-ignored)
│   ├── kustomization.yaml       # Generated from template (git-ignored)
│   └── routes-patch.yaml        # Generated from template (git-ignored)
└── local-config.template.yaml    # Template for local config (committed)
```

## Troubleshooting

### Missing Dependencies

Install yq if not available:
```bash
sudo wget -qO /usr/local/bin/yq https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64
sudo chmod +x /usr/local/bin/yq
```

### Check Deployment Status

```bash
oc get pods -n cost-monitor
oc logs -f deployment/cost-data-service -n cost-monitor
oc logs -f dc/cost-monitor-dashboard -n cost-monitor
```