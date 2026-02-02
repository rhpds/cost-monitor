#!/bin/bash

# Local Development Environment Script
# Sets up tunnels and runs services locally for fast development iteration

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
API_PORT=8000
DASHBOARD_PORT=8050
REDIS_PORT=6379
POSTGRES_PORT=5432

# Smart parameter parsing to handle both formats:
# Format 1: ./script action component (namespace defaults to cost-monitor-dev)
# Format 2: ./script namespace action component
if [ $# -eq 2 ]; then
    # Two arguments: assume action component, use default namespace
    NAMESPACE="cost-monitor-dev"
    ACTION="$1"
    COMPONENT="$2"
elif [ $# -eq 3 ]; then
    # Three arguments: namespace action component
    NAMESPACE="$1"
    ACTION="$2"
    COMPONENT="$3"
elif [ $# -eq 1 ]; then
    # One argument: could be action (help) or namespace only
    if [ "$1" = "help" ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
        NAMESPACE="cost-monitor-dev"
        ACTION="help"
        COMPONENT=""
    else
        # Single argument that's not help - show error
        echo -e "${RED}ERROR: Invalid arguments. See usage below:${NC}"
        echo ""
        show_help
        exit 1
    fi
else
    # Zero or more than 3 arguments
    NAMESPACE="cost-monitor-dev"
    ACTION="help"
    COMPONENT=""
fi

# Service configuration
API_HOST="0.0.0.0"

# Timing configuration
TUNNEL_STARTUP_DELAY=2
SERVICE_STARTUP_DELAY=3

# Temporary directory for tracking processes and logs
TMP_DIR="/tmp/cost-monitor-dev"
mkdir -p "$TMP_DIR"

show_help() {
    echo "Local Development Environment Manager"
    echo ""
    echo "Usage:"
    echo "  $0 [ACTION] [COMPONENT]                 # Uses default namespace: cost-monitor-dev"
    echo "  $0 [NAMESPACE] [ACTION] [COMPONENT]     # Uses custom namespace"
    echo ""
    echo "Actions:"
    echo "  start           - Start services/tunnels"
    echo "  stop            - Stop services/tunnels"
    echo "  restart         - Restart services/tunnels"
    echo "  status          - Show status of services/tunnels"
    echo "  logs            - Show logs for services/tunnels"
    echo "  clear-redis-cache - Clear Redis cache"
    echo ""
    echo "Components (required for most actions):"
    echo "  all              - All components"
    echo "  api              - API service"
    echo "  dashboard        - Dashboard service"
    echo "  postgres-tunnel  - PostgreSQL tunnel"
    echo "  redis-tunnel     - Redis tunnel"
    echo "  all-tunnels      - Both tunnels"
    echo "  postgres-pod     - PostgreSQL pod (OpenShift)"
    echo "  redis-pod        - Redis pod (OpenShift)"
    echo "  all-pods         - Both database pods (OpenShift)"
    echo ""
    echo "Simple Examples (default namespace):"
    echo "  $0 start all               # Start everything in cost-monitor-dev"
    echo "  $0 start api               # Start just API in cost-monitor-dev"
    echo "  $0 stop dashboard          # Stop just dashboard"
    echo "  $0 restart postgres-tunnel # Restart PostgreSQL tunnel"
    echo "  $0 status all              # Status of everything"
    echo "  $0 logs api                # Show API logs"
    echo ""
    echo "Custom Namespace Examples:"
    echo "  $0 my-namespace start all       # Start everything in custom namespace"
    echo "  $0 prod-monitor logs redis-pod  # Show Redis pod logs from prod-monitor namespace"
}

get_secret() {
    local secret_name=$1
    local key=$2
    oc get secret "$secret_name" -n "$NAMESPACE" -o jsonpath="{.data.$key}" 2>/dev/null | base64 -d
}

load_credentials() {
    if [ -z "$DEV_POSTGRES_PASSWORD" ] || [ -z "$DEV_REDIS_PASSWORD" ] || [ -z "$DEV_POSTGRES_USER" ] || [ -z "$DEV_POSTGRES_DATABASE" ]; then
        echo -e "${YELLOW}Loading credentials from OpenShift...${NC}"
        export DEV_POSTGRES_USER=$(get_secret postgresql-credentials username)
        export DEV_POSTGRES_DATABASE=$(get_secret postgresql-credentials database)
        export DEV_POSTGRES_PASSWORD=$(get_secret postgresql-credentials password)
        export DEV_REDIS_PASSWORD=$(get_secret redis-credentials password)
        if [ -z "$DEV_POSTGRES_USER" ] || [ -z "$DEV_POSTGRES_DATABASE" ] || [ -z "$DEV_POSTGRES_PASSWORD" ] || [ -z "$DEV_REDIS_PASSWORD" ]; then
            echo -e "${RED}ERROR: Failed to load credentials from OpenShift secrets${NC}"
            exit 1
        fi
    fi
}

# Check if a service is running by PID file
is_service_running() {
    local service=$1
    [ -f "$TMP_DIR/$service.pid" ] && kill -0 $(cat "$TMP_DIR/$service.pid") 2>/dev/null
}

# Kill existing service if running
kill_existing_service() {
    local service=$1
    if [ -f "$TMP_DIR/$service.pid" ]; then
        kill $(cat "$TMP_DIR/$service.pid") 2>/dev/null || true
        rm -f "$TMP_DIR/$service.pid"
    fi
}

# Start a tunnel for a service
start_tunnel() {
    local service=$1
    local local_port=$2
    local remote_port=$3
    local oc_service=$4

    echo -e "${YELLOW}   Starting $service tunnel...${NC}"
    pkill -f "oc port-forward.*$oc_service" 2>/dev/null || true
    oc port-forward svc/$oc_service $local_port:$remote_port -n "$NAMESPACE" > "$TMP_DIR/$service-tunnel.log" 2>&1 &
    echo $! > "$TMP_DIR/$service.pid"
    sleep $TUNNEL_STARTUP_DELAY
    if nc -z localhost $local_port 2>/dev/null; then
        echo -e "${GREEN}    OK: $service tunnel ready${NC}"
    else
        echo -e "${RED}    ERROR: $service tunnel failed${NC}"
        return 1
    fi
}

# Set up common environment variables for services
setup_service_env() {
    export DATABASE_URL="postgresql://$DEV_POSTGRES_USER:$DEV_POSTGRES_PASSWORD@localhost:$POSTGRES_PORT/$DEV_POSTGRES_DATABASE"
    export POSTGRES_HOST=localhost
    export POSTGRES_PORT=$POSTGRES_PORT
    export POSTGRESQL_USER="$DEV_POSTGRES_USER"
    export POSTGRESQL_PASSWORD="$DEV_POSTGRES_PASSWORD"
    export POSTGRESQL_DATABASE="$DEV_POSTGRES_DATABASE"
    export REDIS_URL="redis://:$DEV_REDIS_PASSWORD@localhost:$REDIS_PORT/0"
    export REDIS_HOST=localhost
    export REDIS_PORT=$REDIS_PORT
    export REDIS_PASSWORD="$DEV_REDIS_PASSWORD"
    export DATA_SERVICE_URL=http://localhost:$API_PORT
    export API_HOST=$API_HOST
    export API_PORT=$API_PORT
    export ENVIRONMENT=development
}

ensure_tunnels() {
    echo -e "${YELLOW}Checking tunnel status...${NC}"

    # Check if postgres tunnel is running
    if is_service_running postgres && nc -z localhost $POSTGRES_PORT 2>/dev/null; then
        echo -e "${GREEN}  OK: PostgreSQL tunnel already running${NC}"
    else
        start_tunnel postgres $POSTGRES_PORT 5432 postgresql
    fi

    # Check if redis tunnel is running
    if is_service_running redis && nc -z localhost $REDIS_PORT 2>/dev/null; then
        echo -e "${GREEN}  OK: Redis tunnel already running${NC}"
    else
        start_tunnel redis $REDIS_PORT 6379 redis-service
    fi
}

check_prerequisites() {
    echo -e "${BLUE}Checking prerequisites...${NC}"

    # Check OpenShift connection
    if ! oc whoami >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Not logged into OpenShift. Run 'oc login' first.${NC}"
        exit 1
    fi

    echo -e "${GREEN}OK: Connected to OpenShift as $(oc whoami)${NC}"

    # Check namespace exists and is accessible
    if ! oc get namespace "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Namespace '$NAMESPACE' not found or not accessible${NC}"
        exit 1
    fi

    # Switch to namespace
    if ! oc project "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Cannot switch to namespace '$NAMESPACE'${NC}"
        exit 1
    fi

    echo -e "${GREEN}OK: Connected to namespace: $NAMESPACE${NC}"

    # Check for existing config/.secrets.yaml
    if [ ! -f "config/.secrets.yaml" ]; then
        echo -e "${RED}ERROR: config/.secrets.yaml file not found. Please ensure cloud credentials are configured.${NC}"
        exit 1
    fi

    echo -e "${GREEN}OK: Found config/.secrets.yaml for cloud credentials${NC}"

    # Test OpenShift connection and secrets
    if ! oc get secret postgresql-credentials -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Cannot access postgresql-credentials secret in namespace $NAMESPACE${NC}"
        exit 1
    fi

    if ! oc get secret redis-credentials -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Cannot access redis-credentials secret in namespace $NAMESPACE${NC}"
        exit 1
    fi

    echo -e "${GREEN}OK: All prerequisites satisfied${NC}"
}


start_all() {
    echo -e "${BLUE}Starting all development services...${NC}"

    # Load credentials from OpenShift if needed
    load_credentials

    # Ensure tunnels are running
    ensure_tunnels

    # Start API if not running
    if is_service_running api; then
        if curl -s http://localhost:$API_PORT/api/health/ready > /dev/null 2>&1; then
            echo -e "${GREEN}API already running and healthy${NC}"
        else
            echo -e "${YELLOW}API process exists but not healthy, restarting...${NC}"
            kill_existing_service api
            start_api_process
        fi
    else
        echo -e "${YELLOW}Starting API service...${NC}"
        start_api_process
    fi

    # Start dashboard if not running
    if is_service_running dashboard; then
        if curl -s http://localhost:$DASHBOARD_PORT > /dev/null 2>&1; then
            echo -e "${GREEN}Dashboard already running and healthy${NC}"
        else
            echo -e "${YELLOW}Dashboard process exists but not healthy, restarting...${NC}"
            kill_existing_service dashboard
            start_dashboard_process
        fi
    else
        echo -e "${YELLOW}Starting Dashboard service...${NC}"
        start_dashboard_process
    fi

    echo -e "${GREEN}All services started${NC}"
}

# Helper function to start API without duplicating logic
start_api_process() {
    setup_service_env
    python3 -m uvicorn src.api.data_service:app --host $API_HOST --port $API_PORT > "$TMP_DIR/api.log" 2>&1 &
    echo $! > "$TMP_DIR/api.pid"
    sleep $SERVICE_STARTUP_DELAY
    if curl -s http://localhost:$API_PORT/api/health/ready > /dev/null 2>&1; then
        echo -e "${GREEN}  OK: API service ready at http://localhost:$API_PORT${NC}"
    else
        echo -e "${YELLOW}  INFO: API service starting... (may take a moment)${NC}"
    fi
}

# Helper function to start dashboard without duplicating logic
start_dashboard_process() {
    setup_service_env
    export DASHBOARD_PORT=$DASHBOARD_PORT
    python3 -m src.visualization.dashboard > "$TMP_DIR/dashboard.log" 2>&1 &
    echo $! > "$TMP_DIR/dashboard.pid"
    sleep $SERVICE_STARTUP_DELAY
    if curl -s http://localhost:$DASHBOARD_PORT > /dev/null 2>&1; then
        echo -e "${GREEN}  OK: Dashboard ready at http://localhost:$DASHBOARD_PORT${NC}"
    else
        echo -e "${YELLOW}  INFO: Dashboard starting... (may take a moment)${NC}"
    fi
}

show_status() {
    echo -e "${BLUE}Local Development Status${NC}"
    echo ""

    # Check for required files and environment
    echo -e "${YELLOW}Configuration:${NC}"
    if [ -f "config/.secrets.yaml" ]; then
        echo -e "  config/.secrets.yaml: ${GREEN}OK: Present${NC}"
    else
        echo -e "  config/.secrets.yaml: ${RED}ERROR: Missing${NC}"
    fi

    if [ -n "$DEV_POSTGRES_USER" ] && [ -n "$DEV_POSTGRES_DATABASE" ] && [ -n "$DEV_POSTGRES_PASSWORD" ] && [ -n "$DEV_REDIS_PASSWORD" ]; then
        echo -e "  Environment: ${GREEN}OK: Credentials loaded${NC}"
    else
        echo -e "  Environment: ${YELLOW}INFO: Credentials will load on service start${NC}"
    fi

    echo ""

    # Check tunnels
    echo -e "${YELLOW}Tunnels:${NC}"
    if is_service_running postgres; then
        echo -e "  PostgreSQL: ${GREEN}OK: Running${NC} (localhost:$POSTGRES_PORT)"
    else
        echo -e "  PostgreSQL: ${RED}ERROR: Stopped${NC}"
    fi

    if is_service_running redis; then
        echo -e "  Redis: ${GREEN}OK: Running${NC} (localhost:$REDIS_PORT)"
    else
        echo -e "  Redis: ${RED}ERROR: Stopped${NC}"
    fi

    echo ""
    echo -e "${YELLOW}Services:${NC}"

    # Check API
    if is_service_running api; then
        if curl -s http://localhost:$API_PORT/api/health/ready > /dev/null 2>&1; then
            echo -e "  API: ${GREEN}OK: Running${NC} (http://localhost:$API_PORT)"
        else
            echo -e "  API: ${YELLOW}WARNING:  Process running but not responding${NC}"
        fi
    else
        echo -e "  API: ${RED}ERROR: Stopped${NC}"
    fi

    # Check Dashboard
    if is_service_running dashboard; then
        if curl -s http://localhost:$DASHBOARD_PORT > /dev/null 2>&1; then
            echo -e "  Dashboard: ${GREEN}OK: Running${NC} (http://localhost:$DASHBOARD_PORT)"
        else
            echo -e "  Dashboard: ${YELLOW}WARNING:  Process running but not responding${NC}"
        fi
    else
        echo -e "  Dashboard: ${RED}ERROR: Stopped${NC}"
    fi
}

show_logs() {
    local service=$1
    local log_file="$TMP_DIR/$service.log"

    if [ -f "$log_file" ]; then
        echo -e "${BLUE}Showing logs for $service:${NC}"
        tail -f "$log_file"
    else
        echo -e "${RED}ERROR: No log file found for $service${NC}"
    fi
}

show_recent_logs() {
    local service=$1
    local log_file="$TMP_DIR/$service.log"

    if [ -f "$log_file" ]; then
        tail -n 10 "$log_file"
    else
        echo -e "${RED}No log file found for $service${NC}"
    fi
}

stop_all() {
    echo -e "${YELLOW}Stopping all local services and tunnels...${NC}"

    # Stop services
    for pid_file in "$TMP_DIR"/*.pid; do
        if [ -f "$pid_file" ]; then
            service_name=$(basename "$pid_file" .pid)
            if kill $(cat "$pid_file") 2>/dev/null; then
                echo -e "${GREEN}  OK: Stopped $service_name${NC}"
            else
                echo -e "${YELLOW}  WARNING:  $service_name was not running${NC}"
            fi
            rm -f "$pid_file"
        fi
    done

    # Clean up any remaining port forwards
    pkill -f "oc port-forward.*postgresql" 2>/dev/null || true
    pkill -f "oc port-forward.*redis-service" 2>/dev/null || true

    echo -e "${GREEN}OK: All services stopped${NC}"
}

# Component-specific functions
start_all_tunnels() {
    echo -e "${BLUE}Starting all tunnels...${NC}"
    load_credentials
    ensure_tunnels
}

start_postgres_tunnel() {
    echo -e "${BLUE}Starting PostgreSQL tunnel...${NC}"
    load_credentials
    if is_service_running postgres && nc -z localhost $POSTGRES_PORT 2>/dev/null; then
        echo -e "${GREEN}  OK: PostgreSQL tunnel already running${NC}"
    else
        start_tunnel postgres $POSTGRES_PORT 5432 postgresql
    fi
}

start_redis_tunnel() {
    echo -e "${BLUE}Starting Redis tunnel...${NC}"
    load_credentials
    if is_service_running redis && nc -z localhost $REDIS_PORT 2>/dev/null; then
        echo -e "${GREEN}  OK: Redis tunnel already running${NC}"
    else
        start_tunnel redis $REDIS_PORT 6379 redis-service
    fi
}

stop_all_tunnels() {
    echo -e "${YELLOW}Stopping all tunnels...${NC}"
    kill_existing_service postgres
    kill_existing_service redis
    pkill -f "oc port-forward.*postgresql" 2>/dev/null || true
    pkill -f "oc port-forward.*redis-service" 2>/dev/null || true
    echo -e "${GREEN}OK: All tunnels stopped${NC}"
}

stop_postgres_tunnel() {
    echo -e "${YELLOW}Stopping PostgreSQL tunnel...${NC}"
    kill_existing_service postgres
    pkill -f "oc port-forward.*postgresql" 2>/dev/null || true
    echo -e "${GREEN}OK: PostgreSQL tunnel stopped${NC}"
}

stop_redis_tunnel() {
    echo -e "${YELLOW}Stopping Redis tunnel...${NC}"
    kill_existing_service redis
    pkill -f "oc port-forward.*redis-service" 2>/dev/null || true
    echo -e "${GREEN}OK: Redis tunnel stopped${NC}"
}

restart_all_tunnels() {
    echo -e "${YELLOW}Restarting all tunnels...${NC}"
    stop_all_tunnels
    start_all_tunnels
}

restart_postgres_tunnel() {
    echo -e "${YELLOW}Restarting PostgreSQL tunnel...${NC}"
    stop_postgres_tunnel
    start_postgres_tunnel
}

restart_redis_tunnel() {
    echo -e "${YELLOW}Restarting Redis tunnel...${NC}"
    stop_redis_tunnel
    start_redis_tunnel
}

# Pod management functions
start_postgres_pod() {
    echo -e "${BLUE}Starting PostgreSQL pod...${NC}"
    if ! oc scale statefulset postgresql --replicas=1 -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Failed to start PostgreSQL pod${NC}"
        return 1
    fi
    echo -e "${GREEN}OK: PostgreSQL pod starting${NC}"
}

start_redis_pod() {
    echo -e "${BLUE}Starting Redis pod...${NC}"
    if ! oc scale deployment redis --replicas=1 -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Failed to start Redis pod${NC}"
        return 1
    fi
    echo -e "${GREEN}OK: Redis pod starting${NC}"
}

start_all_pods() {
    echo -e "${BLUE}Starting all database pods...${NC}"
    start_postgres_pod
    start_redis_pod
}

stop_postgres_pod() {
    echo -e "${YELLOW}Stopping PostgreSQL pod...${NC}"
    if ! oc scale statefulset postgresql --replicas=0 -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Failed to stop PostgreSQL pod${NC}"
        return 1
    fi
    echo -e "${GREEN}OK: PostgreSQL pod stopping${NC}"
}

stop_redis_pod() {
    echo -e "${YELLOW}Stopping Redis pod...${NC}"
    if ! oc scale deployment redis --replicas=0 -n "$NAMESPACE" >/dev/null 2>&1; then
        echo -e "${RED}ERROR: Failed to stop Redis pod${NC}"
        return 1
    fi
    echo -e "${GREEN}OK: Redis pod stopping${NC}"
}

stop_all_pods() {
    echo -e "${YELLOW}Stopping all database pods...${NC}"
    stop_postgres_pod
    stop_redis_pod
}

restart_postgres_pod() {
    echo -e "${YELLOW}Restarting PostgreSQL pod...${NC}"
    stop_postgres_pod
    echo "Waiting for pod to terminate..."
    sleep 5
    start_postgres_pod
}

restart_redis_pod() {
    echo -e "${YELLOW}Restarting Redis pod...${NC}"
    stop_redis_pod
    echo "Waiting for pod to terminate..."
    sleep 5
    start_redis_pod
}

restart_all_pods() {
    echo -e "${YELLOW}Restarting all database pods...${NC}"
    stop_all_pods
    echo "Waiting for pods to terminate..."
    sleep 5
    start_all_pods
}

# Redis cache management
clear_redis_cache() {
    echo -e "${BLUE}Clearing Redis cache...${NC}"

    # Load credentials to get Redis password
    load_credentials

    # Get Redis pod name
    local redis_pod=$(oc get pods -n "$NAMESPACE" -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)

    if [ -z "$redis_pod" ]; then
        echo -e "${RED}ERROR: Redis pod not found${NC}"
        return 1
    fi

    # Check if Redis pod is running
    if ! oc get pod "$redis_pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null | grep -q "Running"; then
        echo -e "${RED}ERROR: Redis pod is not running${NC}"
        return 1
    fi

    # Clear the cache using redis-cli directly on the pod with authentication
    if oc exec "$redis_pod" -n "$NAMESPACE" -- redis-cli -a "$DEV_REDIS_PASSWORD" FLUSHALL >/dev/null 2>&1; then
        echo -e "${GREEN}OK: Redis cache cleared${NC}"
    else
        echo -e "${RED}ERROR: Failed to clear Redis cache${NC}"
        return 1
    fi
}

start_api_only() {
    echo -e "${BLUE}Starting API service...${NC}"
    load_credentials
    ensure_tunnels
    kill_existing_service api
    echo -e "${YELLOW}  Using config/.secrets.yaml for cloud credentials${NC}"
    start_api_process
}

stop_api() {
    echo -e "${YELLOW}Stopping API service...${NC}"
    kill_existing_service api
    echo -e "${GREEN}OK: API stopped${NC}"
}

restart_api() {
    echo -e "${YELLOW}Restarting API service...${NC}"
    stop_api
    start_api_only
}

start_dashboard_only() {
    echo -e "${BLUE}Starting Dashboard service...${NC}"
    load_credentials
    ensure_tunnels
    kill_existing_service dashboard
    start_dashboard_process
}

stop_dashboard() {
    echo -e "${YELLOW}Stopping Dashboard service...${NC}"
    kill_existing_service dashboard
    echo -e "${GREEN}OK: Dashboard stopped${NC}"
}

restart_dashboard() {
    echo -e "${YELLOW}Restarting Dashboard service...${NC}"
    stop_dashboard
    start_dashboard_only
}

# Handler functions for actions
handle_start() {
    local component=$1
    case $component in
        api)
            start_api_only
            ;;
        dashboard)
            start_dashboard_only
            ;;
        postgres-tunnel)
            start_postgres_tunnel
            ;;
        redis-tunnel)
            start_redis_tunnel
            ;;
        all-tunnels)
            start_all_tunnels
            ;;
        postgres-pod)
            start_postgres_pod
            ;;
        redis-pod)
            start_redis_pod
            ;;
        all-pods)
            start_all_pods
            ;;
        all)
            start_all
            ;;
        *)
            echo -e "${RED}ERROR: Unknown component '$component'. Use: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, or all-pods${NC}"
            exit 1
            ;;
    esac
}

handle_stop() {
    local component=$1
    case $component in
        api)
            stop_api
            ;;
        dashboard)
            stop_dashboard
            ;;
        postgres-tunnel)
            stop_postgres_tunnel
            ;;
        redis-tunnel)
            stop_redis_tunnel
            ;;
        all-tunnels)
            stop_all_tunnels
            ;;
        postgres-pod)
            stop_postgres_pod
            ;;
        redis-pod)
            stop_redis_pod
            ;;
        all-pods)
            stop_all_pods
            ;;
        all)
            stop_all
            ;;
        *)
            echo -e "${RED}ERROR: Unknown component '$component'. Use: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, or all-pods${NC}"
            exit 1
            ;;
    esac
}

handle_restart() {
    local component=$1
    case $component in
        api)
            restart_api
            ;;
        dashboard)
            restart_dashboard
            ;;
        postgres-tunnel)
            restart_postgres_tunnel
            ;;
        redis-tunnel)
            restart_redis_tunnel
            ;;
        all-tunnels)
            restart_all_tunnels
            ;;
        postgres-pod)
            restart_postgres_pod
            ;;
        redis-pod)
            restart_redis_pod
            ;;
        all-pods)
            restart_all_pods
            ;;
        all)
            stop_all
            sleep 1
            start_all
            ;;
        *)
            echo -e "${RED}ERROR: Unknown component '$component'. Use: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, or all-pods${NC}"
            exit 1
            ;;
    esac
}

handle_status() {
    local component=$1
    case $component in
        api)
            show_api_status
            ;;
        dashboard)
            show_dashboard_status
            ;;
        postgres-tunnel)
            show_postgres_tunnel_status
            ;;
        redis-tunnel)
            show_redis_tunnel_status
            ;;
        all-tunnels)
            show_all_tunnels_status
            ;;
        postgres-pod)
            show_postgres_pod_status
            ;;
        redis-pod)
            show_redis_pod_status
            ;;
        all-pods)
            show_all_pods_status
            ;;
        all)
            show_status
            ;;
        *)
            echo -e "${RED}ERROR: Unknown component '$component'. Use: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, or all-pods${NC}"
            exit 1
            ;;
    esac
}

handle_logs() {
    local component=$1
    case $component in
        api)
            show_logs api
            ;;
        dashboard)
            show_logs dashboard
            ;;
        postgres-tunnel)
            show_postgres_tunnel_logs
            ;;
        redis-tunnel)
            show_redis_tunnel_logs
            ;;
        all-tunnels)
            show_all_tunnel_logs
            ;;
        postgres-pod)
            show_postgres_pod_logs
            ;;
        redis-pod)
            show_redis_pod_logs
            ;;
        all-pods)
            show_all_pod_logs
            ;;
        all)
            show_all_logs
            ;;
        *)
            echo -e "${RED}ERROR: Unknown component '$component'. Use: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, or all-pods${NC}"
            exit 1
            ;;
    esac
}

# Status functions for individual components
show_api_status() {
    echo -e "${BLUE}API Service Status${NC}"
    if is_service_running api; then
        if curl -s http://localhost:$API_PORT/api/health/ready > /dev/null 2>&1; then
            echo -e "API: ${GREEN}OK: Running${NC} (http://localhost:$API_PORT)"
        else
            echo -e "API: ${YELLOW}WARNING: Process running but not responding${NC}"
        fi
    else
        echo -e "API: ${RED}ERROR: Stopped${NC}"
    fi
}

show_dashboard_status() {
    echo -e "${BLUE}Dashboard Service Status${NC}"
    if is_service_running dashboard; then
        if curl -s http://localhost:$DASHBOARD_PORT > /dev/null 2>&1; then
            echo -e "Dashboard: ${GREEN}OK: Running${NC} (http://localhost:$DASHBOARD_PORT)"
        else
            echo -e "Dashboard: ${YELLOW}WARNING: Process running but not responding${NC}"
        fi
    else
        echo -e "Dashboard: ${RED}ERROR: Stopped${NC}"
    fi
}

show_all_tunnels_status() {
    echo -e "${BLUE}All Tunnels Status${NC}"
    if is_service_running postgres; then
        echo -e "PostgreSQL: ${GREEN}OK: Running${NC} (localhost:$POSTGRES_PORT)"
    else
        echo -e "PostgreSQL: ${RED}ERROR: Stopped${NC}"
    fi

    if is_service_running redis; then
        echo -e "Redis: ${GREEN}OK: Running${NC} (localhost:$REDIS_PORT)"
    else
        echo -e "Redis: ${RED}ERROR: Stopped${NC}"
    fi
}

show_postgres_tunnel_status() {
    echo -e "${BLUE}PostgreSQL Tunnel Status${NC}"
    if is_service_running postgres; then
        echo -e "PostgreSQL: ${GREEN}OK: Running${NC} (localhost:$POSTGRES_PORT)"
    else
        echo -e "PostgreSQL: ${RED}ERROR: Stopped${NC}"
    fi
}

show_redis_tunnel_status() {
    echo -e "${BLUE}Redis Tunnel Status${NC}"
    if is_service_running redis; then
        echo -e "Redis: ${GREEN}OK: Running${NC} (localhost:$REDIS_PORT)"
    else
        echo -e "Redis: ${RED}ERROR: Stopped${NC}"
    fi
}

show_postgres_pod_status() {
    echo -e "${BLUE}PostgreSQL Pod Status (OpenShift)${NC}"
    local pod_status=$(oc get pod postgresql-0 -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)
    if [ "$pod_status" = "Running" ]; then
        echo -e "PostgreSQL Pod: ${GREEN}OK: Running${NC}"
    elif [ "$pod_status" = "Pending" ]; then
        echo -e "PostgreSQL Pod: ${YELLOW}WARNING: Starting${NC}"
    elif [ -n "$pod_status" ]; then
        echo -e "PostgreSQL Pod: ${RED}ERROR: $pod_status${NC}"
    else
        echo -e "PostgreSQL Pod: ${RED}ERROR: Not found${NC}"
    fi
}

show_redis_pod_status() {
    echo -e "${BLUE}Redis Pod Status (OpenShift)${NC}"
    local redis_pod=$(oc get pods -n "$NAMESPACE" -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$redis_pod" ]; then
        local pod_status=$(oc get pod "$redis_pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null)
        if [ "$pod_status" = "Running" ]; then
            echo -e "Redis Pod: ${GREEN}OK: Running${NC}"
        elif [ "$pod_status" = "Pending" ]; then
            echo -e "Redis Pod: ${YELLOW}WARNING: Starting${NC}"
        elif [ -n "$pod_status" ]; then
            echo -e "Redis Pod: ${RED}ERROR: $pod_status${NC}"
        else
            echo -e "Redis Pod: ${RED}ERROR: Unknown status${NC}"
        fi
    else
        echo -e "Redis Pod: ${RED}ERROR: Not found${NC}"
    fi
}

show_all_pods_status() {
    echo -e "${BLUE}All Database Pods Status (OpenShift)${NC}"
    show_postgres_pod_status
    echo ""
    show_redis_pod_status
}

show_all_tunnel_logs() {
    echo -e "${BLUE}All Tunnel Logs${NC}"
    echo "PostgreSQL tunnel logs:"
    if [ -f "$TMP_DIR/postgres-tunnel.log" ]; then
        tail -n 10 "$TMP_DIR/postgres-tunnel.log"
    else
        echo -e "${RED}No PostgreSQL log file found${NC}"
    fi
    echo ""
    echo "Redis tunnel logs:"
    if [ -f "$TMP_DIR/redis-tunnel.log" ]; then
        tail -n 10 "$TMP_DIR/redis-tunnel.log"
    else
        echo -e "${RED}No Redis log file found${NC}"
    fi
}

show_postgres_tunnel_logs() {
    echo -e "${BLUE}PostgreSQL Tunnel Logs${NC}"
    if [ -f "$TMP_DIR/postgres-tunnel.log" ]; then
        tail -f "$TMP_DIR/postgres-tunnel.log"
    else
        echo -e "${RED}No PostgreSQL tunnel log file found${NC}"
    fi
}

show_redis_tunnel_logs() {
    echo -e "${BLUE}Redis Tunnel Logs${NC}"
    if [ -f "$TMP_DIR/redis-tunnel.log" ]; then
        tail -f "$TMP_DIR/redis-tunnel.log"
    else
        echo -e "${RED}No Redis tunnel log file found${NC}"
    fi
}

show_postgres_pod_logs() {
    echo -e "${BLUE}PostgreSQL Pod Logs (OpenShift)${NC}"
    if oc get pod postgresql-0 -n "$NAMESPACE" >/dev/null 2>&1; then
        oc logs postgresql-0 -n "$NAMESPACE" --tail=50
    else
        echo -e "${RED}PostgreSQL pod not found${NC}"
    fi
}

show_redis_pod_logs() {
    echo -e "${BLUE}Redis Pod Logs (OpenShift)${NC}"
    local redis_pod=$(oc get pods -n "$NAMESPACE" -l app=redis -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    if [ -n "$redis_pod" ]; then
        oc logs "$redis_pod" -n "$NAMESPACE" --tail=50
    else
        echo -e "${RED}Redis pod not found${NC}"
    fi
}

show_all_pod_logs() {
    echo -e "${BLUE}All Database Pod Logs (OpenShift)${NC}"
    echo "=== PostgreSQL Pod Logs ==="
    show_postgres_pod_logs
    echo ""
    echo "=== Redis Pod Logs ==="
    show_redis_pod_logs
}

show_all_logs() {
    echo -e "${BLUE}All Service Logs${NC}"
    echo "=== API Logs ==="
    show_recent_logs api
    echo ""
    echo "=== Dashboard Logs ==="
    show_recent_logs dashboard
    echo ""
    echo "=== Tunnel Logs ==="
    show_all_tunnel_logs
    echo ""
    echo "=== Database Pod Logs ==="
    show_all_pod_logs
}

# Main command processing
# (ACTION and COMPONENT are already set by the smart parameter parsing above)

# Validate component is provided for actions that need it
if [ "$ACTION" != "help" ] && [ "$ACTION" != "clear-redis-cache" ] && [ -z "$COMPONENT" ]; then
    echo -e "${RED}ERROR: Component required for action '$ACTION'.${NC}"
    echo -e "${YELLOW}Valid components: all, api, dashboard, postgres-tunnel, redis-tunnel, all-tunnels, postgres-pod, redis-pod, all-pods${NC}"
    echo ""
    show_help
    exit 1
fi

# Debug output to show what namespace is being used
if [ "$ACTION" != "help" ]; then
    echo -e "${BLUE}Using namespace: ${GREEN}$NAMESPACE${NC}"
fi

# Commands that need prerequisites check
case $ACTION in
    start|stop|restart|status|logs|clear-redis-cache)
        check_prerequisites
        ;;
esac

case $ACTION in
    start)
        handle_start "$COMPONENT"
        ;;
    stop)
        handle_stop "$COMPONENT"
        ;;
    restart)
        handle_restart "$COMPONENT"
        ;;
    status)
        handle_status "$COMPONENT"
        ;;
    logs)
        handle_logs "$COMPONENT"
        ;;
    clear-redis-cache)
        clear_redis_cache
        ;;
    help|*)
        show_help
        ;;
esac
