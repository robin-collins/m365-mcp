#!/usr/bin/env python3
"""
Authenticate Microsoft accounts for use with Microsoft MCP.
Run this script to sign in to one or more Microsoft accounts.
"""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add src to path so we can import our modules
sys.path.insert(0, str(Path(__file__).parent / "src"))

from microsoft_mcp import auth


def main():
    load_dotenv()
    
    if not os.getenv("MICROSOFT_MCP_CLIENT_ID"):
        print("Error: MICROSOFT_MCP_CLIENT_ID environment variable is required")
        print("\nPlease set it in your .env file or environment:")
        print("export MICROSOFT_MCP_CLIENT_ID='your-app-id'")
        sys.exit(1)
    
    print("Microsoft MCP Authentication")
    print("============================\n")
    
    # List current accounts
    accounts = auth.list_accounts()
    if accounts:
        print("Currently authenticated accounts:")
        for i, account in enumerate(accounts, 1):
            print(f"{i}. {account.username} (ID: {account.account_id})")
        print()
    else:
        print("No accounts currently authenticated.\n")
    
    # Authenticate new account
    while True:
        choice = input("Do you want to authenticate a new account? (y/n): ").lower()
        if choice == 'n':
            break
        elif choice == 'y':
            print("\nAuthenticating new account...")
            print("You'll be prompted to visit a URL and enter a code.")
            
            try:
                # This will trigger device code flow
                token = auth.get_token()
                print("\n✓ Authentication successful!")
                
                # Show updated account list
                accounts = auth.list_accounts()
                if accounts:
                    new_account = accounts[-1]  # Most recent is usually last
                    print(f"Signed in as: {new_account.username}")
                    print(f"Account ID: {new_account.account_id}")
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
        
        print("\nYou can use these account IDs with any MCP tool by passing account_id parameter.")
        print("Example: send_email(..., account_id='<account-id>')")
    else:
        print("\nNo accounts authenticated.")
    
    print("\nAuthentication complete!")


if __name__ == "__main__":
    main()