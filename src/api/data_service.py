#!/usr/bin/env python3
"""
Cost Data Service - FastAPI Backend
Provides REST API for cost data collection and retrieval
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
import asyncpg
import redis.asyncio as redis
from pydantic import BaseModel

# Import provider system for on-demand data collection
from ..providers.base import ProviderFactory, TimeGranularity, CostDataPoint as ProviderCostDataPoint
from ..utils.auth import MultiCloudAuthManager
from ..config.settings import get_config
# Import provider implementations to register them
from .. import providers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global connections
db_pool = None
redis_client = None
auth_manager = None
config = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global db_pool, redis_client, auth_manager, config

    # Startup
    logger.info("Starting Cost Data Service...")

    # Database connection
    database_url = os.getenv('DATABASE_URL', 'postgresql://cost_monitor:password@postgresql:5432/cost_monitor')
    logger.info("Connecting to database...")
    db_pool = await asyncpg.create_pool(database_url, min_size=5, max_size=20)

    # Redis connection
    redis_url = os.getenv('REDIS_URL', 'redis://redis-service:6379/0')
    logger.info("Connecting to Redis...")
    redis_client = redis.from_url(redis_url, decode_responses=True)

    # Initialize provider system for data collection
    logger.info("Initializing provider system...")
    auth_manager = MultiCloudAuthManager()
    config = get_config()  # Load provider configurations

    logger.info("✅ Cost Data Service started successfully")
    yield
    
    # Shutdown
    logger.info("Shutting down Cost Data Service...")
    if db_pool:
        await db_pool.close()
    if redis_client:
        await redis_client.close()

# FastAPI app
app = FastAPI(
    title="Cost Data Service",
    version="1.0.0",
    description="Backend API for multi-cloud cost monitoring",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic models
class HealthCheck(BaseModel):
    status: str
    timestamp: datetime
    version: str

class CostSummary(BaseModel):
    total_cost: float
    currency: str
    period_start: date
    period_end: date
    provider_breakdown: Dict[str, float]

class CostDataPoint(BaseModel):
    provider: str
    date: date
    cost: float
    currency: str
    service_name: Optional[str] = None
    account_id: Optional[str] = None
    region: Optional[str] = None

# Data collection functions
async def check_existing_data(start_date: date, end_date: date, provider_name: str = None) -> Dict[str, List[date]]:
    """Check what data already exists in database for the given date range"""
    async with db_pool.acquire() as conn:
        query = """
            SELECT p.name as provider, cdp.date
            FROM cost_data_points cdp
            JOIN providers p ON cdp.provider_id = p.id
            WHERE cdp.date BETWEEN $1 AND $2
        """
        params = [start_date, end_date]

        if provider_name:
            query += " AND p.name = $3"
            params.append(provider_name)

        query += " ORDER BY p.name, cdp.date"

        rows = await conn.fetch(query, *params)

        # Group existing dates by provider
        existing_data = {}
        for row in rows:
            provider = row['provider']
            if provider not in existing_data:
                existing_data[provider] = []
            existing_data[provider].append(row['date'])

        return existing_data

async def get_missing_date_ranges(start_date: date, end_date: date, existing_data: Dict[str, List[date]], providers: List[str]) -> Dict[str, List[tuple]]:
    """Identify missing date ranges that need to be collected"""
    missing_ranges = {}

    # Generate all dates in the requested range
    current_date = start_date
    all_dates = []
    while current_date <= end_date:
        all_dates.append(current_date)
        current_date += timedelta(days=1)

    for provider in providers:
        existing_dates = set(existing_data.get(provider, []))
        missing_dates = [d for d in all_dates if d not in existing_dates]

        if missing_dates:
            # Group consecutive missing dates into ranges
            ranges = []
            range_start = missing_dates[0]
            range_end = missing_dates[0]

            for i in range(1, len(missing_dates)):
                if missing_dates[i] == range_end + timedelta(days=1):
                    range_end = missing_dates[i]
                else:
                    ranges.append((range_start, range_end))
                    range_start = missing_dates[i]
                    range_end = missing_dates[i]

            ranges.append((range_start, range_end))
            missing_ranges[provider] = ranges

    return missing_ranges

async def collect_provider_data(provider_name: str, start_date: date, end_date: date) -> List[ProviderCostDataPoint]:
    """Collect cost data from a specific provider for the given date range"""
    try:
        # Get provider configuration from dynaconf config system
        provider_config = config.get_provider_config(provider_name)

        # Ensure we have valid configuration
        if not provider_config:
            raise ValueError(f"No configuration found for provider '{provider_name}'")

        logger.info(f"Using configuration for provider {provider_name}: {list(provider_config.keys())}")

        # Create provider instance
        provider_instance = ProviderFactory.create_provider(provider_name, provider_config)

        # Authenticate
        auth_result = await auth_manager.authenticate_provider(provider_name, provider_config)
        if not auth_result.success:
            logger.error(f"Failed to authenticate with {provider_name}: {auth_result.error}")
            return []

        # Get cost data
        logger.info(f"Collecting {provider_name} data for {start_date} to {end_date}")
        cost_summary = await provider_instance.get_cost_data(
            start_date, end_date, TimeGranularity.DAILY
        )

        return cost_summary.data_points

    except Exception as e:
        logger.error(f"Error collecting data from {provider_name}: {e}")
        return []

async def store_cost_data(provider_name: str, cost_points: List[ProviderCostDataPoint]):
    """Store collected cost data in the database"""
    if not cost_points:
        return

    async with db_pool.acquire() as conn:
        # Get provider ID
        provider_row = await conn.fetchrow("SELECT id FROM providers WHERE name = $1", provider_name)
        if not provider_row:
            logger.error(f"Provider {provider_name} not found in database")
            return

        provider_id = provider_row['id']

        # Insert cost data points
        insert_query = """
            INSERT INTO cost_data_points
            (provider_id, date, granularity, cost, currency, service_name, account_id, region)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (provider_id, date, service_name, account_id, region)
            DO UPDATE SET granularity = EXCLUDED.granularity, cost = EXCLUDED.cost, currency = EXCLUDED.currency
        """

        for point in cost_points:
            point_date = point.date if isinstance(point.date, date) else point.date.date()
            await conn.execute(
                insert_query,
                provider_id,
                point_date,
                'DAILY',  # Set granularity to DAILY for cost data collection
                point.amount,
                point.currency,
                point.service_name,
                point.account_id,
                point.region
            )

        logger.info(f"Stored {len(cost_points)} data points for {provider_name}")

async def update_provider_sync_status(provider_name: str, status: str, last_sync: datetime):
    """Update provider sync status in database"""
    async with db_pool.acquire() as conn:
        await conn.execute(
            "UPDATE providers SET sync_status = $1, last_sync_at = $2 WHERE name = $3",
            status, last_sync, provider_name
        )

async def collect_missing_data(start_date: date, end_date: date, providers: List[str] = None):
    """Main function to collect missing data for the requested date range"""
    if not providers:
        providers = ['aws', 'azure', 'gcp']  # Default to all providers

    # Check what data already exists
    existing_data = await check_existing_data(start_date, end_date)

    # Find missing date ranges
    missing_ranges = await get_missing_date_ranges(start_date, end_date, existing_data, providers)

    if not missing_ranges:
        logger.info(f"No missing data for {start_date} to {end_date}")
        return

    # Collect missing data for each provider
    for provider_name, ranges in missing_ranges.items():
        for range_start, range_end in ranges:
            logger.info(f"Collecting missing {provider_name} data for {range_start} to {range_end}")

            # Collect data from provider
            cost_points = await collect_provider_data(provider_name, range_start, range_end)

            # Store in database
            await store_cost_data(provider_name, cost_points)

            # Update sync status
            await update_provider_sync_status(provider_name, "success", datetime.now())

# Health endpoints
@app.get("/api/health/ready", response_model=HealthCheck)
async def health_ready():
    """Readiness probe"""
    try:
        # Test database connection
        async with db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        
        # Test Redis connection
        await redis_client.ping()
        
        return HealthCheck(
            status="ready",
            timestamp=datetime.now(),
            version="1.0.0"
        )
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail="Service not ready")

@app.get("/api/health/live", response_model=HealthCheck)
async def health_live():
    """Liveness probe"""
    return HealthCheck(
        status="alive",
        timestamp=datetime.now(),
        version="1.0.0"
    )

@app.get("/api/health/db")
async def health_db():
    """Database health check"""
    try:
        async with db_pool.acquire() as conn:
            result = await conn.fetchval("SELECT COUNT(*) FROM providers")
            return {"status": "healthy", "providers_count": result}
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=503, detail="Database not available")

@app.get("/api/health/redis")
async def health_redis():
    """Redis health check"""
    try:
        await redis_client.ping()
        info = await redis_client.info('memory')
        return {
            "status": "healthy", 
            "memory_used": info.get('used_memory_human', 'unknown')
        }
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")
        raise HTTPException(status_code=503, detail="Redis not available")

# Cost data endpoints
@app.get("/api/v1/costs/summary", response_model=CostSummary)
async def get_cost_summary(
    start_date: Optional[date] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[date] = Query(None, description="End date (YYYY-MM-DD)"),
    providers: Optional[List[str]] = Query(None, description="Filter by providers")
):
    """Get cost summary for specified period"""
    try:
        # Default to last 30 days if no dates provided
        if not end_date:
            end_date = date.today()
        if not start_date:
            start_date = end_date - timedelta(days=30)
        
        # Cache key
        cache_key = f"cost_summary:{start_date}:{end_date}:{','.join(providers or [])}"
        
        # Try cache first
        cached = await redis_client.get(cache_key)
        if cached:
            import json
            return json.loads(cached)

        # Check for missing data and collect if needed
        logger.info(f"Checking for missing data: {start_date} to {end_date}")

        # Get list of enabled providers to check
        providers_to_check = providers if providers else ['aws', 'azure', 'gcp']

        # Check existing data
        existing_data = await check_existing_data(start_date, end_date)

        # Find missing date ranges
        missing_ranges = await get_missing_date_ranges(start_date, end_date, existing_data, providers_to_check)

        # Collect missing data if needed
        if missing_ranges:
            logger.info(f"Found missing data ranges: {missing_ranges}")
            await collect_missing_data(start_date, end_date, providers_to_check)
        else:
            logger.info("No missing data found")

        # Query database for complete data
        async with db_pool.acquire() as conn:
            # Get total cost
            query = """
                SELECT p.name as provider, SUM(cdp.cost) as total_cost, cdp.currency
                FROM cost_data_points cdp
                JOIN providers p ON cdp.provider_id = p.id
                WHERE cdp.date BETWEEN $1 AND $2
            """
            
            params = [start_date, end_date]
            
            if providers:
                query += " AND p.name = ANY($3)"
                params.append(providers)
                
            query += " GROUP BY p.name, cdp.currency ORDER BY total_cost DESC"
            
            rows = await conn.fetch(query, *params)
            
            # Build response
            total_cost = sum(row['total_cost'] for row in rows)
            provider_breakdown = {row['provider']: float(row['total_cost']) for row in rows}
            currency = rows[0]['currency'] if rows else 'USD'
            
            result = CostSummary(
                total_cost=total_cost,
                currency=currency,
                period_start=start_date,
                period_end=end_date,
                provider_breakdown=provider_breakdown
            )
            
            # Cache for 30 minutes
            import json
            await redis_client.setex(cache_key, 1800, json.dumps(result.dict(), default=str))
            
            return result
            
    except Exception as e:
        logger.error(f"Error getting cost summary: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving cost data")

@app.get("/api/v1/costs")
async def get_costs(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    providers: Optional[List[str]] = Query(None),
    limit: int = Query(100, ge=1, le=1000)
):
    """Get detailed cost data points"""
    try:
        async with db_pool.acquire() as conn:
            query = """
                SELECT p.name as provider, cdp.date, cdp.cost, cdp.currency,
                       cdp.service_name, cdp.account_id, cdp.region
                FROM cost_data_points cdp
                JOIN providers p ON cdp.provider_id = p.id
                WHERE 1=1
            """
            
            params = []
            param_count = 0
            
            if start_date:
                param_count += 1
                query += f" AND cdp.date >= ${param_count}"
                params.append(start_date)
                
            if end_date:
                param_count += 1
                query += f" AND cdp.date <= ${param_count}"
                params.append(end_date)
                
            if providers:
                param_count += 1
                query += f" AND p.name = ANY(${param_count})"
                params.append(providers)
                
            query += f" ORDER BY cdp.date DESC LIMIT ${param_count + 1}"
            params.append(limit)
            
            rows = await conn.fetch(query, *params)
            
            return [
                CostDataPoint(
                    provider=row['provider'],
                    date=row['date'],
                    cost=float(row['cost']),
                    currency=row['currency'],
                    service_name=row['service_name'],
                    account_id=row['account_id'],
                    region=row['region']
                )
                for row in rows
            ]
            
    except Exception as e:
        logger.error(f"Error getting costs: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving cost data")

@app.get("/api/v1/providers")
async def get_providers():
    """Get list of available providers"""
    try:
        async with db_pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT name, display_name, is_enabled, last_sync_at, sync_status
                FROM providers
                ORDER BY name
            """)
            
            return [
                {
                    "name": row['name'],
                    "display_name": row['display_name'],
                    "is_enabled": row['is_enabled'],
                    "last_sync_at": row['last_sync_at'],
                    "sync_status": row['sync_status']
                }
                for row in rows
            ]
            
    except Exception as e:
        logger.error(f"Error getting providers: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving providers")

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": "Cost Data Service",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/api/health/ready",
            "costs": "/api/v1/costs",
            "summary": "/api/v1/costs/summary",
            "providers": "/api/v1/providers",
            "docs": "/docs"
        }
    }

if __name__ == "__main__":
    uvicorn.run(
        "data_service:app",
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
