# Using --env-file for Testing Different Modes

The `--env-file` command-line argument allows you to easily switch between different environment configurations, making it simple to test different MCP server modes without modifying your main `.env` file.

## Quick Start

### 1. Create Mode-Specific Environment Files

Copy the example files and customize them:

```bash
# For stdio mode (default)
cp .env.stdio.example .env.stdio
# Edit .env.stdio and set your M365_MCP_CLIENT_ID

# For HTTP mode
cp .env.http.example .env.http
# Edit .env.http and set your M365_MCP_CLIENT_ID and MCP_AUTH_TOKEN
```

### 2. Run with Specific Environment File

```bash
# Run with stdio mode configuration
m365-mcp --env-file .env.stdio

# Run with HTTP mode configuration
m365-mcp --env-file .env.http

# Or use relative/absolute paths
m365-mcp --env-file /path/to/custom.env
```

### 3. Authentication with Custom Environment

The `authenticate.py` script also supports the `--env-file` argument:

```bash
# Authenticate using stdio mode credentials
python authenticate.py --env-file .env.stdio

# Authenticate using HTTP mode credentials
python authenticate.py --env-file .env.http
```

### 4. Testing with Custom Environment

The test suite supports custom env files via the `TEST_ENV_FILE` environment variable:

```bash
# Run tests with stdio mode configuration
TEST_ENV_FILE=.env.stdio uv run pytest tests/ -v

# Run tests with HTTP mode configuration
TEST_ENV_FILE=.env.http uv run pytest tests/ -v
```

## Use Cases

### Testing Different Transport Modes

Quickly switch between stdio and HTTP modes without editing your main `.env` file:

```bash
# Test stdio mode
m365-mcp --env-file .env.stdio

# Test HTTP mode
m365-mcp --env-file .env.http
```

### Development vs Production Configurations

Create separate environment files for different environments:

```bash
# Development
.env.dev
m365-mcp --env-file .env.dev

# Staging
.env.staging
m365-mcp --env-file .env.staging

# Production
.env.prod
m365-mcp --env-file .env.prod
```

### Multi-Account Testing

Test with different Microsoft accounts by creating account-specific env files:

```bash
# Work account
.env.work
m365-mcp --env-file .env.work

# Personal account
.env.personal
m365-mcp --env-file .env.personal
```

### CI/CD Integration

Use different configurations in automated testing:

```bash
# In your CI/CD pipeline
TEST_ENV_FILE=.env.ci uv run pytest tests/ -v
```

## Example Configurations

### stdio Mode (.env.stdio)

```bash
M365_MCP_CLIENT_ID=your-client-id
MCP_TRANSPORT=stdio
MCP_LOG_LEVEL=INFO
```

### HTTP Mode with Bearer Auth (.env.http)

```bash
M365_MCP_CLIENT_ID=your-client-id
MCP_TRANSPORT=http
MCP_HOST=127.0.0.1
MCP_PORT=8000
MCP_AUTH_METHOD=bearer
MCP_AUTH_TOKEN=your-secure-token-here
MCP_LOG_LEVEL=DEBUG
```

### HTTP Mode on Custom Port (.env.http.custom)

```bash
M365_MCP_CLIENT_ID=your-client-id
MCP_TRANSPORT=http
MCP_HOST=0.0.0.0
MCP_PORT=9000
MCP_PATH=/api/mcp
MCP_AUTH_METHOD=bearer
MCP_AUTH_TOKEN=your-secure-token-here
```

## Security Notes

1. **Never commit actual `.env` files to version control** - Only commit `.example` files
2. **Add all custom env files to `.gitignore`** - Already configured to ignore `.env.*` (except `.example` files)
3. **Use strong tokens** - Generate with `openssl rand -hex 32`
4. **Rotate tokens regularly** - Especially for production environments
5. **Keep environment files secure** - Use file permissions (e.g., `chmod 600 .env.http`)

## Troubleshooting

### File Not Found Warning

If you see `Warning: Environment file not found`, check:
- The file path is correct (relative or absolute)
- The file exists in the specified location
- You have read permissions on the file

### Environment Variables Not Loading

If environment variables aren't being loaded:
1. Verify the file syntax (KEY=VALUE, no quotes needed for simple values)
2. Check for typos in variable names
3. Ensure no spaces around the `=` sign
4. The server will continue with system environment variables if file is not found

### Default Behavior

If no `--env-file` argument is provided, the server will:
1. Look for `.env` in the current directory
2. Fall back to system environment variables if `.env` not found

## More Information

- See `.env.example` for complete configuration reference
- See `SECURITY.md` for security best practices
- See `QUICKSTART.md` for setup instructions
- See `CHANGELOG.md` for recent changes
