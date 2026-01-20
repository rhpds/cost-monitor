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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global connections
db_pool = None
redis_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management"""
    global db_pool, redis_client
    
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
        
        # Query database
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
