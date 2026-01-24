# Troubleshooting Guide

This guide covers common issues and solutions for the Multi-Cloud Cost Monitor.

## Quick Diagnostics

### Health Checks

```bash
# Check API service health
curl http://localhost:8000/api/health/ready

# Test authentication
python -m src.main test-auth

# Verify configuration
python -m src.main --config config/config.local.yaml costs --dry-run
```

### Service Status

```bash
# OpenShift deployment
oc get pods -l app=cost-monitor
oc logs deployment/cost-monitor-api
oc logs deployment/cost-monitor-dashboard

# Docker Compose
docker-compose ps
docker-compose logs api
docker-compose logs dashboard

# Local development
ps aux | grep "python.*src.main"
```

## Authentication Issues

### AWS Authentication Errors

**Problem:** AWS credentials not working

**Symptoms:**
```
ClientError: An error occurred (InvalidUserID.NotFound) when calling the GetCostAndUsage operation
NoCredentialsError: Unable to locate credentials
```

**Solutions:**

1. **Check credentials:**
   ```bash
   aws sts get-caller-identity
   echo $AWS_ACCESS_KEY_ID
   echo $AWS_SECRET_ACCESS_KEY
   ```

2. **Verify IAM permissions:**
   ```bash
   # Test Cost Explorer access
   aws ce get-cost-and-usage --time-period Start=2025-01-01,End=2025-01-02 --granularity=DAILY --metrics=BlendedCost
   ```

3. **Check region configuration:**
   ```yaml
   clouds:
     aws:
       region: us-east-1  # Cost Explorer requires us-east-1
   ```

4. **IAM policy requirements:**
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "ce:GetCostAndUsage",
           "ce:GetUsageReport",
           "organizations:ListAccounts"
         ],
         "Resource": "*"
       }
     ]
   }
   ```

### Azure Authentication Errors

**Problem:** Azure service principal authentication failing

**Symptoms:**
```
AuthenticationError: Authentication failed
ClientAuthenticationError: The credentials in ServicePrincipalCredentials are not valid
```

**Solutions:**

1. **Verify service principal:**
   ```bash
   az login --service-principal -u $AZURE_CLIENT_ID -p $AZURE_CLIENT_SECRET --tenant $AZURE_TENANT_ID
   az account show
   ```

2. **Check required permissions:**
   ```bash
   # Verify billing reader role
   az role assignment list --assignee $AZURE_CLIENT_ID --all
   ```

3. **Test storage access:**
   ```bash
   az storage blob list --account-name your-billing-account --container-name cost-exports
   ```

### GCP Authentication Errors

**Problem:** GCP service account authentication failing

**Symptoms:**
```
DefaultCredentialsError: Could not automatically determine credentials
PermissionDenied: The caller does not have permission
```

**Solutions:**

1. **Check service account key:**
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   gcloud auth activate-service-account --key-file=$GOOGLE_APPLICATION_CREDENTIALS
   ```

2. **Verify BigQuery permissions:**
   ```bash
   bq query --use_legacy_sql=false "SELECT * FROM billing_export.gcp_billing_export_v1_XXXXX LIMIT 1"
   ```

3. **Test billing account access:**
   ```bash
   gcloud beta billing accounts list
   ```

## Database Connection Issues

### PostgreSQL Connection Errors

**Problem:** Cannot connect to PostgreSQL database

**Symptoms:**
```
psycopg2.OperationalError: could not connect to server
FATAL: database "cost_monitor" does not exist
```

**Solutions:**

1. **Check PostgreSQL service:**
   ```bash
   # Local
   pg_isready -h localhost -p 5432

   # Docker
   docker-compose ps postgresql

   # OpenShift
   oc get pods -l app=postgresql
   ```

2. **Verify database exists:**
   ```bash
   psql -h localhost -p 5432 -U postgres -l
   createdb cost_monitor
   ```

3. **Check connection string:**
   ```bash
   # Test connection
   psql "postgresql://username:password@localhost:5432/cost_monitor"
   ```

4. **Initialize database schema:**
   ```bash
   psql cost_monitor < database/add_aws_accounts_table.sql
   ```

### Database Performance Issues

**Problem:** Slow database queries

**Solutions:**

1. **Check database size:**
   ```sql
   SELECT pg_size_pretty(pg_database_size('cost_monitor'));
   ```

2. **Analyze slow queries:**
   ```sql
   SELECT query, mean_time, calls
   FROM pg_stat_statements
   ORDER BY mean_time DESC
   LIMIT 10;
   ```

3. **Add indexes:**
   ```sql
   CREATE INDEX idx_cost_data_date ON cost_data(date);
   CREATE INDEX idx_cost_data_provider ON cost_data(provider);
   ```

## Cache Issues

### Redis Connection Problems

**Problem:** Cannot connect to Redis cache

**Symptoms:**
```
redis.exceptions.ConnectionError: Error connecting to Redis
ConnectionRefusedError: [Errno 111] Connection refused
```

**Solutions:**

1. **Check Redis service:**
   ```bash
   # Local
   redis-cli ping

   # Docker
   docker-compose ps redis

   # OpenShift
   oc get pods -l app=redis
   ```

2. **Test connection:**
   ```bash
   redis-cli -u redis://localhost:6379 ping
   ```

3. **Check Redis configuration:**
   ```bash
   redis-cli config get "*"
   redis-cli info memory
   ```

### Cache Performance Issues

**Problem:** Poor cache performance or frequent misses

**Solutions:**

1. **Monitor cache statistics:**
   ```bash
   redis-cli info stats
   ```

2. **Check cache key patterns:**
   ```bash
   redis-cli keys "cost_monitor:*"
   ```

3. **Adjust TTL settings:**
   ```yaml
   cache:
     aws:
       ttl: 3600  # Increase for slower-changing data
     azure:
       ttl: 7200  # Azure updates less frequently
   ```

4. **Clear corrupted cache:**
   ```bash
   redis-cli flushall
   ```

## Dashboard Issues

### Dashboard Not Loading

**Problem:** Dashboard page doesn't load or shows errors

**Solutions:**

1. **Check API backend:**
   ```bash
   curl http://localhost:8000/api/health/ready
   ```

2. **Verify Dash service:**
   ```bash
   # Local
   netstat -tlnp | grep 8050

   # Check logs
   python -m src.main dashboard --debug
   ```

3. **Clear browser cache:**
   - Hard refresh: `Ctrl+F5`
   - Clear cookies and cache
   - Try incognito/private mode

4. **Check JavaScript console:**
   - Open browser developer tools (F12)
   - Look for JavaScript errors
   - Check network tab for failed requests

### Charts Not Displaying Data

**Problem:** Dashboard loads but charts are empty

**Solutions:**

1. **Verify data availability:**
   ```bash
   python -m src.main costs --days 7 --format json
   ```

2. **Check date range:**
   - Ensure selected date range has data
   - Try different time periods
   - Verify cloud providers have cost data

3. **Force cache refresh:**
   ```bash
   # API call with force refresh
   curl "http://localhost:8000/api/v1/costs/summary?force_refresh=true"
   ```

### Dashboard Performance Issues

**Problem:** Slow dashboard loading or interactions

**Solutions:**

1. **Reduce data scope:**
   - Use smaller date ranges for testing
   - Filter by specific provider
   - Use daily granularity for recent data

2. **Check memory usage:**
   ```bash
   # Monitor process memory
   top -p $(pgrep -f "python.*dashboard")
   ```

3. **Optimize cache settings:**
   ```yaml
   dashboard:
     refresh_interval: 300  # Increase refresh interval
     max_accounts_display: 10  # Reduce displayed accounts
   ```

## API Issues

### API Endpoints Not Responding

**Problem:** API returns 500 errors or timeouts

**Solutions:**

1. **Check API logs:**
   ```bash
   # Local
   python -m src.main api --log-level DEBUG

   # OpenShift
   oc logs deployment/cost-monitor-api
   ```

2. **Verify dependencies:**
   ```bash
   # Test database connection
   python -c "import asyncpg; print('asyncpg available')"

   # Test Redis connection
   python -c "import redis; r=redis.Redis(); print(r.ping())"
   ```

3. **Check resource limits:**
   ```bash
   # Memory and CPU usage
   docker stats cost-monitor-api

   # OpenShift resource usage
   oc top pods -l app=cost-monitor-api
   ```

### API Authentication Issues

**Problem:** API returns 401/403 errors

**Solutions:**

1. **Check OAuth proxy (OpenShift):**
   ```bash
   oc get route cost-monitor-api-route
   oc logs deployment/oauth-proxy
   ```

2. **Verify service account permissions:**
   ```bash
   oc get serviceaccount cost-monitor
   oc describe rolebinding cost-monitor
   ```

## Cloud Provider API Issues

### Rate Limiting

**Problem:** Cloud provider APIs returning rate limit errors

**Symptoms:**
```
ThrottlingException: Rate exceeded
TooManyRequestsException: Request rate is too high
```

**Solutions:**

1. **Implement exponential backoff:**
   ```yaml
   providers:
     aws:
       retry_config:
         max_attempts: 5
         backoff_multiplier: 2
   ```

2. **Increase cache TTL:**
   ```yaml
   cache:
     aws:
       ttl: 7200  # Cache for 2 hours
   ```

3. **Reduce API call frequency:**
   ```yaml
   dashboard:
     refresh_interval: 900  # Refresh every 15 minutes
   ```

### Data Consistency Issues

**Problem:** Inconsistent or missing data from cloud providers

**Solutions:**

1. **Check data availability:**
   ```bash
   # AWS Cost Explorer has 24-48 hour delay
   python -m src.main costs --start-date 2025-01-22 --provider aws
   ```

2. **Verify billing export configuration:**
   ```bash
   # Azure billing exports
   az consumption export list

   # GCP BigQuery billing export
   bq ls billing_export
   ```

3. **Compare with cloud console:**
   - Verify data matches native cloud cost dashboards
   - Check for currency or timezone differences

## Performance Issues

### High Memory Usage

**Problem:** Application consuming excessive memory

**Solutions:**

1. **Profile memory usage:**
   ```bash
   pip install memory-profiler
   python -m memory_profiler src/main.py costs
   ```

2. **Check for memory leaks:**
   ```bash
   # Monitor memory over time
   while true; do
     ps -o pid,ppid,%mem,rss,cmd -p $(pgrep -f "python.*cost-monitor")
     sleep 30
   done
   ```

3. **Optimize data processing:**
   ```python
   # Use generators instead of loading all data
   for chunk in cost_data_generator(start_date, end_date):
       process_chunk(chunk)
   ```

### Slow API Responses

**Problem:** API endpoints taking too long to respond

**Solutions:**

1. **Enable query profiling:**
   ```bash
   export DEBUG=true
   export LOG_LEVEL=DEBUG
   python -m src.main api
   ```

2. **Optimize database queries:**
   ```sql
   EXPLAIN ANALYZE SELECT * FROM cost_data WHERE date >= '2025-01-01';
   ```

3. **Implement pagination:**
   ```python
   @app.get("/api/v1/costs")
   async def get_costs(limit: int = 100, offset: int = 0):
       # Paginated response
   ```

## Deployment Issues

### OpenShift Deployment Problems

**Problem:** Pods failing to start or crashing

**Solutions:**

1. **Check pod status:**
   ```bash
   oc get pods -l app=cost-monitor
   oc describe pod cost-monitor-api-xxx
   ```

2. **Review logs:**
   ```bash
   oc logs deployment/cost-monitor-api --previous
   oc logs deployment/cost-monitor-dashboard
   ```

3. **Check resource constraints:**
   ```bash
   oc get limitrange
   oc describe resourcequota
   ```

4. **Verify secrets and ConfigMaps:**
   ```bash
   oc get secrets cost-monitor-secrets
   oc get configmap cost-monitor-config
   ```

### Network Connectivity Issues

**Problem:** Services cannot communicate

**Solutions:**

1. **Check service endpoints:**
   ```bash
   oc get endpoints
   oc get services
   ```

2. **Test network policies:**
   ```bash
   oc get networkpolicy
   oc describe networkpolicy cost-monitor-netpol
   ```

3. **Verify DNS resolution:**
   ```bash
   oc exec deployment/cost-monitor-api -- nslookup postgresql
   ```

## Getting Help

### Log Collection

**Collect diagnostic information:**

```bash
#!/bin/bash
# collect-logs.sh

echo "=== System Information ===" > debug-info.txt
uname -a >> debug-info.txt
date >> debug-info.txt

echo "=== Python Environment ===" >> debug-info.txt
python --version >> debug-info.txt
pip list | grep -E "(dash|fastapi|boto3|azure|google)" >> debug-info.txt

echo "=== Configuration ===" >> debug-info.txt
python -m src.main test-auth 2>&1 >> debug-info.txt

echo "=== API Health ===" >> debug-info.txt
curl -s http://localhost:8000/api/health/ready >> debug-info.txt

echo "=== Logs ===" >> debug-info.txt
tail -100 /var/log/cost-monitor/app.log >> debug-info.txt
```

### Enable Debug Mode

**Maximum verbosity for troubleshooting:**

```bash
export DEBUG=true
export LOG_LEVEL=DEBUG
python -m src.main costs --verbose 2>&1 | tee debug-output.log
```

### Support Channels

- **Documentation**: Check docs/ directory for specific guides
- **Configuration Examples**: Review config/ directory
- **GitHub Issues**: Report bugs with debug information
- **Local Testing**: Use direct Python commands for testing individual components

### Common Solution Patterns

1. **"Try turning it off and on again"**: Restart services, clear caches
2. **"Check the obvious"**: Verify credentials, network, basic configuration
3. **"Isolate the problem"**: Test individual components separately
4. **"Compare working state"**: Use known-good configuration
5. **"Gather evidence"**: Collect logs, metrics, and diagnostic output