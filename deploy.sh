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

echo -e "Namespace: ${GREEN}${NAMESPACE}${NC}"
echo -e "Cluster Domain: ${GREEN}${CLUSTER_DOMAIN}${NC}"
echo -e "Image Registry: ${GREEN}${IMAGE_REGISTRY}${NC}"
echo -e "Repository: ${GREEN}${GIT_REPOSITORY}${NC}"
echo -e "Branch: ${GREEN}${GIT_BRANCH}${NC}"
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
    local pg_password=$(yq eval '.secrets.postgresql.password' "$CONFIG_FILE")
    local pg_database=$(yq eval '.secrets.postgresql.database' "$CONFIG_FILE")

    oc create secret generic postgresql-credentials -n ${NAMESPACE} \
        --from-literal=username="$pg_user" \
        --from-literal=password="$pg_password" \
        --from-literal=database="$pg_database" \
        --dry-run=client -o yaml | oc apply -f -

    # Redis credentials
    local redis_password=$(yq eval '.secrets.redis.password' "$CONFIG_FILE")

    oc create secret generic redis-credentials -n ${NAMESPACE} \
        --from-literal=password="$redis_password" \
        --dry-run=client -o yaml | oc apply -f -

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

    oc create secret generic azure-credentials -n ${NAMESPACE} \
        --from-literal=client-id="$azure_client_id" \
        --from-literal=client-secret="$azure_client_secret" \
        --from-literal=tenant-id="$azure_tenant_id" \
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
    echo -e "${YELLOW}[DRY RUN] Would update buildconfigs with repository URL${NC}"
else
    # Create secrets first
    create_secrets

    echo ""

    # Update buildconfigs
    update_buildconfigs

    echo ""

    # Apply all resources with local overlay
    oc apply -k "$LOCAL_OVERLAY_DIR" || {
        echo -e "${RED}❌ Deployment failed${NC}"
        exit 1
    }

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
    echo -e "${BLUE}Dashboard URL:${NC} https://cost-monitor.${CLUSTER_DOMAIN}"
    echo -e "${BLUE}API URL:${NC} https://cost-api.${CLUSTER_DOMAIN}/api"
    echo -e "${BLUE}Health URL:${NC} https://cost-health.${CLUSTER_DOMAIN}/health"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo -e "1. Trigger initial data collection:"
    echo -e "   ${YELLOW}oc create job initial-collection --from=cronjob/historical-data-collection -n ${NAMESPACE}${NC}"
    echo ""
    echo -e "2. Monitor the logs:"
    echo -e "   ${YELLOW}oc logs -f deployment/cost-data-service -n ${NAMESPACE}${NC}"
    echo -e "   ${YELLOW}oc logs -f dc/cost-monitor-dashboard -n ${NAMESPACE}${NC}"
    echo ""
    echo -e "3. Access the dashboard at: ${BLUE}https://cost-monitor.${CLUSTER_DOMAIN}${NC}"
fi