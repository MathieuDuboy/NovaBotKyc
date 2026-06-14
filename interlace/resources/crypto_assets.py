from .models import Wallet, Deposit, Withdrawal
from typing import List, Dict, Any


class Wallets:
    """Handles crypto wallet related API calls."""

    def __init__(self, client):
        self._client = client
        self.addresses_path = "/open-api/v1/asset/wallets/addresses"
        self.deposits_path = "/open-api/v1/asset/wallets/deposits"
        self.withdrawals_path = "/open-api/v1/asset/wallets/withdrawals"
        self.bills_path = "/open-api/v1/asset/wallets/bills"

    def create_blockchain_address(self, address_data) -> Wallet:
        """Creates a new blockchain address."""
        # Assuming address_data = {"chain": "TRX", "alias": "My TRON Addr"}
        response = self._client.post(self.addresses_path, json_data=address_data)
        
        # Extract wallet data from the response
        wallet_data = response.get('data', {})
        
        # Convert to Wallet object
        return Wallet.from_dict(wallet_data)

    def list_all_addresses(self, params=None) -> List[Wallet]:
        """Lists all blockchain addresses."""
        response = self._client.get(self.addresses_path, params=params)
        
        # Extract wallet data from the response
        wallets_data = response.get('data', {}).get('data', [])
        
        # Convert to Wallet objects
        return [Wallet.from_dict(wallet_data) for wallet_data in wallets_data]

    def list_all_deposit_history(self, params=None) -> List[Deposit]:
        """Lists all deposit history."""
        response = self._client.get(self.deposits_path, params=params)
        
        # Extract deposit data from the response
        deposits_data = response.get('data', {}).get('data', [])
        
        # Convert to Deposit objects
        return [Deposit.from_dict(deposit_data) for deposit_data in deposits_data]

    def get_withdraw_coin_fee(self, params) -> Dict[str, Any]:
        """Gets the withdrawal fee for a specific coin/chain."""
        # Assuming params = {"coin": "USDT", "chain": "TRX"}
        path = f"{self.withdrawals_path}/fee"
        response = self._client.get(path, params=params)
        
        # Return the fee data
        return response.get('data', {})

    def withdraw_coin(self, withdrawal_data) -> Withdrawal:
        """Initiates a coin withdrawal."""
        # Assuming withdrawal_data contains coin, chain, address, amount etc.
        response = self._client.post(
            self.withdrawals_path, json_data=withdrawal_data
        )
        
        # Extract withdrawal data from the response
        withdrawal_data = response.get('data', {})
        
        # Convert to Withdrawal object
        return Withdrawal.from_dict(withdrawal_data)

    def list_all_withdrawal_history(self, params=None) -> List[Withdrawal]:
        """Lists all withdrawal history."""
        response = self._client.get(self.withdrawals_path, params=params)
        
        # Extract withdrawal data from the response
        withdrawals_data = response.get('data', {}).get('data', [])
        
        # Convert to Withdrawal objects
        withdrawals = [
            Withdrawal.from_dict(withdrawal_data)
            for withdrawal_data in withdrawals_data
        ]
        return withdrawals

    def list_all_bills(self, params=None) -> List[Dict[str, Any]]:
        """Lists all crypto bills/ledger entries."""
        response = self._client.get(self.bills_path, params=params)
        
        # Extract bill data from the response
        bills_data = response.get('data', {}).get('data', [])
        
        # Return list of bill dictionaries (no model defined for bills)
        return bills_data


class Convert:
    """Handles crypto conversion/trade related API calls."""

    def __init__(self, client):
        self._client = client
        self.base_path = "/open-api/v1/asset/convert"

    def get_trade_currency_pair(self, pair_symbol) -> Dict[str, Any]:
        """Gets details for a specific trading currency pair."""
        # e.g., pair_symbol = "BTC-USDT"
        path = f"{self.base_path}/currency_pairs/{pair_symbol}"
        response = self._client.get(path)
        
        # Return the currency pair data
        return response.get('data', {})

    def get_estimate_quote(self, quote_request) -> Dict[str, Any]:
        """Gets an estimated quote for a trade."""
        # Assuming quote_request = {"from_currency": "BTC", 
        #                          "to_currency": "USDT", "amount": "0.1"}
        path = f"{self.base_path}/estimate-quote"
        response = self._client.post(path, json_data=quote_request)
        
        # Return the quote data
        return response.get('data', {})

    def create_trade(self, trade_request) -> Dict[str, Any]:
        """Creates a new trade based on a quote or parameters."""
        # Assuming trade_request contains pair, amount, direction etc.
        path = f"{self.base_path}/trades"
        response = self._client.post(path, json_data=trade_request)
        
        # Return the trade data
        return response.get('data', {})

    def list_all_trades(self, params=None) -> List[Dict[str, Any]]:
        """Lists all past trades."""
        path = f"{self.base_path}/trades"
        response = self._client.get(path, params=params)
        
        # Extract trade data from the response
        trades_data = response.get('data', {}).get('data', [])
        
        # Return list of trade dictionaries
        return trades_data 