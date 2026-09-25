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


def _ask_yes_no(prompt: str) -> bool:
    """Ask a y/n question until the user answers."""
    while True:
        choice = input(prompt).strip().lower()
        if choice in ("y", "n"):
            return choice == "y"
        print("Please enter 'y' or 'n'")


def _check_accounts(auth_module: Any, accounts: list[Any]) -> dict[str, Exception]:
    """Force-refresh each account's token and print whether it works.

    A forced refresh proves the refresh token is still accepted, and also
    restarts its 90-day inactivity window.

    Returns:
        Mapping of account ID to the error for accounts that are not usable.
    """
    problems: dict[str, Exception] = {}
    if not accounts:
        return problems

    print("Checking sign-in status...")
    for account in accounts:
        try:
            auth_module.reauthenticate_account(account.account_id)
        except Exception as exc:  # noqa: BLE001 - report any failure per account
            problems[account.account_id] = exc
            print(f"  ✗ {account.username}: {exc}")
        else:
            print(f"  ✓ {account.username}: sign-in is valid")
    print()
    return problems


def _sign_in(auth_module: Any, expected_username: str | None = None) -> bool:
    """Run device-code sign-in. Return True if the expected account signed in."""
    try:
        new_account = auth_module.authenticate_new_account()
    except Exception as e:
        print(f"\n✗ Authentication failed: {e}")
        return False

    if not new_account:
        print("\n✗ Authentication failed: Could not retrieve account information")
        return False

    print("\n✓ Authentication successful!")
    print(f"Signed in as: {new_account.username}")
    print(f"Account ID: {new_account.account_id}")

    if expected_username and new_account.username.lower() != expected_username.lower():
        print(
            f"\n⚠ You signed in as {new_account.username}, not "
            f"{expected_username}. {expected_username} still needs to sign in."
        )
        return False
    return True


def _handle_re_auth(auth_module: Any, selector: str) -> int:
    """Handle the --re-auth command."""
    account = _select_account(auth_module, selector, "re-authenticate")
    if not account:
        return 1

    print(f"Force-refreshing token for {account.username}...")
    try:
        result = auth_module.reauthenticate_account(account.account_id)
    except RuntimeError as exc:
        print(f"\n✗ Authentication refresh failed: {exc}")
        return 1
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

    # Verify existing accounts and offer to sign in again where needed
    problems = _check_accounts(auth, accounts)
    for account in accounts:
        problem = problems.get(account.account_id)
        if not isinstance(problem, auth.SignInRequiredError):
            continue
        if _ask_yes_no(f"Sign in again as {account.username} now? (y/n): "):
            if _sign_in(auth, account.username):
                problems.pop(account.account_id)
            print()

    # Authenticate new account
    while _ask_yes_no("Do you want to authenticate a new account? (y/n): "):
        _sign_in(auth)
        print()

    # Final account summary
    accounts = auth.list_accounts()
    if not accounts:
        print("\nNo accounts authenticated.")
        return 1

    print("\nAuthenticated accounts summary:")
    print("==============================")
    for account in accounts:
        status = "✗ NOT USABLE" if account.account_id in problems else "✓ ready"
        print(f"• {account.username} [{status}]")
        print(f"  Account ID: {account.account_id}")

    print(
        "\nYou can use these account IDs with any MCP tool by passing account_id parameter."
    )
    print("Example: send_email(..., account_id='<account-id>')")

    if problems:
        print(
            "\n⚠ Some accounts still need attention (see above). "
            "Run this script again to retry."
        )
        return 1

    print("\nAuthentication complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
