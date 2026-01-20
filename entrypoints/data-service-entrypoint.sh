#!/bin/bash
set -e

echo "Starting Cost Data Service..."
echo "Environment: ${ENVIRONMENT:-production}"

# Ensure virtual environment is first in PATH
export PATH="/opt/app-root/venv/bin:$PATH"

# Construct DATABASE_URL from individual environment variables
export DATABASE_URL="postgresql://${POSTGRESQL_USER}:${POSTGRESQL_PASSWORD}@postgresql:5432/${POSTGRESQL_DATABASE}"
export REDIS_URL="redis://:${REDIS_PASSWORD}@redis-service:6379/0"

echo "Database URL: ${DATABASE_URL}"
echo "Redis URL: ${REDIS_URL}"

# Debug Python environment
echo "Python version: $(python --version)"
echo "Python executable: $(which python)"
echo "PATH: $PATH"
echo "Checking for asyncpg module..."
python -c "import sys; print('Python path:', sys.path)"

# Wait for PostgreSQL to be ready using Python
echo "Waiting for PostgreSQL..."
python -c "
import time
import asyncpg
import asyncio
import os
import sys

async def check_postgres():
    database_url = os.getenv('DATABASE_URL', 'postgresql://cost_monitor:password@postgresql:5432/cost_monitor')
    for i in range(60):  # Try for 2 minutes
        try:
            conn = await asyncpg.connect(database_url)
            await conn.close()
            print('PostgreSQL is ready!')
            return True
        except:
            print('PostgreSQL is unavailable - sleeping')
            await asyncio.sleep(2)
    print('PostgreSQL connection timeout')
    return False

async def check_redis():
    import redis.asyncio as redis
    redis_url = os.getenv('REDIS_URL', 'redis://redis-service:6379/0')
    for i in range(30):  # Try for 1 minute
        try:
            client = redis.from_url(redis_url)
            await client.ping()
            await client.close()
            print('Redis is ready!')
            return True
        except:
            print('Redis is unavailable - sleeping')
            await asyncio.sleep(2)
    print('Redis connection timeout')
    return False

async def main():
    postgres_ok = await check_postgres()
    if not postgres_ok:
        sys.exit(1)

    redis_ok = await check_redis()
    if not redis_ok:
        sys.exit(1)

asyncio.run(main())
"

if [ $? -ne 0 ]; then
    echo "Service dependencies not available"
    exit 1
fi

# Run database migrations if needed (skip for now - we'll use init scripts)
echo "Skipping migrations (using init scripts)..."

# Start the application
echo "Starting FastAPI server..."
exec "$@"