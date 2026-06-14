"""
Usage examples for the Tronscan API client.

This module contains examples of how to use the TronscanClient.
"""

import asyncio
import json

from client import TronscanClient


async def main():
    """Run examples of TronscanClient usage."""
    # Initialize client
    client = TronscanClient()
    print(f"Initialized client with API key: {client.api_key}")

    try:
        # Example 1: Get system status
        print("\n=== Example 1: Get System Status ===")
        system_status = await client.get_system_status()
        print(json.dumps(system_status, indent=2))

        # Example 2: Get latest block
        print("\n=== Example 2: Get Latest Block ===")
        latest_block = await client.get_latest_block()
        print(f"Latest block number: {latest_block.get('number')}")
        print(f"Timestamp: {latest_block.get('timestamp')}")

        # Example 3: Get account information for a specific address
        # Using a well-known TRON address as an example
        print("\n=== Example 3: Get Account Information ===")
        address = "TGjgvdTWWrybVLaVeFqSxsM6evWgCrZHgH"  # Example address
        account_info = await client.get_account(address)
        print(f"Account balance: {account_info.get('balance', 'Not available')}")

        # Example 4: Get transactions for an account
        print("\n=== Example 4: Get Account Transactions ===")
        transactions = await client.get_transactions(address, limit=5)
        print(f"Total transactions: {transactions.get('total')}")
        for i, tx in enumerate(transactions.get('data', [])[:3]):  # Show first 3
            print(f"Transaction {i+1} - Hash: {tx.get('hash')}")
            print(f"  Timestamp: {tx.get('timestamp')}")
            print(f"  Type: {tx.get('contractType')}")

        # Example 5: Get token list
        print("\n=== Example 5: Get Token List ===")
        tokens = await client.get_token_list(limit=5)
        for i, token in enumerate(tokens.get('tokens', [])[:3]):  # Show first 3
            print(f"Token {i+1} - Name: {token.get('name')}")
            print(f"  Symbol: {token.get('tokenAbbr')}")
            print(f"  Issue time: {token.get('dateCreated')}")

    except Exception as e:
        print(f"Error in examples: {e}")
    finally:
        # Always close the client session
        await client.close()


def run_sync_examples():
    """Run synchronous examples of TronscanClient usage."""
    # Initialize client
    client = TronscanClient()
    print(f"Initialized client with API key: {client.api_key}")

    try:
        # Example 1: Get latest block using synchronous method
        print("\n=== Sync Example 1: Get Latest Block ===")
        latest_block = client.get_latest_block_sync()
        print(f"Latest block number: {latest_block.get('number')}")

        # Example 2: Get account information using synchronous method
        print("\n=== Sync Example 2: Get Account Information ===")
        address = "TGjgvdTWWrybVLaVeFqSxsM6evWgCrZHgH"  # Example address
        account_info = client.get_account_sync(address)
        print(f"Account balance: {account_info.get('balance', 'Not available')}")

    except Exception as e:
        print(f"Error in sync examples: {e}")


if __name__ == "__main__":
    # Run async examples
    asyncio.run(main())

    # Run sync examples
    run_sync_examples()
