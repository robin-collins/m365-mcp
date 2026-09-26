# File Tree

Tracked files of the v1.0.0 tree, without editor and tool state (`.claude/`,
`.codex/`, `.gait/`, `.venv/`, `logs/`) and without generated caches.
Directories with many similar files are summarised. Files marked *generated*
are written by a script and must not be edited by hand.

```text
m365-mcp/
├── .github/workflows/ci.yml                # CI: tests, spec checks, pyright, ruff
├── .projects/steering/                     # AI assistant guidance (read before editing code)
│   ├── product.md                          # Product overview
│   ├── tech.md                             # Technology stack and commands
│   ├── structure.md                        # Project structure and layers
│   ├── python.md                           # Python implementation standards
│   ├── mcp-server.md                       # MCP server standards (spec-first, confirm gates)
│   └── tool-names.md                       # Tool naming, safety metadata, description template
├── docs/
│   ├── unified-tools/                      # Tool specification, source of truth (generated)
│   │   ├── README.md                       # Implementation contract and conventions
│   │   ├── SCHEMA_REFERENCE.md             # Human-readable schema reference (generated)
│   │   ├── index.json                      # Tool order, tiers, default toolsets (generated)
│   │   ├── legacy_mapping.json             # The 85 removed v0.x tools and their replacements (generated)
│   │   └── tools/                          # One JSON spec per tool, 29 files (generated)
│   ├── cache_user_guide.md                 # Cache guide: refresh, admin tools, invalidation
│   ├── cache_examples.md                   # Cache usage examples and workflows
│   ├── cache_security.md                   # Cache encryption, keys, compliance notes
│   ├── analysis_results.md                 # Code audit analysis (historical)
│   ├── audit_remediation_task_list.md      # Audit remediation checklist (historical)
│   ├── audit_remediation_phase_gates.md    # Audit remediation phase gates (historical)
│   ├── m365_readonly_test_report.html      # Read-only tool test report (historical)
│   ├── m365_readonly_test_report.md        # Read-only tool test report (historical)
│   ├── m365_write_tool_test_plan.md        # Write-tool test plan (historical)
│   ├── TOOL_RESULTS.md                     # Write-tool audit failure report (historical)
│   └── tasks/                              # Per-task completion reports of the earlier audit remediation
├── evals/                                  # Golden-prompt evaluation harness
│   ├── README.md                           # How the harness works and how to run it
│   ├── cases.py                            # 115 prompts, 25% held out
│   ├── fake_graph.py                       # In-memory personal account served through httpx.MockTransport
│   ├── fixtures.py                         # Fake mailbox, calendar, contacts and OneDrive data
│   ├── grading.py                          # Scoring of first tool, arguments, task success
│   ├── runner.py                           # Runs a model against a tool surface
│   ├── surface.py                          # Builds the surface and patches transport, token and sleeps
│   ├── __init__.py
│   └── results/                            # Run output (kept empty in git)
├── graphapi_update/                        # Graph API research notes (historical)
├── individual_schema/                      # Per-operation JSON schemas from the design phase (historical)
├── unified_schema/                         # Early unified-schema proposal (historical)
├── scripts/
│   ├── build_unified_tool_specs.py         # Generates docs/unified-tools and src/m365_mcp/tool_specs
│   ├── generate_tools_doc.py               # Regenerates MCP_SERVER_TOOLS.md from the live tools/list
│   └── register_reauth_task.ps1            # Registers the weekly re-auth scheduled task (Windows)
├── src/m365_mcp/
│   ├── __init__.py
│   ├── server.py                           # Entry point, stdio and Streamable HTTP transports
│   ├── auth.py                             # MSAL sign-in (personal accounts only), token cache
│   ├── auth_sessions.py                    # Server-side device-flow sessions (opaque auth_session_id)
│   ├── graph.py                            # Graph client: retries, 401 refresh, deadlines, $batch, uploads
│   ├── errors.py                           # GraphAPIError and mapping to actionable ToolError text
│   ├── projections.py                      # Graph JSON to compact result records
│   ├── cursors.py                          # Opaque HMAC-protected pagination cursors
│   ├── untrusted.py                        # Sanitising of third-party text
│   ├── validators.py                       # Shared validation helpers and error format
│   ├── local_files.py                      # Allowed local roots, deny-list, safe file names
│   ├── rate_limit.py                       # Per-account token buckets
│   ├── operations.py                       # Server-side store for asynchronous copy operations
│   ├── observability.py                    # Per-call JSON audit log middleware
│   ├── http_security.py                    # Origin validation, constant-time bearer check
│   ├── resource_cache.py                   # Cache keyed by account and resource, mutation invalidation
│   ├── cache.py                            # Encrypted SQLite cache manager (AES-256, SQLCipher)
│   ├── cache_config.py                     # TTL policies, limits, cache-key generation
│   ├── cache_warming.py                    # Optional startup warming
│   ├── background_worker.py                # Async task queue for cache operations
│   ├── encryption.py                       # Cache key management (keyring, env fallback)
│   ├── logging_config.py                   # Logging setup
│   ├── health_check.py                     # Health check
│   ├── migrations/001_init_cache.sql       # Cache schema
│   ├── services/                           # Graph logic; never imports FastMCP
│   │   ├── accounts.py                     # Account listing, resolution, device-flow orchestration
│   │   ├── calendar.py                     # Events, calendars, availability inputs
│   │   ├── contacts.py                     # Contacts and contact folders
│   │   ├── drive.py                        # OneDrive items, upload, download, copy, share
│   │   ├── mail.py                         # Messages, attachments, reply, forward
│   │   ├── mail_compose.py                 # Draft and send composition
│   │   ├── mail_folders.py                 # Mail folders, mark-all-read, empty
│   │   ├── mail_rules.py                   # Inbox rules
│   │   ├── search.py                       # Per-resource search routing
│   │   └── __init__.py
│   ├── tool_specs/                         # Packaged copy of the specs (generated)
│   │   ├── __init__.py
│   │   ├── index.json
│   │   └── tools/                          # 29 tool JSON files
│   └── tools/
│       ├── __init__.py
│       ├── registry.py                     # build_server(): registers tools from specs, validation pipeline
│       ├── handlers.py                     # Handler and validation-rule registries
│       └── unified/                        # Tool handlers by domain
│           ├── __init__.py
│           ├── common.py                   # Shared helpers
│           ├── mail.py                     # Mail resources of the m365_* tools
│           ├── mail_compose.py             # email_create_draft, email_send, email_reply, email_forward
│           ├── mail_bulk.py                # email_folder_mark_all_read, email_folder_empty
│           ├── mail_rules.py               # email_rule_manage
│           ├── calendar.py                 # Event/calendar resources, calendar_* tools
│           ├── calendar_availability.py    # calendar_find_availability
│           ├── contacts.py                 # Contact resources
│           ├── drive.py                    # Drive resources, drive_upload/copy/share
│           ├── search.py                   # m365_search
│           └── admin.py                    # account_* and admin_* tools
├── tests/
│   ├── conftest.py
│   ├── unified_harness.py                  # Mocked Graph harness for tool tests
│   ├── parity_helpers.py                   # Shared helpers for the parity tests
│   ├── parity_helpers_part2.py
│   ├── fixtures/graph/                     # Graph JSON fixtures
│   ├── test_unified_*.py                   # One module per tool domain (mail, compose, bulk, rules,
│   │                                       #   calendar, availability, contacts, drive, search, admin, common)
│   ├── test_unified_tool_specs.py          # Spec validity, tiers, token budgets, --check
│   ├── test_tool_registry.py               # Live tools/list equals the specs per toolset
│   ├── test_tool_specs_package.py          # Packaged specs equal docs copy; wheel contents
│   ├── test_input_validation.py            # Input pipeline and error format
│   ├── test_output_contract.py             # structuredContent and outputSchema
│   ├── test_sdk_client_conformance.py      # Official MCP SDK client against the server
│   ├── test_parity_part1.py                # Migration table rows 1-43
│   ├── test_parity_part2.py                # Migration table rows 44-85
│   ├── test_services_*.py                  # Service layer tests
│   ├── test_projections.py, test_cursors.py, test_untrusted_content.py, test_local_files.py,
│   │   test_rate_limit.py, test_operations.py, test_observability.py, test_http_security.py,
│   │   test_resource_cache.py, test_registry_caching.py, test_graph_errors.py,
│   │   test_graph_batch.py, test_graph_deadline.py, test_graph_client.py
│   ├── test_account_resolution.py, test_account_validation.py, test_auth_sessions.py,
│   │   test_personal_only_auth.py
│   ├── test_cache.py, test_cache_schema.py, test_cache_warming.py, test_background_worker.py,
│   │   test_encryption.py, test_server_cache_lifecycle.py, test_cache_teardown_scaffolding.py
│   ├── test_validators.py, test_port_cleanup.py, test_windows_path_scaffolding.py
│   ├── test_evals_harness.py               # Offline tests of the evaluation harness
│   ├── test_integration_unified.py         # Live read-only tests (M365_MCP_LIVE_TESTS=1)
│   └── test_services_boundaries.py         # Services never import FastMCP
├── .env.example                            # Environment template with comments
├── .env.http.example                       # HTTP mode configuration example
├── .env.stdio.example                      # stdio mode configuration example
├── .coveragerc
├── .gitattributes
├── .gitignore
├── .python-version
├── 202609_MCP_BEST_PRACTICES_REPORT.md     # Audit that motivated the v1.0.0 design
├── 202609_TASKS.md                         # Active task list
├── AGENTS.md                               # Repository guidelines for coding agents
├── authenticate.py                         # Interactive sign-in (--re-auth, --remove)
├── CHANGELOG.md                            # Changelog with the 1.0.0 migration table
├── CLAUDE.md                               # Claude Code guidance
├── example_mcp.json                        # Example MCP client configuration (HTTP)
├── FILETREE.md                             # This file
├── MCP_BEST_PRACTICES.md                   # External best-practice baseline
├── MCP_SERVER_TOOLS.md                     # Tool reference, generated from the live tools/list
├── mcp_user_experience_report.md           # Earlier diagnostic report (historical)
├── monitor_mcp_server.sh                   # Health monitoring script with auto-recovery
├── pyproject.toml                          # Project configuration and dependencies
├── pyrightconfig.json                      # Type checker configuration
├── QUICKSTART.md                           # Installation and first run
├── README.md                               # Overview, tool list, setup, client configuration
├── SECURITY.md                             # Security guide
├── SQLCIPHER3.md                           # Notes on obtaining SQLCipher wheels
├── start_mcp_with_monitoring.sh            # Server startup with monitoring
├── TASK_ARCHIVE.md                         # Completed tasks with evidence
├── test_mcp_endpoint.sh                    # Manual test of the HTTP endpoint
├── TOOLS.md                                # Reference of tools of other locally installed MCP servers
├── UNIFIED_TOOLS_CONCEPT.md                # Approved design of the 29-tool surface
└── uv.lock                                 # Locked dependency set
```
