import argparse
import asyncio
import json
import logging
from typing import Dict, Optional

import config
# Import the client using the full package path
from tronscan.client import TronscanClient
from utils.logger import logger


def main():
    """Test the TronscanClient with configuration from config.py"""
    parser = argparse.ArgumentParser(description="Tronscan API Client CLI")
    parser.add_argument("--address", help="TRX address to query", default=None)
    args = parser.parse_args()

    try:
        # Get API key from config
        api_key = config.TRONSCAN_API_KEY
        base_url = config.TRONSCAN_BASE_URL

        if not api_key:
            logger.warning(
                "No API key found in config, some endpoints may be rate-limited"
            )

        # Create an instance of the client
        logger.info("Initializing TronscanClient...")
        client = TronscanClient(api_key=api_key, base_url=base_url)

        # Get API information
        logger.info("Testing TronscanClient connection...")
        system_status = client.get_system_status()
        logger.info(
            "System Status: %s", "Online" if system_status.get("success") else "Offline"
        )

        # If an address was provided, get account information
        if args.address:
            logger.info(f"Getting account information for: {args.address}")
            account_info = client.get_account_info(args.address)
            print(json.dumps(account_info, indent=4))

            # Get token balance for the address
            token_balance = client.get_account_tokens(args.address)
            logger.info(
                f"Token balance retrieved: {len(token_balance.get('data', []))} tokens"
            )

            # Get recent transactions
            transactions = client.get_account_transactions(args.address, limit=5)
            logger.info(
                f"Recent transactions retrieved: {len(transactions.get('data', []))} transactions"
            )
        else:
            # Get latest blocks as a demo
            logger.info("Getting latest blocks...")
            latest_blocks = client.get_latest_blocks(limit=5)
            print(json.dumps(latest_blocks, indent=4))

    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)


class TronscanService:
    def __init__(self):
        self.clients: Dict[str, "TronscanClient"] = {}
        self.running = False

    async def start(self):
        try:
            self.running = True
            logger.info("Successfully started Tronscan service")
        except Exception as e:
            logger.error(f"Failed to start Tronscan service: {e}")
            raise

    async def stop(self):
        try:
            self.running = False
            for client in self.clients.values():
                await client.close()
            logger.info("Successfully stopped Tronscan service")
        except Exception as e:
            logger.error(f"Error stopping Tronscan service: {e}")

    async def add_client(self, client_id: str, client: "TronscanClient"):
        try:
            self.clients[client_id] = client
            logger.info(f"Successfully added client {client_id}")
        except Exception as e:
            logger.error(f"Error adding client {client_id}: {e}")

    async def remove_client(self, client_id: str):
        try:
            if client_id in self.clients:
                await self.clients[client_id].close()
                del self.clients[client_id]
                logger.info(f"Successfully removed client {client_id}")
            else:
                logger.warning(f"Client {client_id} not found")
        except Exception as e:
            logger.error(f"Error removing client {client_id}: {e}")

    async def get_client(self, client_id: str) -> Optional["TronscanClient"]:
        try:
            return self.clients.get(client_id)
        except Exception as e:
            logger.error(f"Error getting client {client_id}: {e}")
            return None

    async def broadcast(self, message: str):
        try:
            for client_id, client in self.clients.items():
                try:
                    await client.send_message(message)
                    logger.info(f"Successfully broadcast message to {client_id}")
                except Exception as e:
                    logger.error(f"Error broadcasting message to {client_id}: {e}")
        except Exception as e:
            logger.error(f"Error broadcasting message: {e}")

    async def process_messages(self):
        try:
            while self.running:
                for client_id, client in self.clients.items():
                    try:
                        message = await client.receive_message()
                        if message:
                            logger.info(f"Received message from {client_id}: {message}")
                            # Process message here
                    except Exception as e:
                        logger.error(f"Error processing message from {client_id}: {e}")
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Error in message processing loop: {e}")
            self.running = False


if __name__ == "__main__":
    main()
