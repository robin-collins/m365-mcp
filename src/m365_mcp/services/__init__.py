"""Microsoft Graph service layer.

Services hold the Graph logic (URLs, query parameters, pagination, caching
and invalidation) behind plain Python functions. The MCP tool layer in
``m365_mcp.tools`` validates inputs and calls these functions. Services
never import FastMCP.
"""
