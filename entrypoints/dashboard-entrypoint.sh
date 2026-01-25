#!/bin/bash
set -e

echo "Starting Cost Dashboard Service..."
echo "Environment: ${ENVIRONMENT:-production}"
echo "Data Service URL: ${DATA_SERVICE_URL:-not set}"

# === PROCESS MANAGEMENT FOR RACE CONDITION PREVENTION ===
PIDFILE="/tmp/dashboard.pid"
LOCKFILE="/tmp/dashboard.lock"

# Function to cleanup on exit
cleanup() {
    echo "🧹 Cleaning up dashboard process..."
    rm -f "$PIDFILE" "$LOCKFILE"
    # Kill any orphaned dashboard processes
    pkill -f "python.*dashboard" 2>/dev/null || true
    echo "✅ Cleanup completed"
}

# Set trap for clean shutdown
trap cleanup EXIT INT TERM

# Check for existing dashboard processes and clean them up
echo "🔍 Checking for existing dashboard processes..."
EXISTING_PIDS=$(pgrep -f "python.*dashboard" 2>/dev/null || echo "")
if [ -n "$EXISTING_PIDS" ]; then
    echo "⚠️  Found existing dashboard processes: $EXISTING_PIDS"
    echo "🔄 Terminating existing processes..."
    echo "$EXISTING_PIDS" | xargs kill -TERM 2>/dev/null || true
    sleep 3
    # Force kill if still running
    echo "$EXISTING_PIDS" | xargs kill -KILL 2>/dev/null || true
    echo "✅ Existing processes terminated"
fi

# Create lock file to prevent concurrent starts
if [ -f "$LOCKFILE" ]; then
    LOCK_PID=$(cat "$LOCKFILE" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && kill -0 "$LOCK_PID" 2>/dev/null; then
        echo "❌ Dashboard startup already in progress (PID: $LOCK_PID)"
        echo "   If this is an error, remove: $LOCKFILE"
        exit 1
    else
        echo "🗑️  Removing stale lock file"
        rm -f "$LOCKFILE"
    fi
fi

# Create lock file with our PID
echo $$ > "$LOCKFILE"
echo "🔒 Created startup lock (PID: $$)"

# Ensure virtual environment is first in PATH
export PATH="/opt/app-root/venv/bin:$PATH"

# Construct REDIS_URL from individual environment variables with URL encoding
if [ -n "${REDIS_PASSWORD}" ]; then
    ENCODED_REDIS_PASSWORD=$(python -c "import urllib.parse; print(urllib.parse.quote('${REDIS_PASSWORD}', safe=''))")
    export REDIS_URL="redis://:${ENCODED_REDIS_PASSWORD}@redis-service:6379/0"
    echo "Redis URL configured with authentication"
fi

# Debug Python environment
echo "Python version: $(python --version)"
echo "Python executable: $(which python)"
echo "PATH: $PATH"
echo "Checking for requests module..."
python -c "import sys; print('Python path:', sys.path)"

# Wait for Data Service to be ready using Python
echo "Waiting for Data Service..."
python -c "
import requests
import time
import os
import sys

data_service_url = os.getenv('DATA_SERVICE_URL', 'http://cost-data-service:8000')
print(f'Checking data service at: {data_service_url}')

for i in range(60):  # Try for 2 minutes
    try:
        response = requests.get(f'{data_service_url}/api/health/ready', timeout=5)
        if response.status_code == 200:
            print('Data Service is ready!')
            break
    except:
        pass
    print('Data Service is unavailable - sleeping')
    time.sleep(2)
else:
    print('Data Service connection timeout')
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "Data Service not available"
    exit 1
fi

# Start the dashboard
echo "🚀 Starting Dashboard server with process protection..."

# Verify Python environment before starting
echo "🐍 Python verification:"
echo "  Executable: $(which python)"
echo "  Version: $(python --version)"

# Test Redis module import before starting
echo "🔗 Redis connectivity test:"
python -c "
import sys
try:
    import redis
    print('✅ Redis module available')
    print(f'   Version: {redis.__version__}')
    print(f'   Location: {redis.__file__}')
except ImportError as e:
    print(f'❌ Redis module import failed: {e}')
    print('   Available modules:')
    import pkg_resources
    for pkg in sorted(pkg_resources.working_set, key=lambda x: x.project_name.lower()):
        if 'redis' in pkg.project_name.lower():
            print(f'     {pkg.project_name}: {pkg.version}')
    sys.exit(1)
"

# Final process check before exec
FINAL_CHECK=$(pgrep -f "python.*dashboard" 2>/dev/null | wc -l)
if [ "$FINAL_CHECK" -gt 0 ]; then
    echo "❌ Dashboard processes still detected before start: $FINAL_CHECK"
    echo "🔄 Force cleaning..."
    pkill -9 -f "python.*dashboard" 2>/dev/null || true
    sleep 2
fi

# Record our PID for monitoring
echo $$ > "$PIDFILE"
echo "📝 Dashboard PID recorded: $$"

# Remove startup lock before exec (keeps PID file for monitoring)
rm -f "$LOCKFILE"

# Execute the dashboard with clean environment
echo "🎯 Executing dashboard: $@"
exec "$@"
