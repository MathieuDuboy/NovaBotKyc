import asyncio
import base64
import hashlib
import hmac
import json
import logging
import math
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional, Union
from urllib.parse import urlencode
import random
import requests
import socketio  # Use socketio for WebSockets
import websockets
from pymongo import MongoClient

# Import our central config module
import config
from interlace.client import InterlaceClient
from interlace.exceptions import InterlaceError
from services.mongo_service import MongoClientWrapper
from services.mysql_service import mysql_client
from services.sheets_service import (get_fees_for_user, get_user_from_sheet,
                                     initialize_sheets_service)
from telegram_bot.messaging import telegram_messaging
from utils.interlace_utils import InterlaceClient
from utils.logger import logger


# Add a helper to check if we're in testing mode
TESTING = config.TESTING_MODE
TESTING_URL = config.TESTING_URL
INTERLACE_ADDRESS = config.INTERLACE_ADDRESS
MIN_DEPOSIT_AMOUNT = config.NOVA_DEPOSITS_CONFIG.get("min", 100)
MAX_DEPOSIT_AMOUNT = config.NOVA_DEPOSITS_CONFIG.get("max", 10000)

# --- Helper Functions for REST Signature (from docs) ---


def _flatten_object(obj, parent_key="", res=None):
    """Recursively flattens a nested dictionary."""
    if res is None:
        res = {}
    for key, value in obj.items():
        prop_name = f"{parent_key}_{key}" if parent_key else key
        if isinstance(value, dict):
            _flatten_object(value, prop_name, res)
        else:
            # Ensure value is string for consistent signing
            res[prop_name] = str(value)
    return res


def _object_to_query_string(obj):
    """Converts a dictionary to a sorted, encoded query string."""
    if not obj:
        return ""
    flat_object = _flatten_object(obj)
    sorted_keys = sorted(flat_object.keys())
    query_params = [f"{key}={flat_object[key]}" for key in sorted_keys]
    return "&".join(query_params)


class NovaClient:
    """
    Client for interacting with the NovaBtc API v2 (REST & WebSocket).

    Handles API key authentication and signature generation.
    Requires `requests` and `python-socketio[client]`.
    """

    # Class constants will be overridden by instance values
    WS_PATH = "/zsu/ws/v1"  # Default path

    def __init__(
        self,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        test_mode: bool = False,
        mongo_client_instance=None,
    ):
        """
        Initialize Nova API client.

        Args:
            access_key: API access key. If None, loads from config
            secret_key: API secret key. If None, loads from config
            test_mode: Whether to run in test mode (no real trades)
            mongo_client_instance: Optional MongoDB client instance
        """
        self.access_key = access_key or self._load_access_key()
        self.secret_key = secret_key or self._load_secret_key()

        if not (self.access_key and self.secret_key):
            logger.warning("Missing API credentials. Some methods will not work.")

        self.test_mode = test_mode
        self.base_url = self._load_base_url()
        self.ws_url = self._load_ws_url()
        # Use the WS_PATH from config
        self.ws_path = config.NOVA_API_WS_PATH
        self.session = requests.Session()
        self.ws_connection = None
        self.ws_subscriptions = {}
        self.last_recv_time = time.time()
        self.ping_interval = 20  # seconds
        self.pong_timeout = 10  # seconds
        self.api_version = "v1"
        self.sio = None  # Socket.IO client instance
        self._is_ws_connecting = False
        self._ws_connection_lock = asyncio.Lock() if asyncio else None
        self._user_uuid = None  # Add missing attribute
        self.mongo_client_instance = mongo_client_instance

    def _load_access_key(self) -> Optional[str]:
        """Load API access key from config"""
        # Use the central config constants
        return config.NOVA_API_ACCESS_KEY

    def _load_secret_key(self) -> Optional[str]:
        """Load API secret key from config"""
        # Use the central config constants
        return config.NOVA_API_SECRET_KEY

    def _load_base_url(self) -> str:
        """Load base URL from config, or use default"""
        # Use the central config constants
        return config.NOVA_API_BASE_URL

    def _load_ws_url(self) -> str:
        """Load WebSocket URL from config, or use default"""
        # Use the central config constants
        return config.NOVA_API_WS_URL

    # --- REST API Handling ---

    def _make_request(
        self,
        method: str,
        endpoint: str,
        query_params: dict = None,
        body_data: dict = None,
    ):
        """
        Makes an authenticated REST request to the Nova API.

        Handles signature generation based on provided documentation.
        """
        http_method_upper = method.upper()
        canonical_uri = endpoint

        # Generate canonical_query based on method
        if http_method_upper == "GET":
            # Use query parameters for GET signature
            canonical_query = _object_to_query_string(query_params)
        elif http_method_upper in ["POST", "PUT", "PATCH", "DELETE"]:
            # Use body parameters for other methods' signature
            canonical_query = _object_to_query_string(body_data)
        else:
            canonical_query = ""

        # Construct the string to sign (using format from Python example)
        # Docs text mentions adding access_key here, but example doesn't.
        # Following example as APISign likely doesn't include the key itself.
        canonical_string = f"{http_method_upper}|{canonical_uri}|{canonical_query}"
        logger.debug(f"Canonical string for REST signing: '{canonical_string}'")

        # Generate the signature
        signature = hmac.new(
            self.secret_key.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        logger.debug(f"Generated REST signature: '{signature}'")

        # Prepare headers
        headers = {
            "accept": "application/json",
            "APIKey": self.access_key,
            "APISign": signature,
        }
        if http_method_upper in ["POST", "PUT", "PATCH"] and body_data:
            # Ensure Content-Type for requests with bodies
            headers["Content-Type"] = "application/json"

        # Construct the full URL
        url = self.base_url + canonical_uri

        response = None
        try:
            log_msg = (
                f"Making {http_method_upper} request to {url} "
                f"with headers: {headers}, params: {query_params}, "
                f"json: {body_data}"
            )
            logger.debug(log_msg)

            # Use requests.request for flexibility
            response = requests.request(
                method=http_method_upper,
                url=url,
                headers=headers,
                params=query_params,  # Let requests handle GET params
                json=body_data,  # Send body as JSON for POST/PUT etc.
            )
            response.raise_for_status()  # Raise HTTPError for bad responses

            if not response.text:
                logger.warning(f"Received empty response for {method} {endpoint}")
                return None

            return response.json()

        except requests.exceptions.HTTPError as http_err:
            log_resp_text = response.text if response else "No response body"
            status_code = response.status_code if response else "N/A"
            logger.error(
                f"HTTP error {status_code} occurred: {http_err} - "
                f"Response: {log_resp_text}"
            )
            try:
                error_data = response.json()
                msg = error_data.get("message", log_resp_text)
                err_val = f"API Error ({status_code}): {msg}"
                raise ValueError(err_val) from http_err
            except (json.JSONDecodeError, AttributeError):
                reason = response.reason if response else "Unknown"
                err_msg = (
                    f"API Error: {status_code} {reason}. "
                    f"Response body: {log_resp_text}"
                )
                raise ValueError(err_msg) from http_err
        except requests.exceptions.RequestException as req_err:
            logger.error(f"Request exception occurred: {req_err}")
            raise ValueError(f"Network or request error: {req_err}") from req_err
        except json.JSONDecodeError as json_err:
            log_resp_text = response.text if response else "No response body"
            logger.error(
                f"Failed to decode JSON response: {json_err} - "
                f"Response: {log_resp_text}"
            )
            raise ValueError(f"Invalid JSON response: {log_resp_text}") from json_err

    # --- Authenticated Account Methods ---

    async def _ensure_user_uuid(self):
        """Fetches user_uuid if not already available."""
        if self._user_uuid:
            return self._user_uuid

        logger.info("User UUID not provided, fetching via get_members_me...")
        try:
            # Assume _make_request is thread-safe if called from async context
            user_info = self.get_members_me()  # Call the sync method
            if user_info and "uuid" in user_info:
                self._user_uuid = user_info["uuid"]
                logger.info(f"Fetched User UUID: {self._user_uuid}")
                return self._user_uuid
            else:
                err_msg = "Failed to fetch user_uuid from /members/me."
                raise ValueError(err_msg)
        except Exception as e:
            logger.error(f"Error fetching user_uuid: {e}")
            err_msg = "Could not obtain user_uuid for WebSocket auth."
            raise ValueError(err_msg) from e

    # --- Members Methods ---

    def get_members_me(self):
        """
        Retrieves information about the currently authenticated user.
        Corresponds to GET /api/v2/members/me
        Returns user's 'uuid' needed for WebSocket authentication.
        """
        return self._make_request(method="GET", endpoint="/api/v2/members/me")

    def get_total_balance(self, output_asset: str = "usdt"):
        """
        Retrieves the total account balance estimated in a specific asset.
        Corresponds to GET /api/v2/members/total_balance

        Args:
            output_asset: The asset to represent the total balance in (default: usdt).
        """
        endpoint = "/api/v2/members/total_balance"
        params = {"output_asset": output_asset}
        # Signature uses query_params for GET
        return self._make_request(method="GET", endpoint=endpoint, query_params=params)

    # --- Deposit Addresses Methods ---

    def list_deposit_addresses(self) -> dict:
        """Retrieves list of all deposit addresses
        Corresponds to GET /api/v2/deposit_addresses
        """
        return self._make_request("GET", "/api/v2/deposit_addresses")

    def create_deposit_address(self, dchain: str) -> dict:
        """Requests/create a deposit address for a specific chain
        Args:
            dchain: The deposit chain identifier (e.g., 'usdt')
        """
        return self._make_request(
            method="POST",
            endpoint="/api/v2/deposit_addresses",
            body_data={"dchain": dchain},
        )

    def delete_deposit_address(self, address: str) -> bool:
        """Stub for deleting a deposit address. Not implemented yet in Nova API."""
        try:
            # This is a stub. Replace with real API call when available.
            logger.warning(
                f"delete_deposit_address called for {address}, but not implemented."
            )
            return False
        except Exception as e:
            logger.error(f"Error in delete_deposit_address stub: {e}")
            return False

    # --- Asset Methods ---

    def list_assets(self) -> dict:
        """
        Retrieves a list of all available assets.
        Corresponds to GET /api/v2/assets
        """
        return self._make_request("GET", "/api/v2/assets")

    def get_asset_info(self, asset_code: str) -> dict:
        """
        Retrieves information for a specific asset.
        Corresponds to GET /api/v2/assets/{asset_code}?code={asset_code}

        Args:
            asset_code: The asset code (e.g., 'BTC')
        """
        return self._make_request(
            "GET", f"/api/v2/assets/{asset_code}", query_params={"code": asset_code}
        )

    # --- Markets Methods ---

    def list_markets(self) -> dict:
        """Retrieves a list of all available markets"""
        return self._make_request("GET", "/api/v2/markets")

    def get_market_info(self, market: str) -> dict:
        """Get information about a specific market
        Args:
            market: Market identifier (e.g., 'BTC/USDT')
        """
        return self._make_request(
            "GET", f"/api/v2/markets/{market}", query_params={"market": market}
        )

    # --- Transaction Methods ---

    def list_deposits(self, sort_by: str = "created_at", sort: str = "asc") -> dict:
        """Retrieves list of deposit transactions
        Args:
            sort_by: Field to sort by (default: created_at)
            sort: Sort direction (asc/desc, default: asc)
        """
        params = {"sort_by": sort_by, "sort": sort}
        return self._make_request(
            "GET", "/api/v2/transactions/deposits", query_params=params
        )

    def list_withdrawals(self) -> dict:
        """Retrieves list of withdrawal transactions"""
        return self._make_request("GET", "/api/v2/transactions/withdrawals")

    # --- Requisites Methods ---

    def list_requisites(self) -> dict:
        """
        Retrieves list of requisites.
        Corresponds to GET /api/v2/requisites
        """
        return self._make_request("GET", "/api/v2/requisites")

    # --- Withdrawal Methods ---

    def create_withdrawal(
        self, dchain: str, destination: str, amount: Union[float, str]
    ):
        """
        Creates a withdrawal request.
        Corresponds to POST /api/v2/withdrawals

        Args:
            dchain: The withdrawal chain (e.g., 'trx').
            destination: The destination address.
            amount: The amount to withdraw.
        """
        endpoint = "/api/v2/withdrawals"
        body = {
            "dchain": dchain,
            "destination": destination,
            # Ensure amount is string if API requires
            "amount": amount,
        }
        return self._make_request(method="POST", endpoint=endpoint, body_data=body)

    # --- Exchange Methods ---

    def list_exchanges(self):
        """
        Retrieves a list of past exchanges.
        Corresponds to GET /api/v2/exchanges
        """
        endpoint = "/api/v2/exchanges"
        return self._make_request(method="GET", endpoint=endpoint)

    def create_exchange(
        self, input_asset: str, output_asset: str, amount: Union[float, str]
    ):
        """
        Creates a new exchange between assets.
        Corresponds to POST /api/v2/exchanges

        Args:
            input_asset: The asset to sell.
            output_asset: The asset to buy.
            amount: The amount of input_asset to sell.
        """
        endpoint = "/api/v2/exchanges"
        body = {
            "input_asset": input_asset,
            "output_asset": output_asset,
            "amount": str(amount),
        }
        return self._make_request(method="POST", endpoint=endpoint, body_data=body)

    def estimate_exchange(
        self, input_asset: str, output_asset: str, amount: Union[float, str]
    ):
        """
        Estimates the result of an exchange.
        Corresponds to GET /api/v2/exchanges/estimate

        Args:
            input_asset: The asset to sell.
            output_asset: The asset to buy.
            amount: The amount of input_asset to sell.
        """
        endpoint = "/api/v2/exchanges/estimate"
        params = {
            "input_asset": input_asset,
            "output_asset": output_asset,
            "amount": str(amount),
        }
        return self._make_request(method="GET", endpoint=endpoint, query_params=params)

    # --- Order Methods ---

    def list_orders(
        self,
        market: str = None,
        state: str = None,  # e.g., 'wait', 'done', 'cancel'
        limit: int = 100,
        page: int = 1,
        order_by: str = "desc",  # Or 'asc'
    ):
        """
        Retrieves a list of orders, optionally filtered.
        Corresponds to GET /api/v2/orders

        Check docs.novabtc.io for exact parameter names and available states.

        Args:
            market: Optional market identifier (e.g., 'trxusdt').
            state: Optional order state to filter by.
            limit: Optional number of orders per page.
            page: Optional page number.
            order_by: Optional order direction ('asc' or 'desc').
        """
        endpoint = "/api/v2/orders"
        params = {"limit": limit, "page": page, "order_by": order_by}
        if market:
            params["market"] = market  # Verify exact param name
        if state:
            params["state"] = state  # Verify exact param name

        # Filter out None values cleanly if needed, though requests might handle it
        # params = {k: v for k, v in params.items() if v is not None}

        return self._make_request(method="GET", endpoint=endpoint, query_params=params)

    def get_order_info(self, order_id: int) -> dict:
        """
        Retrieves information for a specific order.
        Corresponds to GET /api/v2/orders/{order_id}

        Args:
            order_id: The ID of the order.
        """
        return self._make_request("GET", f"/api/v2/orders/{order_id}")

    def cancel_order(self, order_id: int) -> dict:
        """
        Cancels a specific order.
        Corresponds to DELETE /api/v2/orders/{order_id}

        Args:
            order_id: The ID of the order.
        """
        return self._make_request("DELETE", f"/api/v2/orders/{order_id}")

    def cancel_all_orders(self) -> dict:
        """
        Cancels all orders.
        Corresponds to DELETE /api/v2/orders
        """
        return self._make_request("DELETE", "/api/v2/orders")

    def create_order(
        self,
        market: str,
        side: str,
        volume: Union[str, float],
        ord_type: str,
        price: Union[str, float] = None,
    ):
        """
        Creates a new order.
        Corresponds to POST /api/v2/orders

        Args:
            market: Market identifier (e.g., 'trxusdt').
            side: 'buy' or 'sell'.
            volume: Amount to buy/sell.
            ord_type: Order type (e.g., 'market', 'limit').
            price: Price for limit orders (required if ord_type='limit').
        """
        endpoint = "/api/v2/orders"  # Verified endpoint
        body = {
            "market": market,
            "side": side,
            "volume": str(volume),  # API example shows string
            "ord_type": ord_type,
        }
        if ord_type == "limit":
            if price is None:
                raise ValueError("Price is required for limit orders.")
            body["price"] = str(price)

        return self._make_request(method="POST", endpoint=endpoint, body_data=body)

    # --- Trade Methods ---

    def list_trades(self, market: str = None, limit: int = 100, page: int = 1) -> dict:
        """
        Retrieves a list of trades.
        Corresponds to GET /api/v2/trades

        Args:
            market: Optional market identifier to filter trades.
            limit: Number of trades per page.
            page: The page number.
        """
        params = {"limit": limit, "page": page}
        if market:
            params["market"] = market
        return self._make_request("GET", "/api/v2/trades", query_params=params)

    # --- Settings Methods ---

    def get_settings_markets(self) -> dict:
        """
        Retrieves market settings.
        Corresponds to GET /api/v2/settings/markets
        """
        return self._make_request("GET", "/api/v2/settings/markets")

    def get_settings_currencies(self) -> dict:
        """
        Retrieves currency settings.
        Corresponds to GET /api/v2/settings/currencies
        """
        return self._make_request("GET", "/api/v2/settings/currencies")

    # --- Tools Methods ---

    def get_info(self):
        """Gets basic platform info. Needs API Key/Sign per docs?"""
        # Docs unclear if /tools/* endpoints need auth. Assuming yes for now.
        # If not, this should be a simple requests.get without auth headers.
        return self._make_request(method="GET", endpoint="/api/v2/tools/info")

    def get_services(self):
        """Gets platform services status. Needs API Key/Sign per docs?"""
        # Docs unclear if /tools/* endpoints need auth. Assuming yes for now.
        return self._make_request(method="GET", endpoint="/api/v2/tools/services")

    def get_timestamp(self):
        """Gets the server timestamp. Needs API Key/Sign per docs?"""
        # Docs unclear if /tools/* endpoints need auth. Assuming yes for now.
        return self._make_request(method="GET", endpoint="/api/v2/tools/timestamp")

    # --- WebSocket Handling (using python-socketio) ---
    def _get_ws_auth_params(self, user_uuid: str) -> dict:
        """Generates connection URL parameters for WebSocket auth."""
        # Signature format: f'{USER_UUID}|{API_KEY}' signed with API_SECRET
        canonical_string = f"{user_uuid}|{self.access_key}"
        logger.debug(f"Canonical string for WS signing: '{canonical_string}'")
        api_sign = hmac.new(
            self.secret_key.encode("utf-8"),
            canonical_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        logger.debug(f"Generated WS signature: '{api_sign}'")
        return {
            "api_key": self.access_key,
            "api_sign": api_sign,
            "user_uuid": user_uuid,
        }

    async def connect_websocket(self):
        """
        Establishes connection using python-socketio.

        Handles fetching user_uuid if necessary.
        Registers default event handlers.
        Does NOT automatically start listening.
        """
        lock = self._ws_connection_lock
        if not lock:
            # Fallback for non-async environments
            logger.warning(
                "Asyncio lock not available. WS connection might have race conditions."
            )

        # Use lock to prevent concurrent connection attempts
        if lock:
            async with lock:
                if self.sio and self.sio.connected:
                    logger.info("WebSocket already connected.")
                    return True
                if self._is_ws_connecting:
                    logger.info("WebSocket connection already in progress.")
                    return False  # Indicate connection is pending
                self._is_ws_connecting = True
        else:
            # No lock - potential race condition
            if self.sio and self.sio.connected:
                logger.info("WebSocket already connected.")
                return True

        try:
            user_uuid = await self._ensure_user_uuid()
            if not user_uuid:
                return False  # Error logged previously

            auth_params = self._get_ws_auth_params(user_uuid)

            # Construct URL with query parameters for authentication
            url_params = (
                f"?api_key={self.access_key}&api_sign={auth_params['api_sign']}"
            )
            connection_url = f"{self.ws_url}{url_params}"

            # Use socketio.AsyncClient
            self.sio = socketio.AsyncClient(logger=True, engineio_logger=False)

            # Register Default Event Handlers
            self._register_default_sio_handlers(connection_url)

            # Attempt Connection
            logger.info(
                f"Attempting Socket.IO connection to {connection_url} "
                f"with path {self.ws_path}"
            )
            await self.sio.connect(
                connection_url, transports=["websocket"], socketio_path=self.ws_path
            )
            logger.info("Socket.IO connect call initiated.")
            # Connection happens in background, check sio.connected later
            return True

        except ValueError as ve:
            logger.error(f"WebSocket connection setup failed: {ve}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during WS connection: {e}", exc_info=True)
            return False
        finally:
            if lock:
                self._is_ws_connecting = False  # Release lock flag

    def _register_default_sio_handlers(self, conn_url):
        """Registers the default Socket.IO event handlers."""

        @self.sio.event
        async def connect():
            logger.info(f"Socket.IO connected to: {conn_url}")
            logger.info(f"API Key: {self.access_key}")

        @self.sio.event
        async def disconnect():
            logger.warning("Socket.IO disconnected.")

        @self.sio.event
        async def close(data):
            logger.warning(f"Socket.IO connection closed: {data}")

        @self.sio.event
        async def connect_error(data):
            logger.error(f"Socket.IO connection error: {data}")

        # Default Data Handlers (can be overridden by register_ws_handler)
        @self.sio.on("account")
        async def on_account(data):
            logger.info(f"WS Received [account]: {data}")

        @self.sio.on("deposit_address")
        async def on_deposit_address(data):
            logger.info(f"WS Received [deposit_address]: {data}")

        @self.sio.on("deposit")
        async def on_deposit(data):
            logger.info(f"WS Received [deposit]: {data}")
            await self.deposit_callback(data)

        @self.sio.on("withdrawal")
        async def on_withdrawal(data):
            logger.info(f"WS Received [withdrawal]: {data}")
            await self.withdrawal_callback(data)

    def register_ws_handler(self, event: str, handler):
        """Registers or overrides a handler for a WebSocket event."""
        if not self.sio:
            # Initialize if not done yet, allows registering before connect
            self.sio = socketio.AsyncClient(logger=True, engineio_logger=False)

        logger.info(f"Registering handler for WS event: '{event}'")
        self.sio.on(event, handler)

    async def disconnect_websocket(self):
        """Disconnects the WebSocket connection gracefully."""
        if self.sio and self.sio.connected:
            logger.info("Disconnecting WebSocket...")
            await self.sio.disconnect()
            logger.info("WebSocket disconnected.")
        else:
            logger.info("WebSocket already disconnected or not initialized.")
        self.sio = None  # Clear client instance

    async def withdrawal_callback(self, data):
        """Handle withdrawal callback from Nova API."""

        do = False

        if do:
            status = data.get("status")
            address = data.get("address")
            amount = float(data.get("amount", 0))
            if status != "done":
                logger.info("Withdrawal not completed, skipping.")
                return
            mongo = self.mongo_client_instance
            pending_transfers = list(
                mongo.pending_card_transfers.find(
                    {"status": "waiting_for_pool", "address": address}
                ).sort("created_at", 1)
            )
            interlace_client = InterlaceClient()
            try:
                balances = interlace_client.funding.get_balances()
                quantum_balance = 0
                for bal in balances["data"]:
                    if (
                        bal["walletType"] == "QuantumAccount"
                        and bal["currency"] == "USD"
                    ):
                        quantum_balance = float(bal["available"])
                        break

            except Exception as e:

                logger.error(f"Error fetching quantum account balance: {e}")
                quantum_balance = 0

            for pending in pending_transfers:
                if quantum_balance >= pending["net_amount"]:
                    try:
                        transfer_payload = {
                            "cardId": pending["card_id"],
                            "cost": round(float(pending["net_amount"]), 2),
                        }
                        transfer_response = (
                            interlace_client.infinity_card.infinity_card_transfer_in(
                                transfer_payload
                            )
                        )
                        logger.info(
                            f"Processed pending card transfer: {transfer_response}"
                        )
                        await mongo.pending_card_transfers.delete_one(
                            {"_id": pending["_id"]}
                        )
                        quantum_balance -= pending["net_amount"]
                    except Exception as e:
                        logger.error(f"Error processing pending card transfer: {e}")
                else:
                    logger.info(
                        "Quantum account balance insufficient for next pending "
                        "transfer. Waiting for next refill."
                    )
                    break

    async def deposit_callback(self, data):
        """Handle deposit callback from Nova API."""
        try:
            fee_percent_interlace = config.NOVA_DEPOSITS_CONFIG.get(
                "fee_percent_interlace", 0
            )
            fee_cash = config.NOVA_DEPOSITS_CONFIG.get("fee_cash", 0)
            virtual_card_fee_config = config.NOVA_DEPOSITS_CONFIG.get(
                "virtual_card_fee", 0
            )

            # --- Extract deposit details ---
            deposit_obj = data.get("object") or {}
            tid = deposit_obj.get("tx_id")
            nova_status = deposit_obj.get("status")
            address = deposit_obj.get("address")
            amount = deposit_obj.get("amount")
            asset = deposit_obj.get("asset")
            action = data.get("action")

            if not tid or not nova_status or not address:
                logger.warning(
                    f"Deposit callback missing tid, status, or address: {deposit_obj}"
                )
                return

            # --- Get user information from deposit timer ---
            mongo = self.mongo_client_instance
            deposit_timer = await mongo.deposit_timers.find_one(
                {"address": address, "expires_at": {
                    "$gt": datetime.now(timezone.utc)}}
            )
            previous_same_tid = await mongo.combined_transactions.find_one(
                {
                    # 'cardId': card_id,
                    "type": "deposit",
                    "tid": tid,
                    "nova_status": "Processing",
                }
            )

            if not deposit_timer and not previous_same_tid:
                logger.warning(f"No active deposit timer found for address: {address}")
                return
            else:
                if deposit_timer:
                    user_id = deposit_timer.get("user_id")
                else:
                    user_id = previous_same_tid.get("user_id")

            if not user_id:
                logger.warning(
                    f"No user_id found in deposit timer for address: {address}"
                )
                return

            user_result = await mysql_client.get_user_from_db(user_id=user_id)

            if not user_result or not user_result.get("success"):
                logger.error(f"Failed to get user data for user_id: {user_id}")
                return

            user_row = user_result.get("user", {})
            card_number = user_row.get("cardNumber")

            if not card_number:
                logger.error(f"No card number found for user_id: {user_id}")
                return

            # Get card ID from Interlace
            card_id = await self.get_card_id_by_card_number(card_number)
            if not card_id:
                logger.error(f"Could not find card_id for card_number: {card_number}")
                return
            # --- Determine if this is the first real deposit ---
            # First check if there's a previous deposit with same tid

            # --- Load user and card information ---
            try:
                if (
                    float(amount) < MIN_DEPOSIT_AMOUNT
                    or float(amount) > MAX_DEPOSIT_AMOUNT
                ):
                    await telegram_messaging.send_deposit_expiry(
                        user_id,
                        message=f"Your deposit amount {amount} is out of range for user_id: {user_id}",
                    )
                    return

                # Get deposit fee for user
                deposit_fee, _ = await mysql_client.get_fees_for_user_mysql(user_id=user_id)
                fee_percent = deposit_fee / 100.0

            except Exception as e:
                logger.error(f"Error loading user/card data: {e}")
                return

            if previous_same_tid:
                if action == "update" and nova_status.lower() != "done":
                    return
                # If we have a previous 'processing' deposit with same tid
                # maintain the same is_first_real_deposit status
                is_first_real_deposit = previous_same_tid.get(
                    "is_first_real_deposit", False
                )
            else:
                # Check if there are any other deposits for this card
                existing_deposits = await mongo.combined_transactions.find(
                    {
                        "cardId": card_id,
                        "type": "deposit",
                        "nova_status": {"$in": ["Done", "Processing"]},
                        "tid": {"$ne": tid},  # Exclude current tid
                    }
                ).to_list(length=1)

                # This is the first deposit if there are no existing deposits
                is_first_real_deposit = not existing_deposits

            # Apply virtual card fee only for first real deposit and if status is not
            # failed
            virtual_card_fee = (
                virtual_card_fee_config
                if is_first_real_deposit and nova_status in ["done", "processing"]
                else 0
            )

            # --- Calculate final amount after fees ---
            try:
                x = float(amount)
                final_amount = (
                    x * (1 - fee_percent - fee_percent_interlace)
                    - fee_cash
                    - virtual_card_fee
                )
                final_amount = round(float(final_amount), 2)
            except Exception as e:
                logger.error(f"Error calculating final amount: {e}")
                final_amount = float(amount)

            # Store in combined_transactions with tracking info
            combined_doc = {
                # Original deposit object fields
                "address": address,
                "amount": float(amount),
                "asset": asset,
                "asset_type": deposit_obj.get("asset_type"),
                "control": deposit_obj.get("control"),
                "action": action,
                "created_at": deposit_obj.get("created_at"),
                "dchain_id": deposit_obj.get("dchain_id"),
                "done_at": deposit_obj.get("done_at"),
                "fee": deposit_obj.get("fee"),
                "high_risk": deposit_obj.get("high_risk"),
                "status": "Pending",  # User-facing status
                "tag": deposit_obj.get("tag"),
                "tid": tid,
                "tx_link": deposit_obj.get("tx_link"),
                "type": "deposit",
                "updated_at": deposit_obj.get("updated_at"),
                "uuid": deposit_obj.get("uuid"),
                # Additional fields for our system
                "tid": tid,
                "timestamp": datetime.now(timezone.utc),
                "transaction_time": datetime.now(timezone.utc),
                "user_id": user_id,
                "cardId": card_id,  # Consistent with Interlace field name
                "internal_status": "Pending",
                "nova_status": nova_status.capitalize(),  # Capitalize Nova status
                "remark": deposit_obj.get("remark"),
                "detail": deposit_obj.get("detail"),
                "card_number": card_number,
                "final_amount": final_amount,
                "fee_percent_nova": fee_percent,
                "fee_percent_interlace": fee_percent_interlace,
                "fee_cash": fee_cash,
                "virtual_card_fee": virtual_card_fee,
                "is_first_real_deposit": is_first_real_deposit,
                "stage": 1,
                # Add tracking fields
                "requires_withdrawal": False,
                "withdrawal_tid": None,
                "withdrawal_status": None,
                "quantum_transfer_status": None,
            }

            await mongo.combined_transactions.insert_one(combined_doc)
            latest_doc = await mongo.combined_transactions.find_one(
                {"tid": tid}, sort=[("timestamp", -1)]  # Sort by timestamp descending
            )
            logger.info(
                f"Saved deposit event for tid={tid} with nova_status={nova_status}, "
                f"is_first_real_deposit={is_first_real_deposit}, virtual_card_fee={virtual_card_fee}"
            )

            if nova_status.lower() == "processing":
                logger.info(
                    f"Processing deposit {tid} for Interlace quantum account "
                    f"(infinity account) logic."
                )
                # Update status to Processing
                await mongo.combined_transactions.update_one(
                    {"_id": latest_doc["_id"]},
                    {"$set": {"status": "Processing", "internal_status": "Processing"}},
                )
                # Send telegram notification about deposit processing
                try:
                    await telegram_messaging.send_deposit_expiry(
                        user_id,
                        message=f"Your deposit of {amount} {asset} is being processed.\nTX Link: {deposit_obj.get('tx_link')}",
                    )
                except Exception as e:
                    logger.error(f"Error sending Telegram message: {e}")

            elif nova_status.lower() == "done":
                logger.info(
                    f"Processing deposit {tid} with Interlace client and Google "
                    f"Sheets lookup"
                )

                # --- Quantum account logic ---
                interlace_client = InterlaceClient()
                try:
                    balances = interlace_client.funding.list_all_balances()
                    quantum_balance = 0
                    for bal in balances:
                        if (
                            bal["walletType"] == "QuantumAccount"
                            and bal["currency"] == "USD"
                        ):
                            quantum_balance = float(bal["available"])
                            break
                except Exception as e:
                    logger.error(f"Error fetching quantum account balance: {e}")
                    quantum_balance = 0

                if quantum_balance >= final_amount:
                    # Validate final amount is positive
                    if final_amount <= 0:
                        logger.error(
                            f"Invalid transfer amount: {final_amount}. "
                            f"Original amount: {amount}, fees: {fee_percent}, "
                            f"{fee_percent_interlace}, {fee_cash}, {virtual_card_fee}"
                        )
                        await mongo.combined_transactions.update_one(
                            {"_id": latest_doc["_id"]},
                            {
                                "$set": {
                                    "quantum_transfer_status": "Failed",
                                    "internal_status": "Failed",
                                    "status": "Failed",
                                    "error": "Invalid transfer amount after fees",
                                }
                            },
                        )
                        return

                    # Transfer from quantum account to card
                    try:
                        transfer_payload = {
                            "cardId": card_id,
                            "cost": final_amount,
                            "clientTransactionId": f"deposit_{tid}_{int(datetime.now().timestamp())}_{random.randint(100000, 999999)}"}
                        transfer_response = (
                            interlace_client.infinity_card.infinity_card_transfer_in(
                                transfer_payload
                            )
                        )
                        logger.info(
                            f"Transfer in response for card_number {card_number}, "
                            f"user {user_id}, amount {final_amount}: "
                            f"{transfer_response}"
                        )
                        # Update combined doc with transfer status
                        await mongo.combined_transactions.update_one(
                            {"_id": latest_doc["_id"]},
                            {
                                "$set": {
                                    "quantum_transfer_status": "Completed",
                                    "internal_status": "Done",
                                    "status": "Processing",  # Will be updated to Completed by CardTransaction callback
                                }
                            },
                        )
                    except Exception as e:
                        logger.error(f"Error transferring to card: {e}")
                        await mongo.combined_transactions.update_one(
                            {"_id": latest_doc["_id"]},
                            {
                                "$set": {
                                    "quantum_transfer_status": "Failed",
                                    "internal_status": "Failed",
                                    "status": "Failed",
                                }
                            },
                        )
                else:
                    # Not enough in quantum account, need to withdraw from Nova
                    amount_to_withdraw = math.ceil((
                        float(amount) * (1 - fee_percent - fee_percent_interlace)
                        - virtual_card_fee - fee_cash
                    ) / (1 - fee_percent_interlace))

                    # Validate withdrawal amount is positive
                    if amount_to_withdraw <= 0:
                        logger.error(
                            f"Invalid withdrawal amount: {amount_to_withdraw}. "
                            f"Original amount: {amount}, fees: {fee_percent}, "
                            f"{fee_percent_interlace}, {virtual_card_fee}"
                        )
                        await mongo.combined_transactions.update_one(
                            {"_id": latest_doc["_id"]},
                            {
                                "$set": {
                                    "requires_withdrawal": False,
                                    "withdrawal_status": "Failed",
                                    "status": "Failed",
                                    "internal_status": "Failed",
                                    "error": "Invalid withdrawal amount after fees",
                                }
                            },
                        )
                        return

                    logger.info(
                        f"Quantum account insufficient. Withdrawing {amount_to_withdraw} "
                        f"from Nova to quantum account."
                    )

                    # Update combined doc to track withdrawal
                    await mongo.combined_transactions.update_one(
                        {"_id": latest_doc["_id"]},
                        {
                            "$set": {
                                "requires_withdrawal": True,
                                "withdrawal_amount": amount_to_withdraw,
                                "withdrawal_status": "Pending",
                                "status": "Processing",
                                "internal_status": "Processing",
                            }
                        },
                    )

                    if TESTING:
                        logger.info(
                            "[TESTING] Simulating AssetsDeposit event via POST to /api/callback on testing_url."
                        )
                        # assets_deposit_event = {
                        #     "id": str(uuid.uuid4()),
                        #     "businessType": "AssetsDeposit",
                        #     "data": {
                        #         "id": str(uuid.uuid4()),
                        #         "createTime": datetime.now(timezone.utc).isoformat(),
                        #         "updateTime": datetime.now(timezone.utc).isoformat(),
                        #         "accountId": deposit_obj.get("accountId", "test-account-id"),
                        #         "balanceId": deposit_obj.get("balanceId", "test-balance-id"),
                        #         "chain": deposit_obj.get("chain", "TRC20"),
                        #         "currency": deposit_obj.get("currency", "USDT"),
                        #         "amount": str(amount_to_withdraw),
                        #         "fee": "0",
                        #         "to": address,
                        #         "status": "Closed",
                        #         "transactionHash": deposit_obj.get("transactionHash", "test-tx-hash")
                        #     },
                        #     "sign": "test-sign"
                        # }
                        # # In testing mode, we'll just simulate the withdrawal response
                        # withdrawal_response = {
                        #     "tid": str(uuid.uuid4()),
                        #     "status": "initiated"
                        # }
                    else:
                        # try:
                        #     if hasattr(self, "create_withdrawal"):
                        #         withdrawal_response = self.create_withdrawal(
                        #             dchain="trc20usdt",
                        #             destination=INTERLACE_ADDRESS,
                        #             amount=amount_to_withdraw,
                        #         )
                        #         # Update combined doc with withdrawal tid
                        #         await mongo.combined_transactions.update_one(
                        #             {"_id": latest_doc["_id"]},
                        #             {
                        #                 "$set": {
                        #                     "withdrawal_tid": withdrawal_response.get(
                        #                         "tid"
                        #                     ),
                        #                     "withdrawal_status": "initiated",
                        #                 }
                        #             },
                        #         )
                        #         logger.info(
                        #             f"Withdrawal requested for {amount_to_withdraw}"
                        #         )
                        #     else:
                        #         logger.error(
                        #             "No create_withdrawal method available on NovaClient."
                        # )
                        # except Exception as e:
                        e = "error"
                        await telegram_messaging.send_admin_alert(
                            f"Error initiating quantum pool withdrawal: {e}\n"
                            f"Withdrawal amount: *{amount_to_withdraw}*\n"
                            f"Destination: {INTERLACE_ADDRESS}\n"
                            f"User: {combined_doc}\n"
                        )

                        await telegram_messaging.send_admin_alert(f"{amount_to_withdraw}")

                        logger.error(
                            f"Error initiating quantum pool withdrawal: {e}"
                        )
                # Close the deposit timer since we received a callback
                try:

                    # Update deposit timer status
                    await mongo.deposit_timers.update_one(
                        {"user_id": user_id},
                        {
                            "$set": {
                                "active": False,
                                "reserved": False,
                                "expiry_notified": True,
                            }
                        },
                    )

                    logger.info(
                        f"Closed deposit timer for address {address} after receiving callback"
                    )

                except Exception as e:
                    logger.error(f"Error closing deposit timer: {e}")

            else:
                logger.info(f"Deposit {tid} has unhandled status: {nova_status}")
        except Exception as e:
            logger.error(f"Error in deposit_callback: {e}")

    async def get_card_id_by_card_number(self, card_number):
        """
        Given a card number, find the card_id using Interlace API (preferred),
        then MongoDB, then MySQL. Returns card_id if found, else None.
        """
        # 1. Try Interlace API
        try:
            interlace_client = InterlaceClient()
            cards = interlace_client.infinity_card.list_all_infinity_cards()
            # Try to match by last 4 digits (since that's how it's often stored)
            for card in cards:
                # card.card_no_last_four is the last 4 digits
                if str(card.card_no_last_four) == str(card_number)[-4:] or str(
                    getattr(card, "card_no", "")
                ) == str(card_number):
                    card_details = interlace_client.infinity_card.get_infinity_card_details(
                        card.id)
                    if (card_details.card_no == str(card_number)):
                        return card.id
                    # else:
                    #     logger.error(f"Card number mismatch: {card_details.card_no} != {card_number}")
                    # return card.id
        except Exception as e:
            logger.error(f"Error looking up card_id in Interlace: {e}")
