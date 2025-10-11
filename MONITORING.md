# MCP Server Monitoring and Diagnostics

This document describes the comprehensive monitoring and diagnostic collection system for the Microsoft MCP server, designed to detect failures and collect detailed diagnostic information for troubleshooting.

## Overview

The monitoring system provides:

- **Comprehensive Logging**: Structured JSON logs, human-readable logs, and separate error logs
- **Continuous Metrics Collection**: Memory, CPU, response times, thread counts, open files
- **Health Monitoring**: Continuous health checks with automatic failure detection
- **Diagnostic Reports**: Detailed error reports with metrics, logs, and system state
- **NO AUTO-RESTART**: On failure, the server is killed and requires manual restart after investigation

## Quick Start

### 1. Start Server with Monitoring

```bash
# Set required environment variables
export MICROSOFT_MCP_CLIENT_ID="your-azure-client-id"
export MCP_AUTH_TOKEN="your-secure-token"  # Optional, will be generated if not set

# Start server with monitoring
./start_mcp_with_monitoring.sh
```

This will:
- Start the MCP server in HTTP mode
- Enable comprehensive logging to `./logs/`
- Start the health monitor
- Auto-restart on failure with diagnostic reports

### 2. Manual Health Check

```bash
# Single health check
uv run python -m microsoft_mcp.health_check http://localhost:8000/health

# Continuous monitoring
uv run python -m microsoft_mcp.health_check --continuous --interval 10 http://localhost:8000/health

# With authentication
uv run python -m microsoft_mcp.health_check --auth-token "your-token" http://localhost:8000/health
```

### 3. Manual Server Start (with logging only)

```bash
# Set environment variables
export MICROSOFT_MCP_CLIENT_ID="your-client-id"
export MCP_TRANSPORT="http"
export MCP_HOST="127.0.0.1"
export MCP_PORT="8000"
export MCP_AUTH_METHOD="bearer"
export MCP_AUTH_TOKEN="your-token"
export MCP_LOG_LEVEL="INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Start server
uv run microsoft-mcp
```

## Metrics Collection

### Metrics File

The monitor continuously collects performance metrics in `logs/metrics.log`:

**Format**: CSV with columns: `timestamp,metric_type,value,status`

**Collected metrics**:
- **Memory (RSS)**: Resident Set Size in KB for each process
- **CPU %**: CPU utilization percentage
- **Thread count**: Number of active threads
- **Open files**: Number of open file descriptors
- **Response time**: Health check response time in milliseconds

**Example**:
```csv
2025-10-10 12:34:56,12345,524288,2.5,8,145
2025-10-10 12:34:56,health_check,145,0
```

This shows a process using 512MB RAM, 2.5% CPU, 8 threads, 145 open files, and a 145ms health check response.

## Logging System

### Log Files

The server creates multiple log files in the `logs/` directory:

| File | Format | Content | Retention |
|------|--------|---------|-----------|
| `mcp_server_all.jsonl` | JSON Lines | All logs (DEBUG+) | 10 files × 10MB |
| `mcp_server_errors.jsonl` | JSON Lines | Errors only (ERROR+) | 10 files × 10MB |
| `mcp_server.log` | Human-readable | All logs (configurable level) | 10 files × 10MB |
| `server_output.log` | Raw | Server stdout/stderr | No rotation |
| `monitor.log` | Human-readable | Monitor activity | No rotation |

### Log Levels

Configure logging verbosity with `MCP_LOG_LEVEL`:

```bash
export MCP_LOG_LEVEL="DEBUG"   # Very verbose, all debug info
export MCP_LOG_LEVEL="INFO"    # Default, normal operations
export MCP_LOG_LEVEL="WARNING" # Only warnings and errors
export MCP_LOG_LEVEL="ERROR"   # Only errors and critical
```

### JSON Log Format

Structured logs in `mcp_server_all.jsonl` use this format:

```json
{
  "timestamp": "2025-10-10T12:34:56.789",
  "level": "INFO",
  "logger": "microsoft_mcp.server",
  "message": "Request processed",
  "module": "server",
  "function": "auth_middleware",
  "line": 230,
  "account_id": "user@example.com",
  "tool_name": "send_email",
  "duration_ms": 145.23
}
```

### Searching Logs

#### Search for errors

```bash
# JSON logs
grep '"level":"ERROR"' logs/mcp_server_all.jsonl | tail -n 20

# Human-readable logs
grep '\[ERROR\]' logs/mcp_server.log | tail -n 20
```

#### Search by account

```bash
grep '"account_id":"user@example.com"' logs/mcp_server_all.jsonl
```

#### Search by tool

```bash
grep '"tool_name":"send_email"' logs/mcp_server_all.jsonl
```

#### Find slow requests

```bash
# Requests taking more than 1000ms
grep '"duration_ms"' logs/mcp_server_all.jsonl | \
  awk -F'"duration_ms":' '{print $2}' | \
  awk -F',' '{if ($1 > 1000) print $0}'
```

## Monitoring System

### Health Check Endpoint

The server exposes a health check endpoint at `/health`:

```bash
curl http://localhost:8000/health
```

Response:
```json
{
  "status": "ok",
  "transport": "http",
  "auth": "bearer"
}
```

### Monitor Script

The `monitor_mcp_server.sh` script provides:

- **Continuous metrics collection**: Memory (RSS), CPU%, threads, open files every check interval
- **Response time tracking**: HTTP health check timing for every request
- **Periodic health checks**: HTTP endpoint polling with configurable intervals
- **Failure detection**: Configurable threshold for consecutive failures
- **Automatic kill on failure**: Graceful SIGTERM → SIGKILL cleanup (NO RESTART)
- **Comprehensive diagnostic reports**: Includes metrics history, logs, system state

**Important**: The monitor does NOT automatically restart the server. On failure, it kills the server and exits with a diagnostic report. This allows you to investigate the root cause before manually restarting.

#### Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_HEALTH_URL` | `http://127.0.0.1:8000/health` | Health check endpoint |
| `MCP_CHECK_INTERVAL` | `10` | Seconds between checks |
| `MCP_MAX_FAILURES` | `3` | Consecutive failures before restart |
| `MCP_LOG_DIR` | `./logs` | Log directory |
| `MCP_REPORT_DIR` | `./reports` | Error report directory |

#### Usage

```bash
# Use defaults
./monitor_mcp_server.sh

# Custom configuration
./monitor_mcp_server.sh --health-check-url http://localhost:8000/health --check-interval 5

# Or with environment variables
export MCP_HEALTH_URL="http://localhost:8000/health"
export MCP_CHECK_INTERVAL="5"
export MCP_MAX_FAILURES="5"
./monitor_mcp_server.sh
```

### Error Reports

When the monitor detects a failure, it generates a comprehensive error report in `reports/`:

```
reports/error_report_20251010_123456.txt
```

The report includes:

1. **Recent Errors**: Last 50 lines from error log
2. **Recent Activity**: Last 100 lines from main log
3. **Recent JSON Logs**: Last 100 structured log entries
4. **Monitor Log**: Last 50 lines from monitor
5. **Metrics Summary**: Last 50 metrics entries (memory, CPU, response times)
6. **System Information**: Process info, memory, disk usage
7. **Process Details**: Process status, command line, open files
8. **Port Information**: Listening sockets
9. **Open Files**: File descriptors for MCP processes

**Key for diagnostics**: Check the metrics summary to see memory growth, CPU spikes, or slow response times leading up to the failure.

## Troubleshooting

### Server Won't Start

1. Check environment variables:
   ```bash
   echo $MICROSOFT_MCP_CLIENT_ID
   echo $MCP_AUTH_TOKEN
   ```

2. Check logs:
   ```bash
   tail -f logs/server_output.log
   tail -f logs/mcp_server.log
   ```

3. Check port availability:
   ```bash
   ss -tlnp | grep 8000
   ```

### Server Hangs or Becomes Unresponsive

1. Check if health check responds:
   ```bash
   curl -v http://localhost:8000/health
   ```

2. Check recent errors:
   ```bash
   tail -f logs/mcp_server_errors.jsonl
   ```

3. Check process status:
   ```bash
   ps aux | grep microsoft-mcp
   ```

4. Force cleanup:
   ```bash
   pkill -9 -f microsoft-mcp
   ```

### High Memory Usage

1. Check process memory:
   ```bash
   ps aux | grep microsoft-mcp
   ```

2. Check for memory leaks in logs:
   ```bash
   grep -i "memory\|leak" logs/mcp_server.log
   ```

### Slow Response Times

1. Check request durations in logs:
   ```bash
   grep '"duration_ms"' logs/mcp_server_all.jsonl | tail -n 50
   ```

2. Check metrics for response time trends:
   ```bash
   grep "health_check" logs/metrics.log | tail -n 50
   ```

3. Check for rate limiting:
   ```bash
   grep -i "rate limit\|throttle" logs/mcp_server.log
   ```

4. Enable debug logging:
   ```bash
   export MCP_LOG_LEVEL="DEBUG"
   ```

### Analyzing Metrics After Failure

When a server fails and generates an error report:

1. **Check memory growth**:
   ```bash
   # Extract memory column from metrics
   grep -E "^[0-9]" reports/error_report_*.txt | grep -A 50 "METRICS SUMMARY" | awk -F',' '{print $3}' | sort -n
   ```

2. **Check response time degradation**:
   ```bash
   # Extract health check timings
   grep "health_check" logs/metrics.log | awk -F',' '{print $1,$3}'
   ```

3. **Look for patterns**: Memory leaks show steady growth, hangs show sudden response time spikes

## Best Practices

### Production Deployment

1. **Use strong authentication tokens**:
   ```bash
   export MCP_AUTH_TOKEN="$(openssl rand -hex 32)"
   ```

2. **Enable monitoring**:
   ```bash
   ./start_mcp_with_monitoring.sh
   ```

3. **Set appropriate log level**:
   ```bash
   export MCP_LOG_LEVEL="INFO"  # Not DEBUG in production
   ```

4. **Monitor disk space**:
   ```bash
   df -h logs/
   ```

5. **Archive old reports**:
   ```bash
   tar -czf reports_archive_$(date +%Y%m%d).tar.gz reports/
   mv reports_archive_*.tar.gz archive/
   rm -rf reports/*
   ```

### Log Rotation

Logs automatically rotate when they reach 10MB. Old logs are kept with `.1`, `.2`, etc. suffixes:

```
logs/
  mcp_server.log       # Current
  mcp_server.log.1     # Previous
  mcp_server.log.2     # Older
  ...
```

To manually clean old logs:

```bash
# Keep only last 3 rotated logs
find logs/ -name "*.log.*" -o -name "*.jsonl.*" | \
  sort -r | tail -n +4 | xargs rm -f
```

### Security

1. **Never expose logs publicly** - They may contain sensitive information
2. **Rotate auth tokens regularly**
3. **Use HTTPS in production** (requires reverse proxy)
4. **Restrict log file permissions**:
   ```bash
   chmod 600 logs/*.jsonl logs/*.log
   ```

## Advanced Usage

### Custom Health Checks

Create custom health check scripts using the Python module:

```python
from microsoft_mcp.health_check import check_health_async
import asyncio

async def main():
    result = await check_health_async(
        url="http://localhost:8000/health",
        timeout=5.0,
        auth_token="your-token"
    )

    if result.success:
        print(f"✓ Healthy (response time: {result.response_time_ms:.2f}ms)")
    else:
        print(f"✗ Unhealthy: {result.error}")

asyncio.run(main())
```

### Integration with Monitoring Systems

#### Prometheus

Export metrics from logs:

```bash
# Count errors in last minute
grep '"level":"ERROR"' logs/mcp_server_all.jsonl | \
  grep "$(date -u -d '1 minute ago' '+%Y-%m-%dT%H:%M')" | \
  wc -l
```

#### Grafana Loki

Ship JSON logs to Loki:

```bash
# Install promtail
# Configure promtail.yaml to tail logs/mcp_server_all.jsonl
```

## Support

If you encounter issues not covered here:

1. Generate an error report (automatically created on failure)
2. Check recent logs in `logs/`
3. Look for related issues in the repository
4. Create a new issue with:
   - Error report
   - Recent logs (sanitized of sensitive info)
   - Steps to reproduce
