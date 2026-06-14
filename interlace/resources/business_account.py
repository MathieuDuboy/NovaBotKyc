from .models import BankAccount, GlobalAccountTransaction
from typing import List

class BusinessAccount:
    """Handles Business Account related API calls."""

    def __init__(self, client):
        self._client = client
        # Base path inferred from endpoint structure
        self.global_accounts_path = "/open-api/v1/global_accounts"
        self.bank_accounts_path = "/open-api/v1/bank_accounts"

    def create_global_account(self, account_data):
        """Creates a new global account."""
        # Assuming account_data is a dict
        return self._client.post(
            self.global_accounts_path, json_data=account_data
        )

    def list_all_global_accounts(self, params=None) -> List[GlobalAccountTransaction]:
        """Lists all global accounts."""
        response = self._client.get(self.global_accounts_path, params=params)
        
        # Extract global account data from the response
        accounts_data = response.get('data', {}).get('data', [])
        
        # Convert to GlobalAccountTransaction objects
        return [GlobalAccountTransaction.from_dict(account_data) for account_data in accounts_data]

    def list_all_bank_accounts(self, params=None) -> List[BankAccount]:
        """Lists all bank accounts."""
        response = self._client.get(self.bank_accounts_path, params=params)
        
        # Extract bank account data from the response
        bank_accounts_data = response.get('data', {}).get('data', [])
        
        # Convert to BankAccount objects
        return [BankAccount.from_dict(bank_account_data) for bank_account_data in bank_accounts_data] 