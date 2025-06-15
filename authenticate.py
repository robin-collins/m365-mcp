#!/usr/bin/env python3
"""Standalone authentication script for Microsoft MCP."""

import os
import sys
from dotenv import load_dotenv
from src.microsoft_mcp import auth

load_dotenv()


def main():
    """Authenticate and cache tokens for Microsoft MCP."""
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print("Error: MICROSOFT_MCP_CLIENT_ID environment variable is required")
        print("Please set it in your .env file or environment")
        sys.exit(1)

    print("Microsoft MCP Authentication")
    print("=" * 40)

    app, cache = auth._build_app()

    # Check for existing accounts
    accounts = app.get_accounts()
    if accounts:
        print(f"\nFound {len(accounts)} existing account(s):")
        for i, account in enumerate(accounts):
            print(f"  {i + 1}. {account['username']}")
        print("\nTo sign in with a new account, continue with the device flow.")
    else:
        print("\nNo existing accounts found.")

    # Start device flow
    print("\nStarting device flow authentication...")
    flow = app.initiate_device_flow(scopes=auth.SCOPES)

    if "user_code" not in flow:
        print("Error: Device flow failed to start")
        print(f"Details: {flow}")
        sys.exit(1)

    print("\n" + "=" * 50)
    print(f"Visit: {flow['verification_uri']}")
    print(f"Enter code: {flow['user_code']}")
    print(f"Expires in: {flow.get('expires_in', 'unknown')} seconds")
    print("=" * 50)

    print("\nWaiting for authentication...")

    try:
        result = app.acquire_token_by_device_flow(flow)

        if "access_token" in result:
            # Save the cache
            auth._save_cache(cache)

            # Get account info
            accounts = app.get_accounts()
            if accounts:
                account = accounts[-1]  # Most recent
                print(f"\n✓ Successfully authenticated as: {account['username']}")
                print(f"  Account ID: {account['home_account_id']}")
            else:
                print("\n✓ Authentication successful!")

            print("\nYou can now run the MCP server and tests.")
        else:
            print(
                f"\n✗ Authentication failed: {result.get('error_description', 'Unknown error')}"
            )
            sys.exit(1)

    except KeyboardInterrupt:
        print("\n\nAuthentication cancelled.")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error during authentication: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
