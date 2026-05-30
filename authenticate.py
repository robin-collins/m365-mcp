#!/usr/bin/env python3
"""
Authenticate Microsoft accounts for use with M365 MCP.
Run this script to sign in to one or more Microsoft accounts.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv


def _parse_arguments() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Authenticate Microsoft accounts for M365 MCP"
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (default: .env)",
    )
    account_group = parser.add_mutually_exclusive_group()
    account_group.add_argument(
        "--re-auth",
        nargs="?",
        const="",
        metavar="ACCOUNT",
        help=(
            "Force-refresh an existing account's Graph token. ACCOUNT can be "
            "an account ID or username; omit it to select interactively."
        ),
    )
    account_group.add_argument(
        "--remove",
        nargs="?",
        const="",
        metavar="ACCOUNT",
        help=(
            "Remove a configured account, its cached tokens, and its database "
            "cache rows. ACCOUNT can be an account ID or username; omit it to "
            "select interactively."
        ),
    )
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts for --remove.",
    )
    return parser.parse_args()


def _print_accounts(accounts: list[Any]) -> None:
    """Print configured accounts for the CLI."""
    if accounts:
        print("Currently authenticated accounts:")
        for i, account in enumerate(accounts, 1):
            print(f"{i}. {account.username} (ID: {account.account_id})")
        print()
    else:
        print("No accounts currently authenticated.\n")


def _match_account(accounts: list[Any], selector: str) -> Any | None:
    """Find an account by exact account ID or username."""
    selector_normalized = selector.lower()
    for account in accounts:
        if account.account_id.lower() == selector_normalized:
            return account
        if account.username.lower() == selector_normalized:
            return account
    return None


def _select_account(auth_module: Any, selector: str, action: str) -> Any | None:
    """Select a configured account for an account-specific CLI action."""
    accounts = auth_module.list_accounts()
    if not accounts:
        print("No accounts are configured.")
        return None

    if selector:
        account = _match_account(accounts, selector)
        if not account:
            print(f"No account matched: {selector}")
            return None
        return account

    if len(accounts) == 1:
        return accounts[0]

    print(f"Select an account to {action}:")
    for i, account in enumerate(accounts, 1):
        print(f"{i}. {account.username} (ID: {account.account_id})")

    while True:
        choice = input("Enter number, account ID, or username: ").strip()
        if not choice:
            print("Please enter a selection.")
            continue
        if choice.isdigit():
            index = int(choice)
            if 1 <= index <= len(accounts):
                return accounts[index - 1]
        account = _match_account(accounts, choice)
        if account:
            return account
        print("Selection did not match a configured account.")


def _handle_re_auth(auth_module: Any, selector: str) -> int:
    """Handle the --re-auth command."""
    account = _select_account(auth_module, selector, "re-authenticate")
    if not account:
        return 1

    print(f"Force-refreshing token for {account.username}...")
    result = auth_module.reauthenticate_account(account.account_id)
    print("\nAuthentication refresh successful!")
    print(f"Account: {result.account.username}")
    print(f"Account ID: {result.account.account_id}")
    if result.expires_in is not None:
        print(f"New token lifetime: {result.expires_in} seconds")
    return 0


def _handle_remove(auth_module: Any, selector: str, skip_confirmation: bool) -> int:
    """Handle the --remove command."""
    account = _select_account(auth_module, selector, "remove")
    if not account:
        return 1

    if not skip_confirmation:
        confirmation = input(
            f"Remove {account.username} and its cached tokens/data? (y/n): "
        ).lower()
        if confirmation != "y":
            print("Account removal cancelled.")
            return 0

    result = auth_module.remove_account(account.account_id)
    print("\nAccount removed.")
    print(f"Account: {result.account.username}")
    print(f"Account ID: {result.account.account_id}")
    print(f"Token cache updated: {'yes' if result.token_cache_removed else 'no'}")
    print(f"Metadata removed: {'yes' if result.metadata_removed else 'no'}")
    cache_counts = result.database_cache_removed
    print(
        "Database cache rows removed: "
        f"{sum(cache_counts.values())} "
        f"({', '.join(f'{key}={value}' for key, value in cache_counts.items())})"
    )
    return 0


def main() -> int:
    # Parse arguments first to get env file path
    args = _parse_arguments()

    # Load environment variables from custom path
    env_file = args.env_file
    if env_file.exists():
        load_dotenv(dotenv_path=env_file)
        print(f"Loaded environment from: {env_file}\n")
    else:
        print(f"Warning: Environment file not found: {env_file}")
        print("Continuing with system environment variables...\n")

    os.environ["M365_MCP_INTERACTIVE_AUTH"] = "true"

    # Import auth module after loading environment
    from m365_mcp import auth

    if not os.getenv("M365_MCP_CLIENT_ID"):
        print("Error: M365_MCP_CLIENT_ID environment variable is required")
        print("\nPlease set it in your .env file or environment:")
        print("export M365_MCP_CLIENT_ID='your-app-id'")
        sys.exit(1)

    print("M365 MCP Authentication")
    print("============================\n")

    # List current accounts
    accounts = auth.list_accounts()
    _print_accounts(accounts)

    re_auth_selector = getattr(args, "re_auth", None)
    remove_selector = getattr(args, "remove", None)
    skip_confirmation = getattr(args, "yes", False)

    if re_auth_selector is not None:
        return _handle_re_auth(auth, re_auth_selector)

    if remove_selector is not None:
        return _handle_remove(auth, remove_selector, skip_confirmation)

    # Authenticate new account
    while True:
        choice = input("Do you want to authenticate a new account? (y/n): ").lower()
        if choice == "n":
            break
        elif choice == "y":
            try:
                # Use the new authentication function
                new_account = auth.authenticate_new_account()

                if new_account:
                    print("\n✓ Authentication successful!")
                    print(f"Signed in as: {new_account.username}")
                    print(f"Account ID: {new_account.account_id}")
                else:
                    print(
                        "\n✗ Authentication failed: Could not retrieve account information"
                    )
            except Exception as e:
                print(f"\n✗ Authentication failed: {e}")
                continue

            print()
        else:
            print("Please enter 'y' or 'n'")

    # Final account summary
    accounts = auth.list_accounts()
    if accounts:
        print("\nAuthenticated accounts summary:")
        print("==============================")
        for account in accounts:
            print(f"• {account.username}")
            print(f"  Account ID: {account.account_id}")

        print(
            "\nYou can use these account IDs with any MCP tool by passing account_id parameter."
        )
        print("Example: send_email(..., account_id='<account-id>')")
    else:
        print("\nNo accounts authenticated.")

    print("\nAuthentication complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
