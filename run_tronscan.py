#!/usr/bin/env python3
"""
Script to run the Tronscan API client for monitoring token transfers.

Usage:
  python run_tronscan.py
"""
import argparse
import asyncio
import json
import logging
import platform
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Import configuration
try:
    import config
    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False

# Import from the package
from tronscan.client import TronscanClient
from utils.logger import logger

# Setup basic logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


async def get_transfers(
    address: str,
    limit: int = 20,
    start: int = 0,
    client: Optional[TronscanClient] = None
) -> Dict[str, Any]:
    """
    Fetch token transfers for a given address.

    Args:
        address: TRON account address
        limit: Maximum number of transfers to fetch
        start: Starting index for pagination
        client: TronscanClient instance (optional)

    Returns:
        Dictionary with transfer data
    """
    # Create new client if none was provided
    close_client = False
    if client is None:
        client = TronscanClient()
        close_client = True

    try:
        # Using the get_transfers method from TronscanClient
        transfers = await client.get_transfers(
            address=address,
            limit=limit,
            start=start,
            sort="-timestamp"  # Newest first
        )
        return transfers
    finally:
        if close_client:
            await client.close()


async def get_transaction_info(
    tx_hash: str,
    client: Optional[TronscanClient] = None
) -> Dict[str, Any]:
    """
    Get detailed information about a specific transaction.

    Args:
        tx_hash: Transaction hash
        client: TronscanClient instance (optional)

    Returns:
        Dictionary with transaction details
    """
    # Create new client if none was provided
    close_client = False
    if client is None:
        client = TronscanClient()
        close_client = True

    try:
        # Using the get_transaction_info method from TronscanClient
        tx_info = await client.get_transaction_info(hash=tx_hash)
        return tx_info
    finally:
        if close_client:
            await client.close()


async def get_trc20_transfers(
    address: str,
    limit: int = 20,
    start: int = 0,
    client: Optional[TronscanClient] = None
) -> Dict[str, Any]:
    """
    Fetch TRC20 token transfers for a given address.

    Args:
        address: TRON account address
        limit: Maximum number of transfers to fetch
        start: Starting index for pagination
        client: TronscanClient instance (optional)

    Returns:
        Dictionary with TRC20 transfer data
    """
    # Create new client if none was provided
    close_client = False
    if client is None:
        client = TronscanClient()
        close_client = True

    try:
        # Using direct API call since there's no specific method in TronscanClient
        # for TRC20 transfers
        endpoint = "token_trc20/transfers"
        params = {
            "limit": limit,
            "start": start,
            "sort": "-timestamp",
            "relatedAddress": address
        }
        return await client._request(endpoint, params)
    finally:
        if close_client:
            await client.close()


def format_timestamp(timestamp: Optional[int]) -> str:
    """
    Convert a Unix timestamp (milliseconds) to a human-readable date string.

    Args:
        timestamp: Unix timestamp in milliseconds

    Returns:
        Human-readable date string
    """
    if not timestamp:
        return "N/A"

    try:
        # Convert milliseconds to seconds for datetime
        dt = datetime.fromtimestamp(timestamp / 1000)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError):
        return "Invalid timestamp"


def format_transfer(transfer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format transfer data for display.

    Args:
        transfer: Transfer data

    Returns:
        Formatted transfer data
    """
    timestamp = transfer.get("timestamp")

    # Log raw transfer data for debugging
    logger.debug(f"Raw transfer data: {json.dumps(transfer, indent=2)}")

    return {
        "hash": transfer.get("transactionHash"),
        "timestamp": timestamp,
        "datetime": format_timestamp(timestamp),
        "block": transfer.get("block"),
        "from": transfer.get("transferFromAddress"),
        "to": transfer.get("transferToAddress"),
        "amount": transfer.get("amount", 0),
        "token_name": transfer.get("tokenName"),
        "token_id": transfer.get("tokenId", ""),
        "status": transfer.get("confirmed", False)
    }


def format_trc20_transfer(transfer: Dict[str, Any]) -> Dict[str, Any]:
    """
    Format TRC20 transfer data for display.

    Args:
        transfer: TRC20 Transfer data

    Returns:
        Formatted transfer data
    """
    timestamp = transfer.get("block_ts")

    # Log raw transfer data for debugging
    logger.debug(f"Raw TRC20 transfer data: {json.dumps(transfer, indent=2)}")

    # Convert amount based on decimals
    amount = transfer.get("quant", "0")
    decimals = transfer.get("token_info", {}).get("decimals", 0)
    if decimals and amount:
        try:
            # Format with proper decimal places
            amount_float = float(amount) / (10 ** int(decimals))
            amount = f"{amount_float:.{decimals}f}"
        except (ValueError, TypeError):
            pass

    return {
        "hash": transfer.get("transaction_id"),
        "timestamp": timestamp,
        "datetime": format_timestamp(timestamp),
        "block": transfer.get("block"),
        "from": transfer.get("from_address"),
        "to": transfer.get("to_address"),
        "amount": amount,
        "token_name": transfer.get("token_info", {}).get("symbol", ""),
        "token_id": transfer.get("contract_address", ""),
        "status": True  # TRC20 transfers are confirmed
    }


async def async_main():
    """Run the Tronscan client with async/await support"""
    parser = argparse.ArgumentParser(
        description="Monitor TRON token transfers for an address"
    )
    parser.add_argument(
        "--address",
        help="TRX address to monitor",
        default=None
    )
    parser.add_argument(
        "-l", "--limit",
        type=int,
        default=10,
        help="Number of transfers to fetch (default: 10)"
    )
    parser.add_argument(
        "-s", "--start",
        type=int,
        default=0,
        help="Starting index for pagination (default: 0)"
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
        help="Watch for new transfers (polls every 30 seconds)"
    )
    parser.add_argument(
        "-t", "--token",
        help="Filter by token name or ID",
        default=None
    )
    parser.add_argument(
        "--tx",
        help="Look up a specific transaction hash",
        default=None
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--trc20-only",
        action="store_true",
        help="Only show TRC20 token transfers"
    )
    parser.add_argument(
        "--all-transfers",
        action="store_true",
        help="Show both regular and TRC20 transfers"
    )

    args = parser.parse_args()

    # Set log level based on verbosity
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.info("Verbose logging enabled")

    # Check for address or transaction hash
    if not args.address and not args.tx:
        parser.error("Please provide either an address (--address) or "
                     "a transaction hash (--tx)")
        return 1

    # Get configuration if available
    api_key = None
    base_url = None
    if HAS_CONFIG:
        api_key = getattr(config, "TRONSCAN_API_KEY", None)
        base_url = getattr(config, "TRONSCAN_BASE_URL", None)

        if not api_key:
            logger.warning(
                "No API key found in config, some endpoints may be limited"
            )

    # Create client instance
    client = TronscanClient(api_key=api_key, base_url=base_url)

    try:
        # Test connection first
        logger.info("Testing TronscanClient connection...")
        system_status = await client.get_system_status()
        logger.info(
            "System Status: %s",
            "Online" if system_status.get("success") else "Offline"
        )

        # If a specific transaction hash is provided, look it up
        if args.tx:
            logger.info(f"Looking up transaction: {args.tx}")
            tx_info = await get_transaction_info(args.tx, client)

            if "error" in tx_info:
                logger.error(f"Error: {tx_info['error']}")
                return 1

            print(json.dumps(tx_info, indent=2))

            # Also try to get this transaction via different methods
            logger.info("Trying to find transaction in transfers...")
            # If address is also provided, try to find this tx in their transfers
            if args.address:
                transfers_data = await get_transfers(args.address, 50, 0, client)
                if "data" in transfers_data:
                    transfers = transfers_data.get("data", [])
                    for transfer in transfers:
                        if transfer.get("transactionHash") == args.tx:
                            logger.info("Found transaction in transfers!")
                            print(json.dumps(transfer, indent=2))
                            return 0
                    logger.info("Transaction not found in first 50 transfers")
            return 0

        # Normal operation for monitoring an address
        address = args.address
        logger.info(f"Monitoring token transfers for: {address}")
        if args.token:
            logger.info(f"Filtering by token: {args.token}")

        # Determine which type of transfers to fetch
        fetch_regular = not args.trc20_only
        fetch_trc20 = args.trc20_only or args.all_transfers

        if args.trc20_only:
            logger.info("Fetching only TRC20 token transfers")
        elif args.all_transfers:
            logger.info("Fetching both regular and TRC20 token transfers")

        seen_txs = set()

        while True:
            try:
                all_transfers = []

                # Fetch regular transfers if needed
                if fetch_regular:
                    logger.info(f"Fetching regular transfers for {address}...")
                    logger.info(f"Using limit={args.limit}, start={args.start}")
                    data = await get_transfers(address, args.limit, args.start, client)

                    if "error" in data:
                        logger.error(
                            f"Error fetching regular transfers: {data['error']}")
                    else:
                        # Log full API response in debug mode
                        logger.debug(
                            f"Regular transfers API Response: {json.dumps(data, indent=2)}")

                        total_count = data.get("total", 0)
                        logger.info(f"Total regular transfers found: {total_count}")

                        transfers = data.get("data", [])
                        logger.info(
                            f"Received {len(transfers)} regular transfers in this batch")

                        # Add to combined list
                        for transfer in transfers:
                            all_transfers.append(("regular", transfer))

                # Fetch TRC20 transfers if needed
                if fetch_trc20:
                    logger.info(f"Fetching TRC20 transfers for {address}...")
                    logger.info(f"Using limit={args.limit}, start={args.start}")
                    trc20_data = await get_trc20_transfers(address, args.limit, args.start, client)

                    if "error" in trc20_data:
                        logger.error(
                            f"Error fetching TRC20 transfers: {trc20_data['error']}")
                    else:
                        # Log full API response in debug mode
                        logger.debug(
                            f"TRC20 transfers API Response: {json.dumps(trc20_data, indent=2)}")

                        total_count = trc20_data.get("total", 0)
                        logger.info(f"Total TRC20 transfers found: {total_count}")

                        trc20_transfers = trc20_data.get("token_transfers", [])
                        logger.info(
                            f"Received {len(trc20_transfers)} TRC20 transfers in this batch")

                        # Add to combined list
                        for transfer in trc20_transfers:
                            all_transfers.append(("trc20", transfer))

                # Process all transfers
                new_transfers = []

                # Sort combined transfers by timestamp (newest first)
                def get_timestamp(transfer_tuple):
                    transfer_type, transfer = transfer_tuple
                    if transfer_type == "regular":
                        return transfer.get("timestamp", 0)
                    else:  # trc20
                        return transfer.get("block_ts", 0)

                all_transfers.sort(key=get_timestamp, reverse=True)

                # Find transfers not seen before
                for transfer_type, transfer in all_transfers:
                    tx_hash = (
                        transfer.get("transactionHash")
                        if transfer_type == "regular"
                        else transfer.get("transaction_id")
                    )

                    if tx_hash and tx_hash not in seen_txs:
                        # Format token name and ID based on transfer type
                        if transfer_type == "regular":
                            token_name = transfer.get("tokenName")
                            token_id = transfer.get("tokenId", "")
                        else:  # trc20
                            token_name = transfer.get(
                                "token_info", {}).get(
                                "symbol", "")
                            token_id = transfer.get("contract_address", "")

                        logger.debug(f"Checking {transfer_type} transfer: {tx_hash}, "
                                     f"token: {token_name} ({token_id})")

                        # Filter by token if specified
                        if args.token and args.token not in (token_name, token_id):
                            logger.debug(f"Skipping transfer (token mismatch)")
                            continue

                        seen_txs.add(tx_hash)
                        new_transfers.append((transfer_type, transfer))

                if new_transfers:
                    logger.info(f"Found {len(new_transfers)} new transfers")

                if args.format == "json":
                    if new_transfers or not args.watch:
                        formatted_transfers = []
                        for transfer_type, transfer in new_transfers:
                            if transfer_type == "regular":
                                formatted_transfers.append(format_transfer(transfer))
                            else:  # trc20
                                formatted_transfers.append(
                                    format_trc20_transfer(transfer))

                        print(json.dumps(formatted_transfers, indent=2))
                else:  # table format
                    if new_transfers or not args.watch:
                        # Print header
                        header = "\n{:<20} {:<19} {:<10} {:<22} {:<22}"
                        header += " {:<15} {:<10} {:<5}"
                        print(header.format(
                            "HASH", "DATETIME", "BLOCK", "FROM", "TO",
                            "AMOUNT", "TOKEN", "TYPE"
                        ))
                        print("-" * 120)

                        # Print transfers
                        for transfer_type, transfer in new_transfers:
                            if transfer_type == "regular":
                                formatted = format_transfer(transfer)
                            else:  # trc20
                                formatted = format_trc20_transfer(transfer)

                            from_addr = formatted["from"]
                            to_addr = formatted["to"]

                            tx_row = "{:<20} {:<19} {:<10} {:<22} {:<22}"
                            tx_row += " {:<15} {:<10} {:<5}"
                            print(tx_row.format(
                                formatted["hash"][:18] + "...",
                                formatted["datetime"],
                                formatted["block"],
                                from_addr[:20] + "..." if from_addr else "N/A",
                                to_addr[:20] + "..." if to_addr else "N/A",
                                formatted["amount"],
                                formatted["token_name"],
                                transfer_type.upper()
                            ))

                if not args.watch:
                    break

                logger.info("Waiting for new transfers... (Ctrl+C to exit)")
                await asyncio.sleep(30)

            except KeyboardInterrupt:
                logger.info("Exiting...")
                break

    finally:
        await client.close()


def main():
    """Entry point for the script"""
    try:
        # Fix for Windows asyncio event loop issues
        if platform.system() == 'Windows':
            # Set event loop policy for Windows
            policy = asyncio.WindowsSelectorEventLoopPolicy()
            asyncio.set_event_loop_policy(policy)
            # For Python 3.8+ on Windows
            asyncio.run(async_main())
        else:
            # For other platforms
            asyncio.run(async_main())

    except KeyboardInterrupt:
        logger.info("Exiting...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    # Make sure all tasks complete properly before exiting
    try:
        main()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
