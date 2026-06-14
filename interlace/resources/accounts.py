from typing import Dict, Any, List, Optional
from .models import Account, User, Balance

class AccountsResource:
    """Resource for interacting with Interlace Accounts API"""

    def __init__(self, client):
        self.client = client

    def list_all_accounts(self, params: Optional[Dict[str, Any]] = None) -> List[Account]:
        """Get a list of all accounts"""
        response = self.client._request('GET', '/accounts', params=params)
        
        # Extract account data from the response
        accounts_data = response.get('data', {}).get('data', [])
        
        # Convert to Account objects
        return [Account.from_dict(account_data) for account_data in accounts_data]

    def get_account_details(self, account_id: str) -> Account:
        """Get details for a specific account"""
        response = self.client._request('GET', f'/accounts/{account_id}')
        
        # Extract account data from the response
        account_data = response.get('data', {})
        
        # Convert to Account object
        return Account.from_dict(account_data)

    def list_all_balances(self, params: Optional[Dict[str, Any]] = None) -> List[Balance]:
        """Get a list of all balances"""
        response = self.client._request('GET', '/balances', params=params)
        
        # Extract balance data from the response
        balances_data = response.get('data', {}).get('data', [])
        
        # Convert to Balance objects
        return [Balance.from_dict(balance_data) for balance_data in balances_data]

    def get_user_info(self, user_id: str) -> User:
        """Get user information"""
        response = self.client._request('GET', f'/users/{user_id}')
        
        # Extract user data from the response
        user_data = response.get('data', {})
        
        # Convert to User object
        return User.from_dict(user_data)

class Accounts:
    """Handles account-related API calls."""

    def __init__(self, client):
        self._client = client
        self.base_path = "/open-api/v1/accounts"

    def list_account_fee_rates(self):
        """Lists fee rates for a specific account."""
        path = f"{self.base_path}/fees"
        return self._client.get(path)

    def create_account(self, account_data):
        """Creates a new account."""
        # Docs don't specify payload structure, assuming json_data
        # User needs to provide the correct dict structure in account_data
        path = f"{self.base_path}/register"
        return self._client.post(path, json_data=account_data)

    def list_all_users(self, params=None):
        """Lists all users associated with a specific account."""
        path = f"{self.base_path.replace('accounts', 'users')}"
        return self._client.get(path, params=params)

    def upload_file(self, file_path, file_type, purpose):
        """Uploads a file (e.g., for KYC)."""
        # This likely requires multipart/form-data
        path = "/open-api/v1/files"
        try:
            with open(file_path, 'rb') as f:
                files = {'file': (file_path, f)}
                data = {
                    'file_type': file_type,  # e.g., 'id_card_face'
                    'purpose': purpose      # e.g., 'kyc'
                }
                # The _request method in client.py handles files parameter
                return self._client.post(path, data=data, files=files)
        except FileNotFoundError:
            raise self._client.InterlaceError(f"File not found: {file_path}")
        except IOError as e:
            err_msg = f"Error reading file {file_path}: {e}"
            raise self._client.InterlaceError(err_msg)

    def ocr_id_card_face(self, file_id):
        """Performs OCR on an uploaded ID card face image."""
        path = "/open-api/v1/ocr/id_card_face"
        return self._client.post(path, json_data={'file_id': file_id})

    def ocr_id_card_back(self, file_id):
        """Performs OCR on an uploaded ID card back image."""
        path = "/open-api/v1/ocr/id_card_back"
        return self._client.post(path, json_data={'file_id': file_id})

    def ocr_passport(self, file_id):
        """Performs OCR on an uploaded passport image."""
        path = "/open-api/v1/ocr/passport"
        return self._client.post(path, json_data={'file_id': file_id})

    def submit_account_kyc(self, account_id, kyc_data):
        """Submits KYC information for an account."""
        # Assuming kyc_data is a dict matching the API spec
        path = f"{self.base_path}/{account_id}/kyc"
        return self._client.post(path, json_data=kyc_data)

    def reset_account_kyc(self, account_id):
        """Resets the KYC status for an account."""
        # API ref says POST, seems unusual for reset, following docs
        path = f"{self.base_path}/{account_id}/kyc/reset"
        return self._client.post(path)

    def get_face_authentication_url(self, account_id):
        """Gets a URL for face authentication."""
        # GET request according to docs
        path = f"{self.base_path}/{account_id}/face_authentication_url"
        return self._client.get(path)

    def face_authentication(self, account_id, auth_data):
        """Submits face authentication data."""
        # Assuming auth_data contains necessary fields like file_id or similar
        path = f"{self.base_path}/{account_id}/face_authentication"
        return self._client.post(path, json_data=auth_data)

    def get_account_kyc_information(self, account_id):
        """Retrieves KYC information for a specific account."""
        path = f"{self.base_path}/{account_id}/kyc"
        return self._client.get(path) 