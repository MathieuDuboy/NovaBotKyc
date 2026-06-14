"""
Tronscan API Client Implementation.

This module provides a client for interacting with the Tronscan API.
Documentation: https://docs.tronscan.org/api-endpoints/
"""

import asyncio
import json
import logging
import os
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urljoin

import aiohttp
import requests
import websockets

import config
from utils.logger import logger

# Import config to access API key and base URL
try:
    import config

    HAS_CONFIG = True
except ImportError:
    HAS_CONFIG = False

logger = logging.getLogger(__name__)

# Default Tronscan API base URL if not available from config
DEFAULT_BASE_URL = "https://apilist.tronscan.org/api/"


class TronscanClient:
    """
    Client for interacting with the Tronscan API.
    Supports both async and sync operations.
    """

    def __init__(self, url: str, api_key: str):
        self.url = url
        self.api_key = api_key
        self.websocket = None
        self.connected = False
        self.message_queue = asyncio.Queue()

    async def connect(self):
        try:
            self.websocket = await websockets.connect(
                self.url, extra_headers={"Authorization": f"Bearer {self.api_key}"}
            )
            self.connected = True
            logger.info("Successfully connected to Tronscan server")
        except Exception as e:
            logger.error(f"Failed to connect to Tronscan server: {e}")
            raise

    async def close(self):
        try:
            if self.websocket:
                await self.websocket.close()
                self.connected = False
                logger.info("Successfully closed Tronscan connection")
        except Exception as e:
            logger.error(f"Error closing Tronscan connection: {e}")

    async def send_message(self, message: str):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return

            await self.websocket.send(message)
            logger.info("Successfully sent message to Tronscan server")
        except Exception as e:
            logger.error(f"Error sending message to Tronscan server: {e}")
            self.connected = False

    async def receive_message(self) -> Optional[str]:
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return None

            message = await self.websocket.recv()
            logger.info("Successfully received message from Tronscan server")
            return message
        except Exception as e:
            logger.error(f"Error receiving message from Tronscan server: {e}")
            self.connected = False
            return None

    async def send_json(self, data: Dict):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return

            message = json.dumps(data)
            await self.send_message(message)
            logger.info("Successfully sent JSON data to Tronscan server")
        except Exception as e:
            logger.error(f"Error sending JSON data to Tronscan server: {e}")

    async def receive_json(self) -> Optional[Dict]:
        try:
            message = await self.receive_message()
            if message:
                data = json.loads(message)
                logger.info("Successfully received JSON data from Tronscan server")
                return data
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from Tronscan server: {e}")
            return None
        except Exception as e:
            logger.error(f"Error receiving JSON data from Tronscan server: {e}")
            return None

    async def ping(self):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return False

            await self.websocket.ping()
            logger.info("Successfully pinged Tronscan server")
            return True
        except Exception as e:
            logger.error(f"Error pinging Tronscan server: {e}")
            self.connected = False
            return False

    async def subscribe(self, channel: str):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return

            await self.send_json({"type": "subscribe", "channel": channel})
            logger.info(f"Successfully subscribed to channel {channel}")
        except Exception as e:
            logger.error(f"Error subscribing to channel {channel}: {e}")

    async def unsubscribe(self, channel: str):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return

            await self.send_json({"type": "unsubscribe", "channel": channel})
            logger.info(f"Successfully unsubscribed from channel {channel}")
        except Exception as e:
            logger.error(f"Error unsubscribing from channel {channel}: {e}")

    async def publish(self, channel: str, message: str):
        try:
            if not self.connected:
                logger.warning("Not connected to Tronscan server")
                return

            await self.send_json(
                {"type": "publish", "channel": channel, "message": message}
            )
            logger.info(f"Successfully published message to channel {channel}")
        except Exception as e:
            logger.error(f"Error publishing message to channel {channel}: {e}")

    def _get_base_url(self):
        """Get the base URL for Tronscan API."""
        return self.url

    @property
    def session(self) -> aiohttp.ClientSession:
        """Get or create the aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make an API request to Tronscan.

        Args:
            endpoint: API endpoint path
            params: URL parameters
            method: HTTP method (GET, POST, etc.)
            data: JSON data for POST requests

        Returns:
            API response as dictionary
        """
        url = urljoin(self._get_base_url(), endpoint)
        headers = {}

        if self.api_key:
            headers["TRON-PRO-API-KEY"] = self.api_key

        try:
            if method.upper() == "GET":
                async with self.session.get(
                    url, params=params, headers=headers
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            elif method.upper() == "POST":
                async with self.session.post(
                    url, params=params, json=data, headers=headers
                ) as response:
                    response.raise_for_status()
                    return await response.json()
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
        except aiohttp.ClientResponseError as e:
            logger.error(f"API error: {e.status} - {e.message}")
            return {"error": f"API error: {e.status} - {e.message}"}
        except aiohttp.ClientError as e:
            logger.error(f"Request error: {str(e)}")
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def _request_sync(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        method: str = "GET",
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Make a synchronous API request to Tronscan.

        Args:
            endpoint: API endpoint path
            params: URL parameters
            method: HTTP method (GET, POST, etc.)
            data: JSON data for POST requests

        Returns:
            API response as dictionary
        """
        url = urljoin(self._get_base_url(), endpoint)
        headers = {}

        if self.api_key:
            headers["TRON-PRO-API-KEY"] = self.api_key

        try:
            if method.upper() == "GET":
                response = requests.get(url, params=params, headers=headers)
            elif method.upper() == "POST":
                response = requests.post(url, params=params, json=data, headers=headers)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            logger.error(f"API error: {e}")
            return {"error": f"API error: {str(e)}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {str(e)}")
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    # Account Endpoints

    async def get_account_list(
        self, limit: int = 20, start: int = 0, sort: str = "-balance"
    ) -> Dict[str, Any]:
        """
        Get list of accounts.

        Args:
            limit: Number of results per page
            start: Index of the starting account
            sort: Sort field (e.g. "-balance" for descending balance)

        Returns:
            Dictionary with account list
        """
        params = {"limit": limit, "start": start, "sort": sort}
        return await self._request("accounts", params)

    async def get_account(self, address: str) -> Dict[str, Any]:
        """
        Get account information.

        Args:
            address: TRON account address

        Returns:
            Dictionary with account information
        """
        params = {"address": address}
        return await self._request("account", params)

    async def get_account_tokens(
        self,
        address: str,
        limit: int = 20,
        start: int = 0,
        hidden: int = 0,
        show: int = 0,
    ) -> Dict[str, Any]:
        """
        Get account's token list.

        Args:
            address: TRON account address
            limit: Number of results per page
            start: Index of the starting token
            hidden: Whether to include hidden tokens (0/1)
            show: Filter option for tokens (0/1)

        Returns:
            Dictionary with token list
        """
        params = {
            "address": address,
            "limit": limit,
            "start": start,
            "hidden": hidden,
            "show": show,
        }
        return await self._request("account/tokens", params)

    async def get_account_votes(self, address: str) -> Dict[str, Any]:
        """
        Get the voted list for an account.

        Args:
            address: TRON account address

        Returns:
            Dictionary with voted SR list
        """
        params = {"address": address}
        return await self._request("account/votes", params)

    async def get_account_resources(self, address: str) -> Dict[str, Any]:
        """
        Get account resources (bandwidth, energy, etc.).

        Args:
            address: TRON account address

        Returns:
            Dictionary with account resources
        """
        params = {"address": address}
        return await self._request("account/resources", params)

    async def get_account_stake2_resources(self, address: str) -> Dict[str, Any]:
        """
        Get stake 2.0 resources for an account.

        Args:
            address: TRON account address

        Returns:
            Dictionary with stake 2.0 resources information
        """
        params = {"address": address}
        return await self._request("account/stake2.0", params)

    async def get_account_approval_list(self, address: str) -> Dict[str, Any]:
        """
        Get approval list for an account.

        Args:
            address: TRON account address

        Returns:
            Dictionary with approval list information
        """
        params = {"address": address}
        return await self._request("account/approval-list", params)

    async def get_account_auth_change_records(self, address: str) -> Dict[str, Any]:
        """
        Get authorization change records for an account.

        Args:
            address: TRON account address

        Returns:
            Dictionary with authorization change records
        """
        params = {"address": address}
        return await self._request("account/auth-change-records", params)

    async def get_account_analysis(
        self,
        address: str,
        type_id: int = 0,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get daily analytics data for an account.

        Args:
            address: TRON account address
            type_id: Type of analysis data
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with account analytics
        """
        params = {"address": address, "typeId": type_id}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("account/analysis", params)

    async def get_participate_project(self, address: str) -> Dict[str, Any]:
        """
        Get projects an account has participated in.

        Args:
            address: TRON account address

        Returns:
            Dictionary with participation information
        """
        params = {"address": address}
        return await self._request("account/participate-project", params)

    async def get_account_token_asset_overview(self, address: str) -> Dict[str, Any]:
        """
        Get account wallet token overview.

        Args:
            address: TRON account address

        Returns:
            Dictionary with token asset overview
        """
        params = {"address": address}
        return await self._request("account/wallet/token/overview", params)

    async def get_multiple_chain_address(self, address: str) -> Dict[str, Any]:
        """
        Find if an address exists on other chains.

        Args:
            address: TRON account address

        Returns:
            Dictionary with associated addresses on other chains
        """
        params = {"address": address}
        return await self._request("multiplechain/address", params)

    # Transaction Endpoints

    async def get_transactions(
        self,
        address: Optional[str] = None,
        limit: int = 20,
        start: int = 0,
        sort: str = "-timestamp",
        count: bool = True,
    ) -> Dict[str, Any]:
        """
        Get account transactions.

        Args:
            address: TRON account address
            limit: Number of results per page
            start: Index of the starting transaction
            sort: Sort field (e.g. "-timestamp" for newest first)
            count: Whether to include total count

        Returns:
            Dictionary with transaction list
        """
        params = {
            "limit": limit,
            "start": start,
            "sort": sort,
            "count": str(count).lower(),
        }

        if address:
            params["address"] = address

        return await self._request("transaction", params)

    async def get_transaction_info(self, hash: str) -> Dict[str, Any]:
        """
        Get detailed information about a transaction.

        Args:
            hash: Transaction hash

        Returns:
            Dictionary with transaction details
        """
        params = {"hash": hash}
        return await self._request("transaction-info", params)

    async def get_transfers(
        self,
        address: Optional[str] = None,
        token: Optional[str] = None,
        limit: int = 20,
        start: int = 0,
        sort: str = "-timestamp",
    ) -> Dict[str, Any]:
        """
        Get token transfers.

        Args:
            address: TRON account address
            token: Token name or ID
            limit: Number of results per page
            start: Index of the starting transfer
            sort: Sort field (e.g. "-timestamp" for newest first)

        Returns:
            Dictionary with transfers list
        """
        params = {"limit": limit, "start": start, "sort": sort}

        if address:
            params["address"] = address

        if token:
            params["token"] = token

        return await self._request("transfer", params)

    async def get_nft_transfers(
        self,
        address: Optional[str] = None,
        contract_address: Optional[str] = None,
        limit: int = 20,
        start: int = 0,
    ) -> Dict[str, Any]:
        """
        Get NFT transfers.

        Args:
            address: TRON account address
            contract_address: NFT contract address
            limit: Number of results per page
            start: Index of the starting transfer

        Returns:
            Dictionary with NFT transfers list
        """
        params = {"limit": limit, "start": start}

        if address:
            params["address"] = address

        if contract_address:
            params["contract_address"] = contract_address

        return await self._request("nft/transfers", params)

    async def get_internal_transactions(
        self, address: Optional[str] = None, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get internal transactions.

        Args:
            address: TRON account address
            limit: Number of results per page
            start: Index of the starting transaction

        Returns:
            Dictionary with internal transactions list
        """
        params = {"limit": limit, "start": start}

        if address:
            params["address"] = address

        return await self._request("internal-transaction", params)

    # Token Endpoints

    async def get_token_list(self, limit: int = 20, start: int = 0) -> Dict[str, Any]:
        """
        Get list of tokens.

        Args:
            limit: Number of results per page
            start: Index of the starting token

        Returns:
            Dictionary with token list
        """
        params = {"limit": limit, "start": start}
        return await self._request("tokens", params)

    async def get_token_info(self, token_id: str) -> Dict[str, Any]:
        """
        Get token information.

        Args:
            token_id: Token ID or name

        Returns:
            Dictionary with token information
        """
        params = {"id": token_id}
        return await self._request("token", params)

    async def get_token_holders(
        self, token_id: str, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get token holders.

        Args:
            token_id: Token ID or name
            limit: Number of results per page
            start: Index of the starting holder

        Returns:
            Dictionary with token holders
        """
        params = {"id": token_id, "limit": limit, "start": start}
        return await self._request("token_holders", params)

    async def get_token_trc20(self, contract_address: str) -> Dict[str, Any]:
        """
        Get TRC20 token information.

        Args:
            contract_address: Contract address of the TRC20 token

        Returns:
            Dictionary with TRC20 token information
        """
        params = {"contract": contract_address}
        return await self._request("token_trc20", params)

    async def get_nft_list(
        self, address: Optional[str] = None, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get NFT list.

        Args:
            address: TRON account address
            limit: Number of results per page
            start: Index of the starting NFT

        Returns:
            Dictionary with NFT list
        """
        params = {"limit": limit, "start": start}

        if address:
            params["address"] = address

        return await self._request("nft/list", params)

    async def get_token_price_history(
        self,
        token_id: str,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get token price history.

        Args:
            token_id: Token ID or name
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with token price history
        """
        params = {"token": token_id, "time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("market/price", params)

    # Contract Endpoints

    async def get_contract(self, contract_address: str) -> Dict[str, Any]:
        """
        Get smart contract information.

        Args:
            contract_address: Contract address

        Returns:
            Dictionary with contract information
        """
        params = {"contract": contract_address}
        return await self._request("contract", params)

    async def get_contract_transactions(
        self,
        contract_address: str,
        limit: int = 20,
        start: int = 0,
        sort: str = "-timestamp",
    ) -> Dict[str, Any]:
        """
        Get transactions for a contract.

        Args:
            contract_address: Contract address
            limit: Number of results per page
            start: Index of the starting transaction
            sort: Sort field (e.g. "-timestamp" for newest first)

        Returns:
            Dictionary with contract transactions
        """
        params = {
            "contract": contract_address,
            "limit": limit,
            "start": start,
            "sort": sort,
        }
        return await self._request("contract/transactions", params)

    async def get_contracts(
        self, limit: int = 20, start: int = 0, sort: str = "-timestamp"
    ) -> Dict[str, Any]:
        """
        Get list of contracts.

        Args:
            limit: Number of results per page
            start: Index of the starting contract
            sort: Sort field (e.g. "-timestamp" for newest first)

        Returns:
            Dictionary with contract list
        """
        params = {"limit": limit, "start": start, "sort": sort}
        return await self._request("contracts", params)

    async def get_contract_events(
        self,
        contract_address: str,
        event_name: Optional[str] = None,
        block_number: Optional[int] = None,
        limit: int = 20,
        start: int = 0,
    ) -> Dict[str, Any]:
        """
        Get events for a contract.

        Args:
            contract_address: Contract address
            event_name: Name of the event to filter by
            block_number: Block number to filter by
            limit: Number of results per page
            start: Index of the starting event

        Returns:
            Dictionary with contract events
        """
        params = {"contract": contract_address, "limit": limit, "start": start}

        if event_name:
            params["event_name"] = event_name

        if block_number is not None:
            params["block_number"] = block_number

        return await self._request("contract/events", params)

    async def get_contract_code(self, contract_address: str) -> Dict[str, Any]:
        """
        Get contract code.

        Args:
            contract_address: Contract address

        Returns:
            Dictionary with contract code
        """
        params = {"contract": contract_address}
        return await self._request("contract/code", params)

    # Block Endpoints

    async def get_block_by_num(self, num: int) -> Dict[str, Any]:
        """
        Get block by number.

        Args:
            num: Block number

        Returns:
            Dictionary with block information
        """
        params = {"num": num}
        return await self._request("block", params)

    async def get_latest_block(self) -> Dict[str, Any]:
        """
        Get latest block information.

        Returns:
            Dictionary with latest block information
        """
        return await self._request("block/latest")

    async def get_blocks(
        self, limit: int = 20, start: int = 0, sort: str = "-number"
    ) -> Dict[str, Any]:
        """
        Get list of blocks.

        Args:
            limit: Number of results per page
            start: Index of the starting block
            sort: Sort field (e.g. "-number" for newest first)

        Returns:
            Dictionary with block list
        """
        params = {"limit": limit, "start": start, "sort": sort}
        return await self._request("blocks", params)

    async def get_block_tx_id(self, hash: str) -> Dict[str, Any]:
        """
        Get transactions for a block by hash.

        Args:
            hash: Block hash

        Returns:
            Dictionary with block transactions
        """
        params = {"hash": hash}
        return await self._request("block/tx", params)

    async def get_block_transactions(
        self, num: int, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get transactions for a block by number.

        Args:
            num: Block number
            limit: Number of results per page
            start: Index of the starting transaction

        Returns:
            Dictionary with block transactions
        """
        params = {"num": num, "limit": limit, "start": start}
        return await self._request("block/tx", params)

    # Witness (Super Representative) Endpoints

    async def get_witnesses(self) -> Dict[str, Any]:
        """
        Get list of Super Representatives.

        Returns:
            Dictionary with SR list
        """
        return await self._request("witness")

    async def get_witness_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about witnesses.

        Returns:
            Dictionary with witness statistics
        """
        return await self._request("witness/statistics")

    async def get_witness_details(self, address: str) -> Dict[str, Any]:
        """
        Get details about a specific witness.

        Args:
            address: Witness address

        Returns:
            Dictionary with witness details
        """
        params = {"address": address}
        return await self._request("witness/details", params)

    async def get_witness_votes(
        self, address: str, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get votes for a witness.

        Args:
            address: Witness address
            limit: Number of results per page
            start: Index of the starting vote

        Returns:
            Dictionary with votes for the witness
        """
        params = {"address": address, "limit": limit, "start": start}
        return await self._request("vote/witness", params)

    # Homepage & Search Endpoints

    async def search(self, query: str) -> Dict[str, Any]:
        """
        Search for blocks, addresses, transactions, tokens or contracts.

        Args:
            query: Search query

        Returns:
            Dictionary with search results
        """
        params = {"searchInAll": "true", "query": query}
        return await self._request("search", params)

    async def get_system_status(self) -> Dict[str, Any]:
        """
        Get TRON system status.

        Returns:
            Dictionary with system status
        """
        return await self._request("system/status")

    async def get_top_accounts(self, limit: int = 20, start: int = 0) -> Dict[str, Any]:
        """
        Get top accounts by balance.

        Args:
            limit: Number of results per page
            start: Index of the starting account

        Returns:
            Dictionary with top accounts
        """
        params = {"limit": limit, "start": start}
        return await self._request("account/list/top", params)

    async def get_top_tokens(self, limit: int = 20, start: int = 0) -> Dict[str, Any]:
        """
        Get top tokens by market cap.

        Args:
            limit: Number of results per page
            start: Index of the starting token

        Returns:
            Dictionary with top tokens
        """
        params = {"limit": limit, "start": start}
        return await self._request("token/list/top", params)

    # Wallet Endpoints

    async def get_wallet_trc20_balance(
        self, address: str, start: int = 0, limit: int = 20
    ) -> Dict[str, Any]:
        """
        Get TRC20 balance for a wallet.

        Args:
            address: Wallet address
            start: Index of the starting token
            limit: Number of results per page

        Returns:
            Dictionary with TRC20 balances
        """
        params = {"address": address, "start": start, "limit": limit}
        return await self._request("wallet/trc20token", params)

    async def get_wallet_transactions(
        self, address: str, limit: int = 20, start: int = 0
    ) -> Dict[str, Any]:
        """
        Get transactions for a wallet.

        Args:
            address: Wallet address
            limit: Number of results per page
            start: Index of the starting transaction

        Returns:
            Dictionary with wallet transactions
        """
        params = {"address": address, "limit": limit, "start": start}
        return await self._request("wallet/transaction", params)

    async def get_wallet_stats(self, address: str) -> Dict[str, Any]:
        """
        Get statistics for a wallet.

        Args:
            address: Wallet address

        Returns:
            Dictionary with wallet statistics
        """
        params = {"address": address}
        return await self._request("wallet/stats", params)

    # Statistics Endpoints

    async def get_market_data(self) -> Dict[str, Any]:
        """
        Get market data.

        Returns:
            Dictionary with market data
        """
        return await self._request("market/data")

    async def get_transaction_stats(
        self, type_str: str = "all", time_dimension: str = "day"
    ) -> Dict[str, Any]:
        """
        Get transaction statistics.

        Args:
            type_str: Transaction type (all/transfer/freeze/etc.)
            time_dimension: Time dimension (hour/day/week/month)

        Returns:
            Dictionary with transaction statistics
        """
        params = {"type": type_str, "time_dimension": time_dimension}
        return await self._request("transaction/stats", params)

    async def get_single_chart_data(self, chart_name: str) -> Dict[str, Any]:
        """
        Get data for a specific chart.

        Args:
            chart_name: Chart name (e.g. "trx_price", "tps", etc.)

        Returns:
            Dictionary with chart data
        """
        params = {"chartName": chart_name}
        return await self._request("data/charts/singleChart", params)

    async def get_defi_stats(self) -> Dict[str, Any]:
        """
        Get DeFi statistics.

        Returns:
            Dictionary with DeFi statistics
        """
        return await self._request("defi/stats")

    # Deep Analysis Endpoints

    async def get_address_growth(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get address growth over time.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with address growth data
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("analysis/address/growth", params)

    async def get_transaction_growth(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get transaction growth over time.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with transaction growth data
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("analysis/transaction/growth", params)

    async def get_transaction_count_by_type(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get transaction count by type.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with transaction count by type
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("analysis/transaction/count-by-type", params)

    async def get_energy_consumption(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get energy consumption over time.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with energy consumption data
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("analysis/energy/consumption", params)

    # Security Service Endpoints

    async def get_address_security_info(self, address: str) -> Dict[str, Any]:
        """
        Get security information for an address.

        Args:
            address: TRON account address

        Returns:
            Dictionary with address security information
        """
        params = {"address": address}
        return await self._request("security/address", params)

    async def get_transaction_security_info(self, hash: str) -> Dict[str, Any]:
        """
        Get security information for a transaction.

        Args:
            hash: Transaction hash

        Returns:
            Dictionary with transaction security information
        """
        params = {"hash": hash}
        return await self._request("security/transaction", params)

    async def get_contract_security_info(self, contract_address: str) -> Dict[str, Any]:
        """
        Get security information for a contract.

        Args:
            contract_address: Contract address

        Returns:
            Dictionary with contract security information
        """
        params = {"contract": contract_address}
        return await self._request("security/contract", params)

    # Protocol Revenue Endpoints

    async def get_protocol_fee_status(self) -> Dict[str, Any]:
        """
        Get current protocol fee status.

        Returns:
            Dictionary with protocol fee status
        """
        return await self._request("system/protocolFeeBurnStatus")

    async def get_protocol_fee_history(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get protocol fee history.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with protocol fee history
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("system/protocolFeeHistory", params)

    async def get_protocol_fee_distribution(
        self,
        time_dimension: str = "day",
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Get protocol fee distribution.

        Args:
            time_dimension: Time dimension (hour/day/week/month)
            start_timestamp: Start time (milliseconds)
            end_timestamp: End time (milliseconds)

        Returns:
            Dictionary with protocol fee distribution data
        """
        params = {"time_dimension": time_dimension}

        if start_timestamp is not None:
            params["start_timestamp"] = start_timestamp

        if end_timestamp is not None:
            params["end_timestamp"] = end_timestamp

        return await self._request("system/protocolFeeDistribution", params)

    # Synchronous methods

    def get_account_sync(self, address: str) -> Dict[str, Any]:
        """
        Synchronous version of get_account.

        Args:
            address: TRON account address

        Returns:
            Dictionary with account information
        """
        params = {"address": address}
        return self._request_sync("account", params)

    def get_transactions_sync(
        self,
        address: Optional[str] = None,
        limit: int = 20,
        start: int = 0,
        sort: str = "-timestamp",
        count: bool = True,
    ) -> Dict[str, Any]:
        """
        Synchronous version of get_transactions.

        Args:
            address: TRON account address
            limit: Number of results per page
            start: Index of the starting transaction
            sort: Sort field (e.g. "-timestamp" for newest first)
            count: Whether to include total count

        Returns:
            Dictionary with transaction list
        """
        params = {
            "limit": limit,
            "start": start,
            "sort": sort,
            "count": str(count).lower(),
        }

        if address:
            params["address"] = address

        return self._request_sync("transaction", params)

    def get_token_info_sync(self, token_id: str) -> Dict[str, Any]:
        """
        Synchronous version of get_token_info.

        Args:
            token_id: Token ID or name

        Returns:
            Dictionary with token information
        """
        params = {"id": token_id}
        return self._request_sync("token", params)

    def get_latest_block_sync(self) -> Dict[str, Any]:
        """
        Synchronous version of get_latest_block.

        Returns:
            Dictionary with latest block information
        """
        return self._request_sync("block/latest")

    def search_sync(self, query: str) -> Dict[str, Any]:
        """
        Synchronous version of search.

        Args:
            query: Search query

        Returns:
            Dictionary with search results
        """
        params = {"searchInAll": "true", "query": query}
        return self._request_sync("search", params)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._session:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.close())
            else:
                loop.run_until_complete(self.close())
