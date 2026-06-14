import json
import logging
from typing import Any, Dict, Optional

import config
# Import the client using the full package path
from nova_api.client import NovaClient
from utils.logger import logger


def get_user_info(client: NovaClient) -> Optional[Dict[str, Any]]:
    """Get current user info from Nova API.

    Args:
        client: Initialized NovaClient instance

    Returns:
        Optional[Dict[str, Any]]: User info if successful, None otherwise
    """
    try:
        logger.info("Attempting to get member info...")
        user_info = client.get_members_me()
        logger.info("Successfully retrieved user info")
        return user_info
    except Exception as e:
        logger.error(f"Failed to get user info: {e}")
        return None


def get_markets(client: NovaClient) -> Optional[Dict[str, Any]]:
    """Get list of markets from Nova API.

    Args:
        client: Initialized NovaClient instance

    Returns:
        Optional[Dict[str, Any]]: Markets info if successful, None otherwise
    """
    try:
        logger.info("Attempting to get markets...")
        markets = client.list_markets()
        logger.info("Successfully retrieved markets")
        return markets
    except Exception as e:
        logger.warning(f"Could not retrieve markets: {e}")
        return None


def main():
    """Test the NovaClient with configuration from config.py"""
    try:
        # Get API keys from config
        access_key = config.NOVA_API_ACCESS_KEY
        secret_key = config.NOVA_API_SECRET_KEY

        if not access_key or not secret_key:
            logger.error("Access key or secret key is missing in config")
            return

        # Create an instance of the client
        logger.info("Initializing NovaClient...")
        nova_client = NovaClient(access_key=access_key, secret_key=secret_key)

        # Get user info
        user_info = get_user_info(nova_client)
        if user_info:
            print(json.dumps(user_info, indent=4))

        # Get markets
        markets = get_markets(nova_client)
        if markets:
            print(json.dumps(markets, indent=4))

    except ValueError as e:
        logger.error(f"API request failed: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}", exc_info=True)


if __name__ == "__main__":
    main()
