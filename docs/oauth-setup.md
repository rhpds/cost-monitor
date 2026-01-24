# OAuth SSO Integration Setup Guide

This guide walks you through setting up OAuth SSO integration for the Cost Monitor application using OpenShift's native OAuth proxy.

## Overview

The OAuth integration provides:

- **Dashboard Access**: Protected by OpenShift native OAuth proxy (external access point)
- **Data Service**: Internal only, accessed by dashboard (no external routes)
- **Health Checks**: Direct access for monitoring tools (IP restricted)
- **Automatic TLS**: Let's Encrypt certificates via OpenShift router edge termination

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                External Access (HTTPS)                 │
│              OpenShift Router + TLS                    │
└─────────────────────┬───────────────────────────────────┘
                      │ Edge Termination
┌─────────────────────▼───────────────────────────────────┐
│          OpenShift OAuth Proxy (Native)                │
│    registry.redhat.io/openshift4/ose-oauth-proxy       │
└─────────────────────┬───────────────────────────────────┘
                      │ Internal HTTP
┌─────────────────────▼───────────────────────────────────┐
│                  Dashboard                              │
│               (Dash/Plotly)                            │
└─────────────────────┬───────────────────────────────────┘
                      │ Internal HTTP
┌─────────────────────▼───────────────────────────────────┐
│                Data Service                             │
│               (FastAPI - Internal Only)                │
└─────────────────────┬───────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────┐
│          PostgreSQL + Redis                            │
└─────────────────────────────────────────────────────────┘
```

## Prerequisites

1. OpenShift cluster with OAuth enabled
2. Access to Red Hat container registry (oauth-proxy image)
3. Cost monitor application already deployed

## Deployment Steps

OAuth integration is **automatically configured** when you run `deploy.sh` with OAuth enabled. The deployment script handles all cluster-specific configuration.

### Automatic Deployment (Recommended)

1. **Enable OAuth in configuration:**
```bash
# Edit config/local-config.yaml
oauth:
  enabled: true
```

2. **Run automated deployment:**
```bash
./deploy.sh
```

The script automatically:
- Generates OAuth secrets (session secret)
- Creates cluster-specific patches for routes and OAuth client
- Configures redirect URIs for your cluster domain
- Applies all OAuth resources with proper dependencies

3. **Access the application:**
```bash
# Get the dashboard URL
oc get route dashboard-route -o jsonpath='{.spec.host}'
echo ""

# Visit the URL - you'll be redirected to OpenShift SSO
```

### Manual Configuration (Advanced)

For custom deployments or troubleshooting, you can configure OAuth manually:

#### Step 1: Configure OAuth Resources

The OAuth proxy uses OpenShift's native integration with these key configurations:

**OAuth Proxy (args-based configuration):**
```yaml
# openshift/base/auth/oauth-proxy.yaml
args:
- -provider=openshift
- -http-address=:8080  # Internal HTTP only
- -https-address=
- -email-domain=*
- -upstream=http://dashboard-service:8050/
- -client-id=cost-monitor-oauth-client
- -client-secret-file=/etc/proxy/secrets/client-secret
- -cookie-secret-file=/etc/proxy/secrets/session_secret
- -openshift-service-account=cost-monitor-oauth
- -openshift-ca=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
- -skip-auth-regex=^/health
```

**OAuth Client:**
```yaml
# openshift/base/auth/oauth-rbac.yaml
redirectURIs:
- "https://cost-monitor.apps.cluster.local/oauth/callback"  # Note: /oauth/ not /oauth2/
```

#### Step 2: Generate Secrets

```bash
# Generate session secret (32 characters for OpenShift oauth-proxy)
session_secret=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c32)

# Create OAuth proxy secret
oc create secret generic oauth-proxy-secret \
    --from-literal=client-id="cost-monitor-oauth-client" \
    --from-literal=client-secret="" \
    --from-literal=session_secret="$session_secret"
```

#### Step 3: Apply Resources

```bash
# Deploy OAuth components
oc apply -k openshift/base/auth/

# Wait for OAuth client to be created and get the client secret
CLIENT_SECRET=$(oc get oauthclient cost-monitor-oauth-client -o jsonpath='{.secret}')

# Update the OAuth secret with the generated client secret
oc patch secret oauth-proxy-secret -p "{\"stringData\":{\"client-secret\":\"$CLIENT_SECRET\"}}"

# Restart OAuth proxy to pick up the secret
oc rollout restart deployment/oauth-proxy
```

## User Role Configuration

### Default Access

By default, all authenticated users get `viewer` access with `costs:read` permission.

### Custom Role Mapping

Edit the user roles in `openshift/base/auth/oauth-secrets.yaml`:

```yaml
data:
  users.yaml: |
    users:
      # Map specific users to roles
      john.doe@company.com:
        - admin
      jane.smith@company.com:
        - analyst

      # Service accounts
      prometheus:
        - service

  groups.yaml: |
    groups:
      # Map OpenShift/LDAP groups to roles
      cost-monitor-admins:
        - admin
      finance-team:
        - analyst
```

Apply role changes:

```bash
oc apply -f openshift/base/auth/oauth-secrets.yaml
oc rollout restart deployment/oauth-proxy
```

## Security Features

### Network Isolation

- **OAuth Proxy**: Only external access point
- **Dashboard**: Only accessible via OAuth proxy
- **Data Service**: Internal only (no external routes)
- **Database**: Only accessible by application pods

### Access Control

- **Authentication**: OpenShift SSO required for dashboard access
- **Authorization**: Role-based access (admin/analyst/viewer/service)
- **Network Policies**: Strict pod-to-pod communication rules
- **Rate Limiting**: Applied at route level

### Monitoring Access

Health checks bypass OAuth for monitoring tools:

```bash
# Health check URL (IP restricted)
curl https://health-cost-monitor.apps.YOUR-CLUSTER-DOMAIN/health/ready
```

## Troubleshooting

### OAuth Login Issues

```bash
# Check OAuth client status
oc get oauthclient cost-monitor-oauth-client

# Check OAuth proxy logs
oc logs -l component=oauth-proxy

# Check OAuth proxy health endpoint
oc exec -it deploy/oauth-proxy -- curl -I http://localhost:8080/oauth/healthz

# Verify OpenShift OAuth service account
oc get serviceaccount cost-monitor-oauth
oc describe serviceaccount cost-monitor-oauth
```

### Dashboard Access Issues

```bash
# Check dashboard pod status
oc get pods -l component=dashboard

# Check internal connectivity from OAuth proxy to dashboard
oc exec -it deploy/oauth-proxy -- curl -I http://dashboard-service:8050

# Check dashboard logs
oc logs -l component=dashboard

# Test route configuration
oc get route dashboard-route -o yaml
```

### Authentication Flow Issues

```bash
# Check OAuth client redirect URI configuration
oc get oauthclient cost-monitor-oauth-client -o yaml | grep -A5 redirectURIs

# Verify OAuth client secret is properly configured
oc get secret oauth-proxy-secret -o yaml

# Check for authentication errors in proxy logs
oc logs -l component=oauth-proxy | grep -i "error\|denied\|unauthorized"
```

### Data Service Issues

```bash
# Verify data service is internal only (should timeout from external)
curl -I https://cost-monitor-api.apps.cluster.local/api/health/ready

# Check internal connectivity from dashboard to data service
oc exec -it deploy/dashboard -- curl -I http://cost-data-service:8000/api/health/ready

# Check data service logs
oc logs -l component=data-service

# Verify health check route works (bypasses OAuth)
curl -I https://health-cost-monitor.apps.cluster.local/health
```

### TLS Certificate Issues

```bash
# Check route TLS configuration
oc get route dashboard-route -o jsonpath='{.spec.tls}' | jq .

# Verify edge termination is working
curl -kI https://$(oc get route dashboard-route -o jsonpath='{.spec.host}')

# Check for certificate errors in router logs
oc logs -n openshift-ingress -l ingresscontroller.operator.openshift.io/deployment-ingresscontroller=default
```

## Future Enhancements

### JWT API Access

When direct API access is needed, implement JWT authentication:

1. Add JWT middleware to FastAPI data service
2. Create service account tokens
3. Add external API route with JWT validation
4. Update network policies for external API access

### LDAP Integration

For LDAP/AD groups instead of individual user mapping:

1. Configure OpenShift OAuth for LDAP
2. Update group mappings in `oauth-secrets.yaml`
3. Users inherit roles from LDAP group membership

### Advanced Access Control

For fine-grained permissions:

1. Implement resource-level permissions
2. Add cost center / department filtering
3. Create API endpoints for user management
4. Add audit logging for access tracking

## Configuration Reference

### Key Files

- `openshift/base/auth/oauth-proxy.yaml` - OAuth proxy deployment
- `openshift/base/auth/oauth-rbac.yaml` - OpenShift OAuth client and RBAC
- `openshift/base/auth/oauth-secrets.yaml` - User role mappings
- `openshift/base/auth/oauth-routes.yaml` - External routes (dashboard only)
- `openshift/base/security/network-policies.yaml` - Network isolation

### Configuration Reference

**OpenShift OAuth Proxy Arguments:**

| Argument | Description | Value |
|----------|-------------|-------|
| `-provider` | OAuth provider type | `openshift` |
| `-client-id` | OAuth client ID | `cost-monitor-oauth-client` |
| `-client-secret-file` | Path to client secret file | `/etc/proxy/secrets/client-secret` |
| `-cookie-secret-file` | Path to session secret file | `/etc/proxy/secrets/session_secret` |
| `-openshift-service-account` | Service account name | `cost-monitor-oauth` |
| `-http-address` | Internal HTTP listen address | `:8080` |
| `-upstream` | Backend service URL | `http://dashboard-service:8050/` |

**Secret Keys:**

| Key | Description | Generated By |
|-----|-------------|--------------|
| `client-secret` | OAuth client secret | OpenShift (auto-generated) |
| `session_secret` | Session encryption key | deploy.sh (32 random chars) |
| `client-id` | OAuth client identifier | Static: `cost-monitor-oauth-client` |

### Default Roles

| Role | Permissions | Description |
|------|-------------|-------------|
| `admin` | `costs:read`, `costs:export`, `config:read`, `config:write`, `users:manage` | Full access |
| `analyst` | `costs:read`, `costs:export` | Read and export cost data |
| `viewer` | `costs:read` | Read-only access |
| `service` | `costs:read`, `health:read` | Service account access |