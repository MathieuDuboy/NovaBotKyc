import asyncio
import logging
import os
from typing import Any, Dict, Optional

# Import with proper package paths
from interlace.client import InterlaceClient
from interlace.exceptions import AuthenticationError, InterlaceError
from utils.logger import logger


def initialize_client() -> Optional[InterlaceClient]:
    """Initialize the InterlaceClient with proper authentication.

    Returns:
        Optional[InterlaceClient]: Initialized client if successful, None otherwise
    """
    try:
        logger.info("Initializing InterlaceClient...")
        client = InterlaceClient()

        # Check if tokens already exist and are potentially valid
        if client.config["access_token"] and not client._is_token_expired():
            logger.info("Existing valid access token found in params.json.")
            return client

        logger.info("No valid access token found or token expired.")
        logger.info("Attempting to generate new token using direct flow...")

        # Generate new tokens using the direct flow
        token_info = client.authentication.generate_access_token()
        logger.info("\n--- New Token Information Received ---")
        logger.info(f"Access Token: {token_info.get('accessToken')}")
        logger.info(f"Refresh Token: {token_info.get('refreshToken')}")
        logger.info(f"Expires In: {token_info.get('expiresIn')}")
        logger.info("\nNew token information has been saved to params.json.")

        return client

    except InterlaceError as auth_err:
        logger.error(f"\nError generating access token: {auth_err}")
        return None
    except Exception as e:
        logger.error(
            f"\nAn unexpected error occurred during client initialization: {e}"
        )
        return None


def get_balances(client: InterlaceClient) -> Optional[Dict[str, Any]]:
    """Get account balances from Interlace API.

    Args:
        client: Initialized InterlaceClient instance

    Returns:
        Optional[Dict[str, Any]]: Balances info if successful, None otherwise
    """
    try:
        logger.info("\n--- Attempting to List Balances ---")
        balances = client.funding.list_all_balances()
        logger.info("Successfully fetched balances")
        return balances
    except InterlaceError as api_err:
        logger.error(f"API call failed: {api_err}")
        if isinstance(api_err, AuthenticationError):
            logger.error(
                "Authentication error during API call. "
                "Token might be invalid or expired."
            )
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting balances: {e}")
        return None


def get_cards(client: InterlaceClient) -> Optional[Dict[str, Any]]:
    """Get list of cards from Interlace API.

    Args:
        client: Initialized InterlaceClient instance

    Returns:
        Optional[Dict[str, Any]]: Cards info if successful, None otherwise
    """
    try:
        logger.info("\n--- Attempting to List Cards ---")
        cards = client.infinity_card.list_all_infinity_cards()
        logger.info("Successfully fetched cards")
        return cards
    except InterlaceError as api_err:
        logger.error(f"API call failed: {api_err}")
        if isinstance(api_err, AuthenticationError):
            logger.error(
                "Authentication error during API call. "
                "Token might be invalid or expired."
            )
        return None
    except Exception as e:
        logger.error(f"Unexpected error getting cards: {e}")
        return None


def main():
    """Demonstrates the direct authentication flow and API usage."""
    try:
        # Initialize client
        client = initialize_client()
        if not client:
            return

        # Get balances
        balances = get_balances(client)
        if balances:
            print(balances)

        # Get cards
        cards = get_cards(client)
        if cards:
            print(cards)

    except InterlaceError as e:
        logger.error(f"\nAn error occurred during API call: {e}")
    except Exception as e:
        logger.error(f"\nAn unexpected error occurred: {e}")


class InterlaceService:
    def __init__(self):
        self.clients: Dict[str, "InterlaceClient"] = {}
        self.running = False

    async def start(self):
        try:
            self.running = True
            logger.info("Successfully started Interlace service")
        except Exception as e:
            logger.error(f"Failed to start Interlace service: {e}")
            raise

    async def stop(self):
        try:
            self.running = False
            for client in self.clients.values():
                await client.close()
            logger.info("Successfully stopped Interlace service")
        except Exception as e:
            logger.error(f"Error stopping Interlace service: {e}")

    async def add_client(self, client_id: str, client: "InterlaceClient"):
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

    async def get_client(self, client_id: str) -> Optional["InterlaceClient"]:
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
