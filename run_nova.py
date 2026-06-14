#!/usr/bin/env python3
"""
Script to run the Nova API client for WebSocket connections.

Usage:
  python run_nova.py
"""
import asyncio
import json
import logging
import sys
import traceback
import time
import config
import pandas as pd
from sqlalchemy import create_engine, text
# Import NovaClient from nova_api.client
from nova_api.client import NovaClient
from utils.logger import logger


def get_config():
    """Get configuration from config.py"""
    return {
        'testing': config.get('testing', False),
        'testing_url': config.get('testing_url', '')
    }


def load_config():
    """Load configuration from params.json."""
    try:
        with open('config/params.json', 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Failed to load configuration: {e}")
        return None


def save_to_mysql(address_list):
    """Save address list to MySQL database."""
    try:
        # Debug print to check config contents
        print("Config:", config)

        # Create MySQL connection string from config
        mysql_uri = (
            f"mysql+pymysql://"
            f"{config['mysql']['user']}:{config['mysql']['password']}"
            f"@{config['mysql']['host']}:{config['mysql']['port']}"
            f"/{config['mysql']['database']}"
        )

        # Create SQLAlchemy engine
        engine = create_engine(
            mysql_uri,
            pool_size=config['mysql'].get('pool_size', 5),
            pool_recycle=config['mysql'].get('pool_recycle', 3600),
            connect_args={'connect_timeout': config['mysql'].get('connect_timeout', 10)}
        )

        # Create DataFrame from address list
        df = pd.DataFrame(address_list, columns=['nova_address'])

        # Save to MySQL
        df.to_sql(
            'pool',
            engine,
            if_exists='replace',  # Replace existing table
            index=False,
            chunksize=1000
        )

        logger.info(f"Successfully saved {len(address_list)} addresses to MySQL")

    except Exception as e:
        logger.error(f"Error saving to MySQL: {e}")
        logger.error(traceback.format_exc())


async def socket_connect_nova():
    """Connect to Nova API WebSockets using the NovaClient class."""
    # Load configuration
    logger.info("Loading configuration...")
    config = load_config()

    if not config:
        logger.error("Failed to load config file (params.json)")
        return 1

    # Get API keys from config
    nova_config = config.get('nova_api', {})
    api_key = nova_config.get('access_key')
    api_secret = nova_config.get('secret_key')

    # Get user_uuid from config
    user_uuid = nova_config.get('user_uuid')

    # Override URLs with the correct values
    api_base_url = "https://api.novabtc.io"
    api_ws_url = "wss://api.novabtc.io"
    ws_path = "/zsu/ws/v1"

    if not api_key or not api_secret:
        logger.error("API key or secret not found in configuration")
        return 1

    try:
        # Create a client instance
        client = NovaClient(access_key=api_key, secret_key=api_secret)

        # Override the URLs to use the correct domain
        client.base_url = api_base_url
        client.ws_url = api_ws_url
        client.ws_path = ws_path

        # Set user_uuid if provided, to avoid making the REST API call
        if user_uuid:
            logger.info(f"Using provided user UUID: {user_uuid[:5]}...")
            client._user_uuid = user_uuid

        logger.info(f"Created client with API Key: {api_key[:5]}...")
        logger.info(f"Base URL: {client.base_url}")
        logger.info(f"WebSocket URL: {client.ws_url}")

        # Connect to WebSocket
        logger.info("Connecting to WebSocket...")
        if not client.sio or not client.sio.connected:
            connected = await client.connect_websocket()
            if not connected:
                logger.error("Failed to connect to WebSocket")
                return 1

        logger.info("Connected! Waiting for events...")
        logger.info("Press Ctrl+C to exit")

        # Keep the script running until interrupted
        while client.sio and client.sio.connected:
            await asyncio.sleep(1)

        return 0

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        if client.sio and client.sio.connected:
            await client.disconnect_websocket()
        return 0

    except Exception as e:
        logger.error(f"Error: {e}")
        logger.error(traceback.format_exc())
        if client.sio and client.sio.connected:
            await client.disconnect_websocket()
        return 1


if __name__ == "__main__":

    try:
        config = load_config()
        nova_config = config.get('nova_api', {})
        api_key = nova_config.get('access_key')
        api_secret = nova_config.get('secret_key')
        client = NovaClient(access_key=api_key, secret_key=api_secret)
        address_list = []
        range_i = 100
        address = 'trc20usdt'
        # df = pd.read_csv('address_list.csv')
        # address_list = df['0'].tolist()
        # # Generate deposit addresses
        for i in range(range_i):
            try:
                deposit_address = client.create_deposit_address(address)
                address_list.append(deposit_address["address"])
                logger.info(f"Generated address {i+1}/{range_i}")
            except Exception as e:
                logger.error(f"Error generating address: {e}")
                logger.error(traceback.format_exc())

        pd.DataFrame(
            address_list,
            columns=['nova_address']).to_csv(f'nova_address/address_list_{time.time()}.csv', index=False)
        # # Save addresses to MySQL
        # if address_list:
        # save_to_mysql(address_list)
        # else:
        #     logger.warning("No addresses were generated")

        # logger.info("Initializing NovaClient...")
        # logger.info("Attempting to get member info...")
        # print(1)

    except Exception as e:

        logger.error(f"Uncaught exception: {e}")
        logger.error(traceback.format_exc())
