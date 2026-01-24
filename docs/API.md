# API Reference

The FastAPI backend provides RESTful endpoints for programmatic access to cost data.

## Base URL

- Local development: `http://localhost:8000`
- OpenShift deployment: `https://your-route-url`

## Health Check Endpoints

### Service Readiness Check
```http
GET /api/health/ready
```

Returns HTTP 200 when the service is ready to serve requests.

**Response:**
```json
{
  "status": "ready",
  "timestamp": "2025-01-24T10:00:00Z",
  "database": "connected",
  "cache": "connected"
}
```

### Service Liveness Check
```http
GET /api/health/live
```

Returns HTTP 200 when the service is running.

**Response:**
```json
{
  "status": "alive",
  "timestamp": "2025-01-24T10:00:00Z"
}
```

## Cost Data Endpoints

### Cost Summary
```http
GET /api/v1/costs/summary
```

Get aggregated cost summary across all enabled providers.

**Query Parameters:**
- `start_date` (string, optional): Start date in YYYY-MM-DD format
- `end_date` (string, optional): End date in YYYY-MM-DD format
- `provider` (string, optional): Filter by provider (aws/azure/gcp)
- `force_refresh` (boolean, optional): Bypass cache and fetch fresh data

**Example Response:**
```json
{
  "total_cost": 15432.50,
  "currency": "USD",
  "period": {
    "start_date": "2025-01-01",
    "end_date": "2025-01-24"
  },
  "breakdown": {
    "aws": {
      "total": 8500.25,
      "percentage": 55.1
    },
    "azure": {
      "total": 4200.15,
      "percentage": 27.2
    },
    "gcp": {
      "total": 2732.10,
      "percentage": 17.7
    }
  },
  "top_services": [
    {
      "service": "Amazon EC2",
      "provider": "aws",
      "cost": 3200.50,
      "percentage": 20.7
    }
  ]
}
```

### Daily Cost Trends
```http
GET /api/v1/costs/daily
```

Get daily cost trends with provider breakdown.

**Query Parameters:**
- `start_date` (string, optional): Start date in YYYY-MM-DD format
- `end_date` (string, optional): End date in YYYY-MM-DD format
- `provider` (string, optional): Filter by provider (aws/azure/gcp)
- `granularity` (string, optional): Data granularity (daily/monthly)

**Example Response:**
```json
{
  "data": [
    {
      "date": "2025-01-23",
      "total": 687.45,
      "aws": 425.30,
      "azure": 180.15,
      "gcp": 82.00
    },
    {
      "date": "2025-01-24",
      "total": 712.80,
      "aws": 445.20,
      "azure": 185.30,
      "gcp": 82.30
    }
  ],
  "summary": {
    "total_cost": 1400.25,
    "average_daily": 700.13,
    "period_days": 2
  }
}
```

### Service-Level Breakdown
```http
GET /api/v1/costs/services
```

Get cost breakdown by cloud services.

**Query Parameters:**
- `start_date` (string, optional): Start date in YYYY-MM-DD format
- `end_date` (string, optional): End date in YYYY-MM-DD format
- `provider` (string, optional): Filter by provider (aws/azure/gcp)
- `limit` (integer, optional): Limit number of services returned (default: 50)

**Example Response:**
```json
{
  "services": [
    {
      "service": "Amazon EC2",
      "provider": "aws",
      "cost": 3200.50,
      "percentage": 20.7,
      "trend": "increasing"
    },
    {
      "service": "Azure Virtual Machines",
      "provider": "azure",
      "cost": 2100.25,
      "percentage": 13.6,
      "trend": "stable"
    }
  ],
  "total_services": 45,
  "total_cost": 15432.50
}
```

### Account/Project Breakdown
```http
GET /api/v1/costs/accounts
```

Get cost breakdown by accounts (AWS), subscriptions (Azure), or projects (GCP).

**Query Parameters:**
- `start_date` (string, optional): Start date in YYYY-MM-DD format
- `end_date` (string, optional): End date in YYYY-MM-DD format
- `provider` (string, optional): Filter by provider (aws/azure/gcp)
- `limit` (integer, optional): Limit number of accounts returned (default: 50)

**Example Response:**
```json
{
  "accounts": [
    {
      "account_id": "123456789012",
      "account_name": "Production",
      "provider": "aws",
      "cost": 8500.25,
      "percentage": 55.1
    },
    {
      "subscription_id": "12345678-1234-1234-1234-123456789012",
      "subscription_name": "Production Subscription",
      "provider": "azure",
      "cost": 4200.15,
      "percentage": 27.2
    }
  ],
  "total_accounts": 12,
  "total_cost": 15432.50
}
```

## Error Responses

All endpoints may return the following error responses:

### 400 Bad Request
```json
{
  "error": "Bad Request",
  "message": "Invalid date format. Use YYYY-MM-DD.",
  "details": {
    "field": "start_date",
    "value": "2025/01/24"
  }
}
```

### 401 Unauthorized
```json
{
  "error": "Unauthorized",
  "message": "Authentication required"
}
```

### 500 Internal Server Error
```json
{
  "error": "Internal Server Error",
  "message": "Failed to retrieve cost data",
  "details": "AWS API connection timeout"
}
```

## Example Usage

### Using curl

```bash
# Get cost summary for last 7 days
curl "http://localhost:8000/api/v1/costs/summary?start_date=2025-01-17&end_date=2025-01-24"

# Get AWS-only costs with fresh data
curl "http://localhost:8000/api/v1/costs/summary?provider=aws&force_refresh=true"

# Get daily trends for January
curl "http://localhost:8000/api/v1/costs/daily?start_date=2025-01-01&end_date=2025-01-31"

# Get top 10 services by cost
curl "http://localhost:8000/api/v1/costs/services?limit=10"
```

### Using Python

```python
import requests

# Get cost summary
response = requests.get("http://localhost:8000/api/v1/costs/summary",
                       params={"start_date": "2025-01-01",
                              "end_date": "2025-01-24"})
data = response.json()
print(f"Total cost: ${data['total_cost']:.2f}")

# Get daily trends
response = requests.get("http://localhost:8000/api/v1/costs/daily")
trends = response.json()
for day in trends['data']:
    print(f"{day['date']}: ${day['total']:.2f}")
```

### Using JavaScript

```javascript
// Get cost summary
async function getCostSummary() {
    const response = await fetch('/api/v1/costs/summary');
    const data = await response.json();
    console.log(`Total cost: $${data.total_cost}`);
}

// Get service breakdown
async function getServiceBreakdown() {
    const response = await fetch('/api/v1/costs/services?limit=10');
    const data = await response.json();
    data.services.forEach(service => {
        console.log(`${service.service}: $${service.cost}`);
    });
}
```

## Rate Limiting

The API implements rate limiting to prevent abuse:

- **Rate Limit**: 100 requests per minute per client
- **Headers**: Response includes rate limit headers:
  - `X-RateLimit-Limit`: Request limit per window
  - `X-RateLimit-Remaining`: Remaining requests in window
  - `X-RateLimit-Reset`: Timestamp when window resets

## Authentication

When deployed with OAuth proxy (OpenShift), authentication is handled automatically. For direct API access, authentication tokens may be required depending on your deployment configuration.