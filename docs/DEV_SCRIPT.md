# Local Development Script

The `scripts/dev-local-to-ocp.sh` script provides a comprehensive development environment for the cost-monitor application by creating tunnels to OpenShift resources and managing local services.

## Overview

This script allows developers to:
- Run API and dashboard services locally with live code reloading
- Create port-forward tunnels to Redis and PostgreSQL in OpenShift
- Manage OpenShift database pods (start/stop/restart)
- Clear Redis cache when needed
- Monitor service status and view logs
- Avoid git commits for rapid development iteration

## Prerequisites

1. **OpenShift CLI**: `oc` command must be installed and configured
2. **OpenShift Login**: Must be logged into your OpenShift cluster (`oc login`)
3. **Cloud Credentials**: `config/.secrets.yaml` must exist with cloud provider credentials
4. **Python Environment**: Local Python environment with required dependencies
5. **Network Tools**: `nc` (netcat) and `curl` for connectivity checks

## Usage

```bash
./scripts/dev-local-to-ocp.sh [NAMESPACE] [ACTION] [COMPONENT]
```

### Parameters

- **NAMESPACE** (optional): OpenShift namespace, defaults to `cost-monitor-dev`
- **ACTION** (required): What operation to perform
- **COMPONENT** (required): What component to operate on

## Actions

| Action | Description |
|--------|-------------|
| `start` | Start services/tunnels/pods |
| `stop` | Stop services/tunnels/pods |
| `restart` | Restart services/tunnels/pods |
| `status` | Show status of services/tunnels/pods |
| `logs` | Show logs for services/tunnels/pods |
| `clear-redis-cache` | Clear Redis cache (no component needed) |
| `help` | Show help information |

## Components

### Local Services
| Component | Description |
|-----------|-------------|
| `api` | FastAPI data service (localhost:8000) |
| `dashboard` | Dash visualization dashboard (localhost:8050) |

### OpenShift Tunnels
| Component | Description |
|-----------|-------------|
| `postgres-tunnel` | PostgreSQL port-forward (localhost:5432) |
| `redis-tunnel` | Redis port-forward (localhost:6379) |
| `all-tunnels` | Both database tunnels |

### OpenShift Pod Management
| Component | Description |
|-----------|-------------|
| `postgres-pod` | PostgreSQL StatefulSet pod |
| `redis-pod` | Redis Deployment pod |
| `all-pods` | Both database pods |

### Meta Components
| Component | Description |
|-----------|-------------|
| `all` | All services and tunnels (excludes pod management) |

## Examples

### Starting Services
```bash
# Start everything (services + tunnels)
./scripts/dev-local-to-ocp.sh start all

# Start just the API service
./scripts/dev-local-to-ocp.sh start api

# Start just database tunnels
./scripts/dev-local-to-ocp.sh start all-tunnels

# Start PostgreSQL pod in OpenShift
./scripts/dev-local-to-ocp.sh start postgres-pod
```

### Stopping Services
```bash
# Stop everything
./scripts/dev-local-to-ocp.sh stop all

# Stop just the dashboard
./scripts/dev-local-to-ocp.sh stop dashboard

# Stop database pods in OpenShift
./scripts/dev-local-to-ocp.sh stop all-pods
```

### Restarting Services
```bash
# Restart API for code changes
./scripts/dev-local-to-ocp.sh restart api

# Restart database tunnels if connection issues
./scripts/dev-local-to-ocp.sh restart all-tunnels

# Restart Redis pod in OpenShift
./scripts/dev-local-to-ocp.sh restart redis-pod
```

### Status and Monitoring
```bash
# Check status of everything
./scripts/dev-local-to-ocp.sh status all

# Check just API status
./scripts/dev-local-to-ocp.sh status api

# Check database pod status
./scripts/dev-local-to-ocp.sh status all-pods
```

### Viewing Logs
```bash
# Follow API logs in real-time
./scripts/dev-local-to-ocp.sh logs api

# View PostgreSQL tunnel logs
./scripts/dev-local-to-ocp.sh logs postgres-tunnel

# View Redis pod logs from OpenShift
./scripts/dev-local-to-ocp.sh logs redis-pod

# View all logs (recent entries)
./scripts/dev-local-to-ocp.sh logs all
```

### Cache Management
```bash
# Clear Redis cache (useful after data structure changes)
./scripts/dev-local-to-ocp.sh clear-redis-cache
```

### Using Different Namespaces
```bash
# Use staging environment
./scripts/dev-local-to-ocp.sh cost-monitor-staging start all

# Check production pod status
./scripts/dev-local-to-ocp.sh cost-monitor-prod status all-pods
```

## How It Works

### Credential Management
The script automatically extracts database credentials from OpenShift secrets:
- PostgreSQL: `postgresql-credentials` secret (username, password, database)
- Redis: `redis-credentials` secret (password)
- Cloud credentials are read from existing `config/.secrets.yaml`

### Port Forwarding
Tunnels are created using `oc port-forward`:
- PostgreSQL: `localhost:5432` → `postgresql.svc:5432`
- Redis: `localhost:6379` → `redis-service.svc:6379`

### Process Management
- Service processes are run in background with PIDs stored in `/tmp/cost-monitor-dev/`
- Logs are written to `/tmp/cost-monitor-dev/` (e.g., `api.log`, `postgres-tunnel.log`)
- Health checks ensure services are responding on expected ports

### Pod Management
- Uses `oc scale` to start/stop pods by setting replicas to 1/0
- PostgreSQL: Manages `postgresql` StatefulSet
- Redis: Manages `redis` Deployment
- Includes waiting periods for graceful termination

## File Locations

### Temporary Files (Auto-cleaned)
- **PIDs**: `/tmp/cost-monitor-dev/*.pid`
- **Logs**: `/tmp/cost-monitor-dev/*.log`

### Configuration Files (Not Modified)
- **Cloud Credentials**: `config/.secrets.yaml`
- **OpenShift Secrets**: Retrieved dynamically, not stored locally

## Development Workflow

### Typical Development Session
```bash
# 1. Start everything
./scripts/dev-local-to-ocp.sh start all

# 2. Develop and test locally
# API available at: http://localhost:8000
# Dashboard available at: http://localhost:8050

# 3. Restart services as needed for code changes
./scripts/dev-local-to-ocp.sh restart api
./scripts/dev-local-to-ocp.sh restart dashboard

# 4. Clear cache if data structure changes
./scripts/dev-local-to-ocp.sh clear-redis-cache

# 5. Check logs if issues arise
./scripts/dev-local-to-ocp.sh logs api

# 6. Stop when done
./scripts/dev-local-to-ocp.sh stop all
```

### Code Change Workflow
1. **API Changes**: `restart api` to reload FastAPI with new code
2. **Dashboard Changes**: `restart dashboard` to reload Dash application
3. **Database Schema Changes**: `clear-redis-cache` to invalidate cached data
4. **Connection Issues**: `restart all-tunnels` to recreate port-forwards

## Troubleshooting

### Common Issues

**"Not logged into OpenShift"**
```bash
oc login https://your-cluster-url
```

**"Namespace not found"**
```bash
# Check available namespaces
oc get namespaces | grep cost-monitor

# Use correct namespace
./scripts/dev-local-to-ocp.sh cost-monitor-dev start all
```

**"Failed to load credentials"**
- Verify OpenShift secrets exist: `oc get secrets | grep -E "(postgresql|redis)-credentials"`
- Check namespace permissions: `oc auth can-i get secrets`

**"API/Dashboard not responding"**
- Check if tunnels are running: `status all-tunnels`
- Verify database connectivity: `status all-pods`
- Check service logs: `logs api` or `logs dashboard`

**"Port already in use"**
- Stop existing services: `stop all`
- Kill any remaining processes: `pkill -f "oc port-forward"`

### Manual Cleanup
```bash
# Remove all temporary files
rm -rf /tmp/cost-monitor-dev/

# Kill any remaining port-forwards
pkill -f "oc port-forward"

# Check for hung processes
ps aux | grep -E "(uvicorn|python.*dashboard)"
```

### Debug Mode
```bash
# Check what's running
./scripts/dev-local-to-ocp.sh status all

# View recent log entries
./scripts/dev-local-to-ocp.sh logs all

# Test OpenShift connectivity
oc get pods -n cost-monitor-dev
```

## Security Notes

- Database passwords are loaded from OpenShift secrets (not stored locally)
- Cloud credentials use existing `config/.secrets.yaml` file
- No secrets are written to the local filesystem
- Temporary files are created in `/tmp` with process isolation
- Redis cache clearing requires proper authentication

## Performance Tips

- Use `restart api` instead of `restart all` for faster API reloads
- Use `clear-redis-cache` sparingly (only when data structure changes)
- Monitor tunnel health with `status all-tunnels` if experiencing connectivity issues
- Use `logs api` to monitor FastAPI startup and identify performance bottlenecks