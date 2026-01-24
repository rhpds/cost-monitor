#!/bin/bash
set -e

echo "Starting Cost Dashboard Service..."
echo "Environment: ${ENVIRONMENT:-production}"
echo "Data Service URL: ${DATA_SERVICE_URL:-not set}"

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
echo "Starting Dashboard server..."
exec "$@"