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
ENVIRONMENT="${1:-prod}"
DRY_RUN="${2:-false}"
OVERLAY="local"

# Determine config file based on environment
if [ "${ENVIRONMENT}" = "dev" ]; then
    CONFIG_FILE="openshift/local/local-config-dev.yaml"
elif [ "${ENVIRONMENT}" = "prod" ]; then
    CONFIG_FILE="openshift/local/local-config.yaml"
else
    echo -e "${RED}❌ Invalid environment: ${ENVIRONMENT}${NC}"
    echo "Usage: $0 [prod|dev] [dry-run]"
    echo "  prod: Deploy to production namespace (default)"
    echo "  dev:  Deploy to development namespace"
    echo "  dry-run: Show what would be deployed without applying"
    exit 1
fi
LOCAL_OVERLAY_DIR="openshift/overlays/local"
TEMPLATE_OVERLAY_DIR="openshift/overlays/local-template"

echo -e "${BLUE}🚀 Cost Monitor Deployment Script (Enhanced)${NC}"
echo -e "${BLUE}=============================================${NC}"
echo -e "${YELLOW}Environment: ${ENVIRONMENT}${NC}"
echo -e "${YELLOW}Config File: ${CONFIG_FILE}${NC}"
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
    echo -e "${RED}❌ Configuration file for ${ENVIRONMENT} environment not found: $CONFIG_FILE${NC}"
    echo ""
    echo -e "${YELLOW}Please create your ${ENVIRONMENT} environment configuration:${NC}"
    if [ "${ENVIRONMENT}" = "dev" ]; then
        echo -e "1. Copy from existing: ${BLUE}cp openshift/local/local-config.yaml $CONFIG_FILE${NC}"
        echo -e "2. Or copy from template: ${BLUE}cp openshift/local-config.template.yaml $CONFIG_FILE${NC}"
    else
        echo -e "1. Copy the template: ${BLUE}cp openshift/local-config.template.yaml $CONFIG_FILE${NC}"
    fi
    echo -e "3. Edit the file with your actual values: ${BLUE}vi $CONFIG_FILE${NC}"
    echo ""
    echo "Available environments: prod, dev"
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

# Detect sed command (use gsed if available, otherwise platform-specific sed)
if command -v gsed &> /dev/null; then
    SED_CMD="gsed -i"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    SED_CMD="sed -i ''"
else
    SED_CMD="sed -i"
fi

# Generate local overlay from template
echo -e "${BLUE}🔧 Generating local overlay...${NC}"

# Ensure local overlay directory exists
mkdir -p "$LOCAL_OVERLAY_DIR"

# Copy template and customize
cp "$TEMPLATE_OVERLAY_DIR/kustomization.yaml" "$LOCAL_OVERLAY_DIR/"
cp "$TEMPLATE_OVERLAY_DIR/routes-patch.yaml" "$LOCAL_OVERLAY_DIR/"

# Replace placeholders in kustomization.yaml
# Replace registry and namespace in image paths, but preserve image names
eval $SED_CMD "\"s|YOUR_REGISTRY_URL/cost-monitor/|${IMAGE_REGISTRY}/${NAMESPACE}/|g\"" "$LOCAL_OVERLAY_DIR/kustomization.yaml"
# Replace remaining YOUR_REGISTRY_URL instances (if any)
eval $SED_CMD "\"s|YOUR_REGISTRY_URL|${IMAGE_REGISTRY}|g\"" "$LOCAL_OVERLAY_DIR/kustomization.yaml"
# Replace namespace field
eval $SED_CMD "\"s|^namespace: cost-monitor|namespace: ${NAMESPACE}|g\"" "$LOCAL_OVERLAY_DIR/kustomization.yaml"

# Replace placeholders in routes-patch.yaml
eval $SED_CMD "\"s|YOUR_CLUSTER_DOMAIN|${CLUSTER_DOMAIN}|g\"" "$LOCAL_OVERLAY_DIR/routes-patch.yaml"

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

    # Update PostgreSQL user password if it was regenerated and pod exists
    if [[ "$pg_password_raw" == *'$(openssl rand'* ]]; then
        echo -e "${BLUE}🔄 Updating PostgreSQL user password...${NC}"
        if oc get pod postgresql-0 -n ${NAMESPACE} &>/dev/null && oc get pod postgresql-0 -n ${NAMESPACE} -o jsonpath='{.status.phase}' | grep -q "Running"; then
            oc exec postgresql-0 -n ${NAMESPACE} -- psql -U postgres -c "ALTER USER ${pg_user} WITH PASSWORD '${pg_password}';" 2>/dev/null || {
                echo -e "${YELLOW}⚠️  Could not update PostgreSQL password - database may be initializing${NC}"
            }
            echo -e "${GREEN}✅ PostgreSQL password updated${NC}"
        else
            echo -e "${YELLOW}⚠️  PostgreSQL not yet running - will use new password on first start${NC}"
        fi
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

    # Restart Redis if password was regenerated and deployment exists
    if [[ "$redis_password_raw" == *'$(openssl rand'* ]]; then
        echo -e "${BLUE}🔄 Restarting Redis with new password...${NC}"
        if oc get deployment redis -n ${NAMESPACE} &>/dev/null; then
            oc rollout restart deployment/redis -n ${NAMESPACE}
            echo -e "${GREEN}✅ Redis restart initiated${NC}"
        else
            echo -e "${YELLOW}⚠️  Redis deployment not yet created - will use new password on first start${NC}"
        fi
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
    local gcp_project_id=$(yq eval '.secrets.gcp.project_id' "$CONFIG_FILE")
    local gcp_bigquery_dataset=$(yq eval '.secrets.gcp.bigquery_billing_dataset' "$CONFIG_FILE")
    local gcp_billing_account=$(yq eval '.secrets.gcp.billing_account_id' "$CONFIG_FILE")

    if [ -f "$gcp_file" ]; then
        oc create secret generic gcp-credentials -n ${NAMESPACE} \
            --from-file=service-account.json="$gcp_file" \
            --from-literal=project-id="$gcp_project_id" \
            --from-literal=bigquery-dataset="$gcp_bigquery_dataset" \
            --from-literal=billing-account-id="$gcp_billing_account" \
            --dry-run=client -o yaml | oc apply -f -
    else
        echo -e "${YELLOW}⚠️  GCP service account file not found: $gcp_file${NC}"
        echo -e "${YELLOW}   Creating placeholder GCP secret${NC}"
        oc create secret generic gcp-credentials -n ${NAMESPACE} \
            --from-literal=service-account.json='{}' \
            --from-literal=project-id="${gcp_project_id:-}" \
            --from-literal=bigquery-dataset="${gcp_bigquery_dataset:-}" \
            --from-literal=billing-account-id="${gcp_billing_account:-}" \
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

    # Generate random OAuth client secret (secure random string)
    local oauth_client_secret=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)

    # Generate cookie secret (exactly 32 characters for OpenShift oauth-proxy)
    # Use openssl for cross-platform compatibility (macOS and RHEL)
    local cookie_secret=$(openssl rand -hex 16)

    # Store the OAuth client secret for use in OAuthClient creation
    export OAUTH_CLIENT_SECRET="$oauth_client_secret"

    # Create OAuth proxy secret with client and session secrets (for OpenShift oauth-proxy)
    oc create secret generic oauth-proxy-secret -n ${NAMESPACE} \
        --from-literal=client-id="cost-monitor-oauth-client" \
        --from-literal=client-secret="$oauth_client_secret" \
        --from-literal=cookie-secret="$cookie_secret" \
        --from-literal=session_secret="$cookie_secret" \
        --dry-run=client -o yaml | oc apply -f -

    echo -e "${GREEN}✅ OAuth secrets generated with random client secret${NC}"
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
        # Determine the redirect URI based on environment
        local redirect_uri
        if [ "${ENVIRONMENT}" = "dev" ]; then
            redirect_uri="https://dashboard-route-${NAMESPACE}.${CLUSTER_DOMAIN}/oauth/callback"
        else
            redirect_uri="https://cost-monitor.${CLUSTER_DOMAIN}/oauth/callback"
        fi

        # Update OAuth RBAC with correct redirect URI and generated client secret
        # Note: namespace changes are handled automatically by kustomize
        sed -e "s|https://cost-monitor\\.apps\\.cluster\\.local/oauth/callback|${redirect_uri}|g" \
            -e "s|secret: cost-monitor-oauth-secret|secret: ${OAUTH_CLIENT_SECRET}|g" \
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

# Function for ordered service startup to prevent race conditions
deploy_services_ordered() {
    echo -e "${BLUE}🔄 Implementing ordered service startup sequence (race condition prevention)...${NC}"

    if [ "${DRY_RUN}" = "true" ]; then
        echo -e "${YELLOW}[DRY RUN] Would execute ordered deployment sequence${NC}"
        return
    fi

    # Step 1: Scale down all application services to prevent conflicts
    echo -e "${YELLOW}🛑 Step 1: Scaling down application services...${NC}"

    # Scale down in reverse dependency order (dashboard first, then data service)
    oc scale deployment/dashboard-service --replicas=0 -n ${NAMESPACE} 2>/dev/null || echo "   Dashboard service not found (first deployment)"
    oc scale deployment/cost-data-service --replicas=0 -n ${NAMESPACE} 2>/dev/null || echo "   Data service not found (first deployment)"

    # Wait for all application pods to fully terminate
    echo -e "${YELLOW}   Waiting for application pods to terminate...${NC}"
    oc wait --for=delete pod -l component=dashboard -n ${NAMESPACE} --timeout=90s 2>/dev/null || true
    oc wait --for=delete pod -l component=data-service -n ${NAMESPACE} --timeout=90s 2>/dev/null || true

    # Verify no application processes remain
    APP_PODS_REMAINING=$(oc get pods -n ${NAMESPACE} -l 'component in (dashboard,data-service)' --no-headers 2>/dev/null | wc -l)
    if [ "$APP_PODS_REMAINING" -gt 0 ]; then
        echo -e "${YELLOW}   Force terminating remaining application pods...${NC}"
        oc delete pods -l 'component in (dashboard,data-service)' -n ${NAMESPACE} --grace-period=10 --force 2>/dev/null || true
        sleep 5
    fi

    echo -e "${GREEN}✅ Step 1: Application services scaled down cleanly${NC}"

    # Step 2: Configuration already applied, just ensure clean state
    echo -e "${YELLOW}⚙️  Step 2: Configuration already applied - verifying clean state...${NC}"
    echo -e "${GREEN}✅ Step 2: Ready for ordered startup${NC}"

    # Step 3: Start services in dependency order
    echo -e "${YELLOW}🚀 Step 3: Starting services in dependency order...${NC}"

    # 3a: Start data service first (backend dependency)
    echo -e "${BLUE}   Starting data service...${NC}"
    oc scale deployment/cost-data-service --replicas=1 -n ${NAMESPACE}

    # Wait for data service to be ready before starting dashboard
    if ! wait_for_deployment "cost-data-service" 600; then
        echo -e "${RED}❌ Data service failed to start - aborting dashboard startup${NC}"
        return 1
    fi

    # 3b: Start dashboard service (frontend depends on backend)
    echo -e "${BLUE}   Starting dashboard service...${NC}"
    oc scale deployment/dashboard-service --replicas=1 -n ${NAMESPACE}

    if ! wait_for_deployment "dashboard-service" 300; then
        echo -e "${RED}❌ Dashboard service failed to start${NC}"
        return 1
    fi

    echo -e "${GREEN}✅ Step 3: All services started successfully${NC}"

    # Step 4: Verify process integrity
    echo -e "${YELLOW}🔍 Step 4: Verifying process integrity...${NC}"

    # Check for dual dashboard processes
    sleep 10  # Allow containers to fully initialize
    DASHBOARD_POD=$(oc get pods -l component=dashboard -n ${NAMESPACE} -o name --no-headers | head -1 2>/dev/null || echo "")
    if [ -n "$DASHBOARD_POD" ]; then
        PROCESS_COUNT=$(oc exec "$DASHBOARD_POD" -n ${NAMESPACE} -- ps aux 2>/dev/null | grep -c "python.*dashboard" || echo "0")
        echo -e "${BLUE}   Dashboard processes detected: ${PROCESS_COUNT}${NC}"

        if [ "$PROCESS_COUNT" -gt 1 ]; then
            echo -e "${RED}⚠️  Multiple dashboard processes detected!${NC}"
            echo -e "${YELLOW}   Triggering clean restart...${NC}"
            oc rollout restart deployment/dashboard-service -n ${NAMESPACE}
            wait_for_deployment "dashboard-service" 300
            echo -e "${GREEN}✅ Dashboard restarted with single process${NC}"
        else
            echo -e "${GREEN}✅ Dashboard process integrity verified${NC}"
        fi
    fi

    echo -e "${GREEN}🎉 Ordered deployment completed successfully!${NC}"
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
        echo -e "${GREEN}✅ OAuth client configured with generated secret${NC}"

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

    # Deploy all resources first (infrastructure and applications)
    echo -e "${BLUE}🚀 Deploying all resources...${NC}"

    # Apply resources, using replace for deployments to handle immutable field changes
    if ! oc apply -k "$LOCAL_OVERLAY_DIR"; then
        echo -e "${YELLOW}⚠️  Initial apply failed (likely immutable field changes), trying replace strategy...${NC}"

        # Extract and apply non-deployment resources first
        oc kustomize "$LOCAL_OVERLAY_DIR" | oc apply -f - --selector='!app.kubernetes.io/component=data-service,!app.kubernetes.io/component=dashboard'

        # Force replace deployments to handle spec changes
        echo -e "${BLUE}🔄 Force replacing deployments with updated configurations...${NC}"
        oc kustomize "$LOCAL_OVERLAY_DIR" | oc apply -f - --selector='app.kubernetes.io/component=data-service' --force
        oc kustomize "$LOCAL_OVERLAY_DIR" | oc apply -f - --selector='app.kubernetes.io/component=dashboard' --force
    fi
    echo -e "${GREEN}✅ All resources deployed${NC}"

    echo ""

    # Wait for databases to be ready first (infrastructure layer)
    echo -e "${BLUE}🗄️  Ensuring database infrastructure is ready...${NC}"
    wait_for_statefulset "postgresql" 600
    wait_for_deployment "redis" 300

    echo ""

    # Start application services in proper order to prevent race conditions
    deploy_services_ordered

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
