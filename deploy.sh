#!/bin/bash

# Cost Monitor OpenShift Deployment Script with Local Configuration Support
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
OVERLAY="${1:-local}"
DRY_RUN="${2:-false}"
CONFIG_FILE="openshift/local/local-config.yaml"
LOCAL_OVERLAY_DIR="openshift/overlays/local"
TEMPLATE_OVERLAY_DIR="openshift/overlays/local-template"

echo -e "${BLUE}🚀 Cost Monitor Deployment Script (Enhanced)${NC}"
echo -e "${BLUE}=============================================${NC}"
echo ""

# Check for required tools
for tool in oc yq; do
    if ! command -v $tool &> /dev/null; then
        echo -e "${RED}❌ Required tool '$tool' is not installed or not in PATH${NC}"
        if [ "$tool" = "yq" ]; then
            echo "Please install yq: https://github.com/mikefarah/yq#install"
        fi
        exit 1
    fi
done

# Check local configuration
if [ ! -f "$CONFIG_FILE" ]; then
    echo -e "${RED}❌ Local configuration file not found: $CONFIG_FILE${NC}"
    echo ""
    echo -e "${YELLOW}Please create your local configuration:${NC}"
    echo -e "1. Copy the template: ${BLUE}cp openshift/local-config.template.yaml $CONFIG_FILE${NC}"
    echo -e "2. Edit the file with your actual values: ${BLUE}vi $CONFIG_FILE${NC}"
    echo ""
    exit 1
fi

# Load configuration
echo -e "${BLUE}📖 Loading local configuration...${NC}"
NAMESPACE=$(yq eval '.deployment.namespace' "$CONFIG_FILE")
CLUSTER_DOMAIN=$(yq eval '.deployment.cluster_domain' "$CONFIG_FILE")
IMAGE_REGISTRY=$(yq eval '.deployment.image_registry' "$CONFIG_FILE")
GIT_REPOSITORY=$(yq eval '.git.repository' "$CONFIG_FILE")
GIT_BRANCH=$(yq eval '.git.branch' "$CONFIG_FILE")
GIT_CONTEXT_DIR=$(yq eval '.git.context_dir // "."' "$CONFIG_FILE")
OAUTH_ENABLED=$(yq eval '.oauth.enabled // true' "$CONFIG_FILE")

echo -e "Namespace: ${GREEN}${NAMESPACE}${NC}"
echo -e "Cluster Domain: ${GREEN}${CLUSTER_DOMAIN}${NC}"
echo -e "Image Registry: ${GREEN}${IMAGE_REGISTRY}${NC}"
echo -e "Repository: ${GREEN}${GIT_REPOSITORY}${NC}"
echo -e "Branch: ${GREEN}${GIT_BRANCH}${NC}"
echo -e "OAuth SSO: ${GREEN}${OAUTH_ENABLED}${NC}"
echo -e "Dry Run: ${GREEN}${DRY_RUN}${NC}"
echo ""

# Check if we're logged in to OpenShift
if ! oc whoami &> /dev/null; then
    echo -e "${RED}❌ Not logged in to OpenShift cluster${NC}"
    echo "Please login using: oc login <cluster-url>"
    exit 1
fi

echo -e "${GREEN}✅ OpenShift CLI ready${NC}"
echo -e "${GREEN}✅ Logged in as: $(oc whoami)${NC}"
echo ""

# Generate local overlay from template
echo -e "${BLUE}🔧 Generating local overlay...${NC}"

# Ensure local overlay directory exists
mkdir -p "$LOCAL_OVERLAY_DIR"

# Copy template and customize
cp "$TEMPLATE_OVERLAY_DIR/kustomization.yaml" "$LOCAL_OVERLAY_DIR/"
cp "$TEMPLATE_OVERLAY_DIR/routes-patch.yaml" "$LOCAL_OVERLAY_DIR/"

# Replace placeholders in kustomization.yaml
sed -i "s|YOUR_REGISTRY_URL|${IMAGE_REGISTRY}|g" "$LOCAL_OVERLAY_DIR/kustomization.yaml"
sed -i "s|cost-monitor|${NAMESPACE}|g" "$LOCAL_OVERLAY_DIR/kustomization.yaml"

# Replace placeholders in routes-patch.yaml
sed -i "s|YOUR_CLUSTER_DOMAIN|${CLUSTER_DOMAIN}|g" "$LOCAL_OVERLAY_DIR/routes-patch.yaml"

echo -e "${GREEN}✅ Local overlay generated${NC}"

# Function to wait for deployment
wait_for_deployment() {
    local deployment_name=$1
    local timeout=${2:-300}

    echo -e "${YELLOW}⏳ Waiting for deployment ${deployment_name} to be ready...${NC}"

    if oc rollout status deployment/${deployment_name} -n ${NAMESPACE} --timeout=${timeout}s; then
        echo -e "${GREEN}✅ Deployment ${deployment_name} is ready${NC}"
    else
        echo -e "${RED}❌ Deployment ${deployment_name} failed to become ready${NC}"
        return 1
    fi
}

# Function to wait for StatefulSet
wait_for_statefulset() {
    local sts_name=$1
    local timeout=${2:-300}

    echo -e "${YELLOW}⏳ Waiting for StatefulSet ${sts_name} to be ready...${NC}"

    if oc rollout status statefulset/${sts_name} -n ${NAMESPACE} --timeout=${timeout}s; then
        echo -e "${GREEN}✅ StatefulSet ${sts_name} is ready${NC}"
    else
        echo -e "${RED}❌ StatefulSet ${sts_name} failed to become ready${NC}"
        return 1
    fi
}

# Function to create secrets from configuration
create_secrets() {
    echo -e "${BLUE}🔐 Creating secrets...${NC}"

    # PostgreSQL credentials
    local pg_user=$(yq eval '.secrets.postgresql.username' "$CONFIG_FILE")
    local pg_password_raw=$(yq eval '.secrets.postgresql.password' "$CONFIG_FILE")

    # Generate URL-safe passwords (no special characters that break URLs)
    if [[ "$pg_password_raw" == *'$(openssl rand'* ]]; then
        local pg_password=$(openssl rand -hex 32)  # Use hex instead of base64 for URL safety
    else
        local pg_password=$(eval echo "$pg_password_raw")
    fi

    local pg_database=$(yq eval '.secrets.postgresql.database' "$CONFIG_FILE")

    oc create secret generic postgresql-credentials -n ${NAMESPACE} \
        --from-literal=username="$pg_user" \
        --from-literal=password="$pg_password" \
        --from-literal=database="$pg_database" \
        --from-literal=admin-password="$pg_password" \
        --dry-run=client -o yaml | oc apply -f -

    # Update PostgreSQL user password if it was regenerated
    if [[ "$pg_password_raw" == *'$(openssl rand'* ]]; then
        echo -e "${BLUE}🔄 Updating PostgreSQL user password...${NC}"
        oc exec postgresql-0 -n ${NAMESPACE} -- psql -U postgres -c "ALTER USER ${pg_user} WITH PASSWORD '${pg_password}';" 2>/dev/null || {
            echo -e "${YELLOW}⚠️  Could not update PostgreSQL password - database may be initializing${NC}"
        }
        echo -e "${GREEN}✅ PostgreSQL password updated${NC}"
    fi

    # Redis credentials
    local redis_password_raw=$(yq eval '.secrets.redis.password' "$CONFIG_FILE")

    # Generate URL-safe Redis password
    if [[ "$redis_password_raw" == *'$(openssl rand'* ]]; then
        local redis_password=$(openssl rand -hex 32)  # Use hex for URL safety
    else
        local redis_password=$(eval echo "$redis_password_raw")
    fi

    oc create secret generic redis-credentials -n ${NAMESPACE} \
        --from-literal=password="$redis_password" \
        --dry-run=client -o yaml | oc apply -f -

    # Restart Redis if password was regenerated (Redis reads password from secret on startup)
    if [[ "$redis_password_raw" == *'$(openssl rand'* ]]; then
        echo -e "${BLUE}🔄 Restarting Redis with new password...${NC}"
        oc rollout restart deployment/redis -n ${NAMESPACE} || {
            echo -e "${YELLOW}⚠️  Could not restart Redis deployment${NC}"
        }
        echo -e "${GREEN}✅ Redis restart initiated${NC}"
    fi

    # AWS credentials
    local aws_key=$(yq eval '.secrets.aws.access_key_id' "$CONFIG_FILE")
    local aws_secret=$(yq eval '.secrets.aws.secret_access_key' "$CONFIG_FILE")

    oc create secret generic aws-credentials -n ${NAMESPACE} \
        --from-literal=access-key-id="$aws_key" \
        --from-literal=secret-access-key="$aws_secret" \
        --dry-run=client -o yaml | oc apply -f -

    # Azure credentials
    local azure_client_id=$(yq eval '.secrets.azure.client_id' "$CONFIG_FILE")
    local azure_client_secret=$(yq eval '.secrets.azure.client_secret' "$CONFIG_FILE")
    local azure_tenant_id=$(yq eval '.secrets.azure.tenant_id' "$CONFIG_FILE")
    local azure_subscription_id=$(yq eval '.secrets.azure.subscription_id' "$CONFIG_FILE")
    local azure_storage_account=$(yq eval '.secrets.azure.storage_account' "$CONFIG_FILE")
    local azure_export_name=$(yq eval '.secrets.azure.export_name' "$CONFIG_FILE")
    local azure_container=$(yq eval '.secrets.azure.container' "$CONFIG_FILE")

    oc create secret generic azure-credentials -n ${NAMESPACE} \
        --from-literal=client-id="$azure_client_id" \
        --from-literal=client-secret="$azure_client_secret" \
        --from-literal=tenant-id="$azure_tenant_id" \
        --from-literal=subscription-id="$azure_subscription_id" \
        --from-literal=storage-account="$azure_storage_account" \
        --from-literal=export-name="$azure_export_name" \
        --from-literal=container="$azure_container" \
        --dry-run=client -o yaml | oc apply -f -

    # GCP credentials (if service account file exists)
    local gcp_file=$(yq eval '.secrets.gcp.service_account_file' "$CONFIG_FILE")
    if [ -f "$gcp_file" ]; then
        oc create secret generic gcp-credentials -n ${NAMESPACE} \
            --from-file=service-account.json="$gcp_file" \
            --dry-run=client -o yaml | oc apply -f -
    else
        echo -e "${YELLOW}⚠️  GCP service account file not found: $gcp_file${NC}"
        echo -e "${YELLOW}   Creating placeholder GCP secret${NC}"
        oc create secret generic gcp-credentials -n ${NAMESPACE} \
            --from-literal=service-account.json='{}' \
            --dry-run=client -o yaml | oc apply -f -
    fi

    # Webhook secrets
    local github_secret=$(yq eval '.secrets.webhook.github_secret' "$CONFIG_FILE")
    local generic_secret=$(yq eval '.secrets.webhook.generic_secret' "$CONFIG_FILE")

    oc create secret generic webhook-secrets -n ${NAMESPACE} \
        --from-literal=github="$github_secret" \
        --from-literal=generic="$generic_secret" \
        --dry-run=client -o yaml | oc apply -f -

    echo -e "${GREEN}✅ Secrets created/updated${NC}"
}

# Update buildconfig with repository URL
update_buildconfigs() {
    echo -e "${BLUE}🔨 Updating build configurations...${NC}"

    # Create temporary buildconfig with updated repository and context
    local temp_buildconfig="/tmp/buildconfig-updated.yaml"
    sed -e "s|REPLACE_WITH_YOUR_REPOSITORY_URL|${GIT_REPOSITORY}|g" \
        -e "s|contextDir: \".\"|contextDir: \"${GIT_CONTEXT_DIR}\"|g" \
        openshift/base/buildconfigs/buildconfigs.yaml > "$temp_buildconfig"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would apply updated buildconfig${NC}"
    else
        oc apply -f "$temp_buildconfig" -n ${NAMESPACE}
        rm -f "$temp_buildconfig"
    fi

    echo -e "${GREEN}✅ Build configurations updated${NC}"
}

# OAuth setup functions
detect_oauth_settings() {
    echo -e "${BLUE}🔍 Detecting OpenShift OAuth configuration...${NC}"

    # Get cluster OAuth issuer URL
    local oauth_route=""
    if oc get route oauth-openshift -n openshift-authentication &> /dev/null; then
        oauth_route=$(oc get route oauth-openshift -n openshift-authentication -o jsonpath='{.spec.host}' 2>/dev/null)
    fi

    if [ -z "$oauth_route" ]; then
        # Try alternative method
        oauth_route=$(oc get ingress cluster -o jsonpath='{.status.domain}' 2>/dev/null || echo "oauth-openshift.${CLUSTER_DOMAIN}")
        oauth_route="oauth-openshift.${oauth_route}"
    fi

    OAUTH_ISSUER_URL="https://${oauth_route}"

    echo -e "${GREEN}✅ OAuth issuer URL: ${OAUTH_ISSUER_URL}${NC}"

    # Get cluster app domain
    OAUTH_COOKIE_DOMAIN=".${CLUSTER_DOMAIN}"

    echo -e "${GREEN}✅ Cookie domain: ${OAUTH_COOKIE_DOMAIN}${NC}"
}

generate_tls_secret() {
    echo -e "${BLUE}🔐 Generating TLS secrets for OAuth proxy...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would generate TLS secrets${NC}"
        return
    fi

    # Add service annotation to automatically generate TLS certificates
    oc annotate service oauth-proxy-service -n ${NAMESPACE} \
        service.alpha.openshift.io/serving-cert-secret-name=proxy-tls \
        --overwrite

    echo -e "${GREEN}✅ TLS secret configured for auto-generation${NC}"
}

generate_oauth_secrets() {
    echo -e "${BLUE}🔐 Generating OAuth secrets...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would generate OAuth secrets${NC}"
        return
    fi

    # Generate cookie secret (exactly 32 characters for OpenShift oauth-proxy)
    local cookie_secret=$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c32)

    # Create OAuth proxy secret with client and session secrets (for OpenShift oauth-proxy)
    oc create secret generic oauth-proxy-secret -n ${NAMESPACE} \
        --from-literal=client-id="cost-monitor-oauth-client" \
        --from-literal=client-secret="" \
        --from-literal=session_secret="$cookie_secret" \
        --dry-run=client -o yaml | oc apply -f -

    echo -e "${GREEN}✅ OAuth secrets generated with session secret${NC}"
}

configure_oauth_files() {
    echo -e "${BLUE}🔧 Configuring OAuth files...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would configure OAuth files for cluster-specific deployment${NC}"
        return
    fi

    # Create OAuth patches directory in local overlay
    mkdir -p "$LOCAL_OVERLAY_DIR/auth-patches"

    # Copy and update OAuth proxy configuration with cluster-specific values
    local oauth_proxy_base="openshift/base/auth/oauth-proxy.yaml"
    local oauth_proxy_patch="$LOCAL_OVERLAY_DIR/auth-patches/oauth-proxy-patch.yaml"
    if [ -f "$oauth_proxy_base" ]; then
        # Create cluster-specific OAuth proxy configuration
        # The OAuth proxy now uses args-based configuration, so we only need basic substitutions
        sed -e "s|redis-auth|redis-credentials|g" \
            "$oauth_proxy_base" > "$oauth_proxy_patch"
        echo "Created OAuth proxy patch: $oauth_proxy_patch"
    fi

    # Copy and update OAuth routes with cluster domain
    local oauth_routes_base="openshift/base/auth/oauth-routes.yaml"
    local oauth_routes_patch="$LOCAL_OVERLAY_DIR/auth-patches/oauth-routes-patch.yaml"
    if [ -f "$oauth_routes_base" ]; then
        sed -e "s|health-cost-monitor\\.apps\\.cluster\\.local|health-cost-monitor.${CLUSTER_DOMAIN}|g" \
            "$oauth_routes_base" > "$oauth_routes_patch"
        echo "Created OAuth routes patch: $oauth_routes_patch"
    fi

    # Copy and update OAuth RBAC redirect URIs
    local oauth_rbac_base="openshift/base/auth/oauth-rbac.yaml"
    local oauth_rbac_patch="$LOCAL_OVERLAY_DIR/auth-patches/oauth-rbac-patch.yaml"
    if [ -f "$oauth_rbac_base" ]; then
        sed -e "s|cost-monitor\\.apps\\.cluster\\.local|cost-monitor.${CLUSTER_DOMAIN}|g" \
            "$oauth_rbac_base" > "$oauth_rbac_patch"
        echo "Created OAuth RBAC patch: $oauth_rbac_patch"
    fi

    # Update local overlay kustomization.yaml to include OAuth patches
    local kustomization_file="$LOCAL_OVERLAY_DIR/kustomization.yaml"
    if [ -f "$kustomization_file" ]; then
        # Add OAuth patches to kustomization if not already present
        if ! grep -q "auth-patches" "$kustomization_file"; then
            cat >> "$kustomization_file" << EOF

# OAuth cluster-specific configurations
patchesStrategicMerge:
- auth-patches/oauth-proxy-patch.yaml
- auth-patches/oauth-routes-patch.yaml
- auth-patches/oauth-rbac-patch.yaml
EOF
        fi
    fi

    echo -e "${GREEN}✅ OAuth configuration files configured for deployment${NC}"
}

# Function to clean up stuck deployments
cleanup_stuck_deployments() {
    echo -e "${BLUE}🧹 Cleaning up stuck deployments...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would clean up stuck deployments${NC}"
        return
    fi

    # Check for data service pods with many restarts or stuck state
    local problematic_pods=$(oc get pods -n ${NAMESPACE} -l component=data-service --no-headers 2>/dev/null | awk '{if($4 > 3 || $3 ~ /Error|CrashLoopBackOff/) print $1}' || echo "")
    local stuck_rollout=$(oc rollout status deployment/cost-data-service -n ${NAMESPACE} --timeout=5s 2>&1 | grep -q "Waiting for deployment" && echo "stuck" || echo "")

    if [ -n "$problematic_pods" ] || [ -n "$stuck_rollout" ]; then
        echo -e "${YELLOW}🔄 Scaling down cost-data-service to force clean restart...${NC}"

        # Scale down to 0
        oc scale deployment/cost-data-service --replicas=0 -n ${NAMESPACE}

        # Wait for pods to terminate
        echo -e "${YELLOW}   Waiting for pods to terminate...${NC}"
        oc wait --for=delete pod -l component=data-service -n ${NAMESPACE} --timeout=60s 2>/dev/null || true

        # Scale back up to 1
        echo -e "${YELLOW}   Scaling back up...${NC}"
        oc scale deployment/cost-data-service --replicas=1 -n ${NAMESPACE}

        echo -e "${GREEN}✅ Cost data service restarted cleanly${NC}"
    fi

    # Clean up failed OAuth proxy pods (these we can just delete)
    local failed_oauth_pods=$(oc get pods -n ${NAMESPACE} -l component=oauth-proxy --field-selector=status.phase=Failed -o name 2>/dev/null || echo "")
    if [ -n "$failed_oauth_pods" ]; then
        echo -e "${YELLOW}🗑️  Removing failed OAuth proxy pods...${NC}"
        echo "$failed_oauth_pods" | xargs oc delete -n ${NAMESPACE} --ignore-not-found=true
    fi

    echo -e "${GREEN}✅ Cleanup completed${NC}"
}

setup_oauth_client() {
    echo -e "${BLUE}🔑 Setting up OAuth client...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would verify OAuth client setup${NC}"
        return
    fi

    # Clean up any failed OAuth proxy pods first
    echo -e "${BLUE}🧹 Cleaning up failed OAuth proxy pods...${NC}"
    oc delete pods -l component=oauth-proxy --field-selector=status.phase=Failed -n ${NAMESPACE} --ignore-not-found=true

    # Wait for OAuth client to be created by the deployment
    local max_attempts=30
    local attempt=0

    echo -e "${YELLOW}⏳ Waiting for OAuth client to be created...${NC}"
    while [ $attempt -lt $max_attempts ]; do
        if oc get oauthclient cost-monitor-oauth-client &> /dev/null; then
            echo -e "${GREEN}✅ OAuth client found${NC}"
            break
        fi
        attempt=$((attempt + 1))
        if [ $((attempt % 5)) -eq 0 ]; then
            echo -e "${YELLOW}   Still waiting... ($attempt/$max_attempts)${NC}"
        fi
        sleep 3
    done

    if [ $attempt -lt $max_attempts ]; then
        # Get the OAuth client secret and update the proxy secret
        local client_secret=$(oc get oauthclient cost-monitor-oauth-client -o jsonpath='{.secret}' 2>/dev/null)
        if [ -n "$client_secret" ]; then
            echo -e "${BLUE}🔧 Updating OAuth proxy secret with client secret...${NC}"
            oc patch secret oauth-proxy-secret -n ${NAMESPACE} \
                -p "{\"stringData\":{\"client-secret\":\"$client_secret\"}}"
            echo -e "${GREEN}✅ OAuth client secret updated${NC}"
        fi

        # Restart OAuth proxy pods to pick up updated secrets
        echo -e "${BLUE}🔄 Restarting OAuth proxy...${NC}"
        oc delete pods -l component=oauth-proxy -n ${NAMESPACE} --ignore-not-found=true

        # Wait a moment for new pods to start
        sleep 5
        echo -e "${GREEN}✅ OAuth proxy restarted${NC}"
    else
        echo -e "${RED}❌ Failed to find OAuth client after ${max_attempts} attempts${NC}"
        return 1
    fi
}

# Create namespace if it doesn't exist
echo -e "${BLUE}📁 Creating namespace...${NC}"
if oc get namespace ${NAMESPACE} &> /dev/null; then
    echo -e "${YELLOW}⚠️  Namespace ${NAMESPACE} already exists${NC}"
else
    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would create namespace: ${NAMESPACE}${NC}"
    else
        oc create namespace ${NAMESPACE}
        echo -e "${GREEN}✅ Created namespace: ${NAMESPACE}${NC}"
    fi
fi

echo ""

# Deploy the application
echo -e "${BLUE}🎯 Deploying Cost Monitor...${NC}"

if [ "${DRY_RUN}" = "true" ]; then
    echo -e "${YELLOW}[DRY RUN] Would deploy with kustomize...${NC}"
    oc kustomize "$LOCAL_OVERLAY_DIR" || {
        echo -e "${RED}❌ Kustomization failed${NC}"
        exit 1
    }
    echo -e "${YELLOW}[DRY RUN] Would create secrets from configuration${NC}"
    if [ "${OAUTH_ENABLED}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would setup OAuth integration${NC}"
    fi
    echo -e "${YELLOW}[DRY RUN] Would update buildconfigs with repository URL${NC}"
else
    # Create secrets first
    create_secrets

    echo ""

    # Setup OAuth if enabled
    if [ "${OAUTH_ENABLED}" = "true" ]; then
        detect_oauth_settings
        echo ""
        generate_oauth_secrets
        echo ""
        configure_oauth_files
        echo ""
    fi

    # Update buildconfigs
    update_buildconfigs

    echo ""

    # Apply all resources with local overlay
    oc apply -k "$LOCAL_OVERLAY_DIR" || {
        echo -e "${RED}❌ Deployment failed${NC}"
        exit 1
    }

    echo ""

    # Clean up any stuck deployments before waiting
    cleanup_stuck_deployments

    echo ""

    # Wait for databases to be ready first
    echo -e "${BLUE}🗄️  Waiting for data services...${NC}"
    wait_for_statefulset "postgresql" 600
    wait_for_deployment "redis" 300

    echo ""

    # Wait for application services
    echo -e "${BLUE}🔧 Waiting for application services...${NC}"
    wait_for_deployment "cost-data-service" 600

    # Dashboard deployment has different name pattern
    if oc get deployment "cost-monitor-dashboard" -n ${NAMESPACE} &> /dev/null; then
        wait_for_deployment "cost-monitor-dashboard" 300
    elif oc get deploymentconfig "cost-monitor-dashboard" -n ${NAMESPACE} &> /dev/null; then
        echo -e "${YELLOW}⏳ Waiting for DeploymentConfig cost-monitor-dashboard to be ready...${NC}"
        oc rollout status dc/cost-monitor-dashboard -n ${NAMESPACE} --timeout=300s
        echo -e "${GREEN}✅ DeploymentConfig cost-monitor-dashboard is ready${NC}"
    fi

    # Setup OAuth client and wait for proxy if enabled
    if [ "${OAUTH_ENABLED}" = "true" ]; then
        if ! setup_oauth_client; then
            echo -e "${RED}❌ OAuth client setup failed - deployment cannot continue${NC}"
            echo -e "${BLUE}💡 OAuth is required for application access${NC}"
            exit 1
        fi
        echo ""
        if ! wait_for_deployment "oauth-proxy" 300; then
            echo -e "${RED}❌ OAuth proxy failed - application will not be accessible${NC}"
            echo -e "${BLUE}💡 Check OAuth proxy logs: oc logs -l component=oauth-proxy -n ${NAMESPACE}${NC}"
            exit 1
        fi
    fi

    echo ""

    # Show deployment status
    echo -e "${BLUE}📊 Deployment Status:${NC}"
    oc get pods -n ${NAMESPACE}

    echo ""

    # Show routes
    echo -e "${BLUE}🌐 Routes:${NC}"
    oc get routes -n ${NAMESPACE}

    echo ""

    # Final status
    echo -e "${GREEN}🎉 Deployment completed successfully!${NC}"
    echo ""

    # Show appropriate URLs based on OAuth configuration
    if [ "${OAUTH_ENABLED}" = "true" ]; then
        echo -e "${BLUE}🔐 OAuth-Protected URLs:${NC}"
        DASHBOARD_URL=$(oc get route dashboard-route -n ${NAMESPACE} -o jsonpath='{.spec.host}' 2>/dev/null || echo "dashboard-route-${NAMESPACE}.${CLUSTER_DOMAIN}")
        echo -e "${BLUE}Dashboard URL (OAuth):${NC} https://${DASHBOARD_URL}"
        echo -e "${BLUE}Health URL (Direct):${NC} https://health-cost-monitor.${CLUSTER_DOMAIN}/health"
        echo ""
        echo -e "${YELLOW}📝 OAuth Information:${NC}"
        echo -e "   • Dashboard access requires OpenShift login"
        echo -e "   • Data API is internal only (no external access)"
        echo -e "   • Health checks available for monitoring tools"
    else
        echo -e "${BLUE}📖 Standard URLs:${NC}"
        echo -e "${BLUE}Dashboard URL:${NC} https://cost-monitor.${CLUSTER_DOMAIN}"
        echo -e "${BLUE}API URL:${NC} https://cost-api.${CLUSTER_DOMAIN}/api"
        echo -e "${BLUE}Health URL:${NC} https://cost-health.${CLUSTER_DOMAIN}/health"
    fi
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    if [ "${OAUTH_ENABLED}" = "true" ]; then
        echo -e "1. Access the dashboard:"
        echo -e "   ${YELLOW}https://${DASHBOARD_URL}${NC}"
        echo -e "   (Login with your OpenShift credentials)"
        echo ""
        echo -e "2. Configure user roles (optional):"
        echo -e "   ${YELLOW}oc edit configmap user-roles -n ${NAMESPACE}${NC}"
        echo -e "   See ${BLUE}docs/oauth-setup.md${NC} for detailed configuration"
        echo ""
        echo -e "3. Monitor OAuth proxy logs:"
        echo -e "   ${YELLOW}oc logs -f deployment/oauth-proxy -n ${NAMESPACE}${NC}"
        echo ""
        echo -e "4. Trigger initial data collection:"
        echo -e "   ${YELLOW}oc create job initial-collection --from=cronjob/historical-data-collection -n ${NAMESPACE}${NC}"
        echo ""
        echo -e "5. Monitor application logs:"
        echo -e "   ${YELLOW}oc logs -f deployment/cost-data-service -n ${NAMESPACE}${NC}"
        echo -e "   ${YELLOW}oc logs -f dc/cost-monitor-dashboard -n ${NAMESPACE}${NC}"
    else
        echo -e "1. Trigger initial data collection:"
        echo -e "   ${YELLOW}oc create job initial-collection --from=cronjob/historical-data-collection -n ${NAMESPACE}${NC}"
        echo ""
        echo -e "2. Monitor the logs:"
        echo -e "   ${YELLOW}oc logs -f deployment/cost-data-service -n ${NAMESPACE}${NC}"
        echo -e "   ${YELLOW}oc logs -f dc/cost-monitor-dashboard -n ${NAMESPACE}${NC}"
        echo ""
        echo -e "3. Access the dashboard at: ${BLUE}https://cost-monitor.${CLUSTER_DOMAIN}${NC}"
    fi
fi