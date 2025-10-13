  Critical Changes (Must Do)

  1. pyproject.toml (2 locations)

  # Line 2
  name = "m365-mcp"

  # Line 21 - Entry point script name
  [project.scripts]
  m365-mcp = "m365_mcp.server:main"  # Note: Python module uses underscores

  2. Folder Structure

  ⚠️ Important: Python packages use underscores, not hyphens!
  mv src/microsoft_mcp src/m365_mcp

  3. Environment Variables (84 references across codebase)

  You have two options:

  Option A: Rename environment variables (Breaking change)
  - MICROSOFT_MCP_CLIENT_ID → M365_MCP_CLIENT_ID
  - MICROSOFT_MCP_TENANT_ID → M365_MCP_TENANT_ID
  - MCP_* variables can stay as-is (they're generic MCP protocol vars)

  Option B: Keep existing names (Backward compatible)
  - Keep MICROSOFT_MCP_* for compatibility
  - Users don't need to update their .env files

  Files affected (if you choose Option A):
  - src/m365_mcp/auth.py
  - src/m365_mcp/server.py
  - .env.example
  - .env.stdio.example
  - .env.http.example
  - All documentation files

  4. Shell Scripts (3 files)

  # start_mcp_with_monitoring.sh - line 167
  nohup uv run m365-mcp > "${SERVER_OUTPUT_LOG}" 2>&1 &

  # monitor_mcp_server.sh - line 152
  pgrep -f "m365-mcp|m365_mcp" || true

  5. Documentation Files (Update all references)

  Must update:
  - README.md - Title, installation commands, URLs
  - QUICKSTART.md - All setup commands
  - CHANGELOG.md - Project name references
  - CLAUDE.md - Project overview
  - MONITORING.md - Commands and references
  - ENV_FILE_USAGE.md - Example commands
  - SECURITY.md - Project name
  - .projects/steering/*.md - All steering documents

  Example from README.md line 22:
  # Current
  git clone https://github.com/robin-collins/m365-mcp.git
  cd microsoft-mcp && uv sync

  # Updated
  git clone https://github.com/robin-collins/m365-mcp.git
  cd m365-mcp && uv sync

  6. Authentication Script Comments

  # authenticate.py - line 3, 21
  """
  Authenticate Microsoft accounts for use with M365 MCP.
  ...
  """
  description="Authenticate Microsoft accounts for M365 MCP"

  7. Lock File

  After all changes:
  uv lock --upgrade-package m365-mcp

  Optional Changes

  8. Git Repository Name ✅ Already done!

  Your git remote already shows m365-mcp.git, so this is complete.

  9. Cache Directory Name (Not required)

  The cache is currently .cache/token_cache.json - you could rename to .m365_mcp_cache/ for clarity, but not necessary since it's project-local.

  10. Tool Metadata (For consistency)

  The tool descriptions in src/m365_mcp/tools/*.py mention "Microsoft MCP" - consider updating to "M365 MCP" for branding consistency.

  Testing After Rename

  # 1. Rebuild
  uv sync

  # 2. Verify CLI command
  uv run m365-mcp --help

  # 3. Test stdio mode
  uv run m365-mcp --env-file .env.stdio

  # 4. Run tests
  uv run pytest tests/test_validators.py tests/test_tool_confirmation.py -v

  Recommendation

  I recommend Option B (keep MICROSOFT_MCP_* environment variables) because:
  1. Backward compatible - Existing users don't break
  2. Less work - Only 7 critical files to update vs. 84 references
  3. Clear naming - "MICROSOFT" in the variable makes it obvious what service it connects to
  4. Common pattern - Many MCP servers keep the service name in env vars (e.g., GITHUB_TOKEN, OPENAI_API_KEY)

  The package name m365-mcp is cleaner/shorter while the env vars remain descriptive.
