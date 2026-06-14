#!/usr/bin/env python3
"""
Transaction detector for TRON blockchain.
Uses the TronscanClient to monitor transactions for a specific address.
"""

import argparse
import asyncio
import json
import sys
from typing import Any, Dict, List, Optional

from tronscan.client import TronscanClient


async def fetch_transactions(
    address: str,
    limit: int = 20,
    client: Optional[TronscanClient] = None
) -> Dict[str, Any]:
    """
    Fetch transactions for a given address.

    Args:
        address: TRON account address
        limit: Maximum number of transactions to fetch
        client: TronscanClient instance (optional)

    Returns:
        Dictionary with transaction data
    """
    # Create new client if none was provided
    close_client = False
    if client is None:
        client = TronscanClient()
        close_client = True

    try:
        # Using the get_transactions method from TronscanClient
        transactions = await client.get_transactions(
            address=address,
            limit=limit,
            sort="-timestamp",  # Newest first
            count=True
        )
        return transactions
    finally:
        if close_client:
            await client.close()


def format_transaction(tx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format transaction data for display.

    Args:
        tx: Transaction data

    Returns:
        Formatted transaction data
    """
    return {
        "hash": tx.get("hash"),
        "timestamp": tx.get("timestamp"),
        "block": tx.get("block"),
        "from": tx.get("ownerAddress"),
        "to": tx.get("toAddress"),
        "value": tx.get("amount") if tx.get("amount") else 0,
        "type": tx.get("contractType"),
        "status": tx.get("confirmed")
    }


async def main():
    parser = argparse.ArgumentParser(
        description="Monitor TRON transactions for an address")
    parser.add_argument("address", help="TRON account address to monitor")
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=10,
        help="Number of transactions to fetch (default: 10)"
    )
    parser.add_argument(
        "-f", "--format",
        choices=["json", "table"],
        default="table",
        help="Output format (default: table)"
    )
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Watch for new transactions (polls every 30 seconds)"
    )

    args = parser.parse_args()

    client = TronscanClient()

    try:
        seen_txs = set()

        while True:
            try:
                address = args.address
                print(f"Fetching transactions for {address}...")
                data = await fetch_transactions(address, args.limit, client)

                if "error" in data:
                    print(f"Error: {data['error']}")
                    return 1

                transactions = data.get("data", [])
                new_txs = []

                # Find transactions not seen before
                for tx in transactions:
                    tx_hash = tx.get("hash")
                    if tx_hash and tx_hash not in seen_txs:
                        seen_txs.add(tx_hash)
                        new_txs.append(tx)

                if args.format == "json":
                    if new_txs or not args.watch:
                        print(json.dumps(
                            [format_transaction(tx) for tx in new_txs],
                            indent=2
                        ))
                else:  # table format
                    if new_txs or not args.watch:
                        # Print header
                        print("\n{:<20} {:<10} {:<24} {:<24} {:<15}".format(
                            "HASH", "BLOCK", "FROM", "TO", "VALUE"
                        ))
                        print("-" * 95)

                        # Print transactions
                        for tx in new_txs:
                            formatted = format_transaction(tx)
                            from_addr = formatted["from"]
                            to_addr = formatted["to"]

                            print("{:<20} {:<10} {:<24} {:<24} {:<15}".format(
                                formatted["hash"][:18] + "...",
                                formatted["block"],
                                from_addr[:22] + "..." if from_addr else "N/A",
                                to_addr[:22] + "..." if to_addr else "N/A",
                                formatted["value"]
                            ))

                if not args.watch:
                    break

                print("\nWaiting for new transactions... (Ctrl+C to exit)")
                await asyncio.sleep(30)

            except KeyboardInterrupt:
                print("\nExiting...")
                break

    finally:
        await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)
