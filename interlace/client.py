import json
import logging
import os
import time
from typing import Dict, Optional
from urllib.parse import urljoin

import requests

from config import INTERLACE_DEV, INTERLACE_MODE, INTERLACE_PROD
from utils.logger import logger

from .exceptions import APIError, AuthenticationError, InterlaceError
from .resources.accounts import Accounts
from .resources.authentication import Authentication
from .resources.business_account import BusinessAccount
from .resources.crypto_assets import Convert, Wallets
from .resources.funding import Funding
from .resources.infinity_card import Budgets, InfinityCard
from .resources.pay import Charges, Config, Refunds
from .resources.payout import Payees, Payouts


class InterlaceClient:
    """Main client for interacting with the Interlace API."""

    def __init__(self):
        """
        Initializes the client and handles token validation/renewal.
        """
        self.mode = INTERLACE_MODE
        self.config = INTERLACE_DEV if self.mode == "dev" else INTERLACE_PROD
        self.base_url = self.config.get('base_url', 'http://localhost')

        # Validate core configuration first
        self._validate_core_config()

        # Initialize resources needed for authentication
        self._init_resources()

        # Initialize session after resources
        self.session = requests.Session()
        self.headers = {}

        # Handle token initialization/validation
        self._initialize_tokens()

    def _validate_core_config(self):
        """Validates essential configuration parameters"""
        required_keys = [
            'account_id',
            'client_id',
            'client_secret',
            'redirect_uri',
            'base_url']
        missing = [k for k in required_keys if not self.config.get(k)]

        if missing:
            raise InterlaceError(
                f"Missing required config keys in {self.mode} section: {missing}"
            )

    def _initialize_tokens(self):
        """Handles token validation and initial acquisition"""
        if self._is_token_valid():
            logger.info("Using existing valid access token")
            # Set header from config dictionary
            self.headers['x-access-token'] = self.config.get('access_token')
            return

        logger.info("No valid tokens found, initiating authentication flow")
        try:
            token_data = self.authentication.generate_access_token()
            self._update_tokens(token_data)
        except Exception as e:
            raise InterlaceError(f"Initial auth failed: {str(e)}")

    def _is_token_valid(self) -> bool:
        """Checks if existing token is still valid"""
        access_token = self.config.get('access_token')
        token_expiry = self.config.get('token_expiry')

        if not access_token or not token_expiry:
            return False

        # Check expiration with 60 second buffer
        return time.time() < (token_expiry - 60)

    def _update_tokens(self, token_data: dict):
        """Updates tokens using API response format"""
        # Update config dictionary with new tokens
        self.config.update({
            'access_token': token_data.get('accessToken'),
            'refresh_token': token_data.get('refreshToken'),
            'token_expiry': time.time() + int(token_data.get('expiresIn', 0))
        })

        # Set header from config dictionary
        self.headers['x-access-token'] = self.config['access_token']
        self._save_config()

    def _save_config(self):
        """Persists tokens to params.json"""
        try:
            import stat
            params_path = os.path.join(
                os.path.dirname(
                    os.path.dirname(
                        os.path.abspath(__file__))),
                'config/params.json')

            exists = os.path.exists(params_path)
            writable = os.access(params_path, os.W_OK)
            if exists and not writable:
                os.chmod(params_path, stat.S_IWUSR | stat.S_IRUSR)

            # Read existing configuration, or use an empty dict if reading fails
            try:
                with open(params_path, 'r') as f:
                    params = json.load(f)
            except Exception:
                params = {}

            # Update token configuration under the current mode
            interlace_config = params.setdefault('interlace', {})
            token_expiry = self.config['token_expiry']
            interlace_mode_config = interlace_config.setdefault(self.mode, {})
            interlace_mode_config.update({
                'access_token': self.config['access_token'],
                'refresh_token': self.config['refresh_token'],
                'token_expiry': token_expiry,
            })

            # # Write updated configuration back to the file
            # with open(params_path, 'w') as f:
            #     json.dump(params, f, indent=2)

        except Exception as e:
            logger.error(f"Failed to save tokens: {str(e)}")
            raise InterlaceError("Could not persist token updates")

    def _get_base_url(self) -> str:
        """Gets base URL from loaded configuration"""
        return self.config['base_url']

    def _init_resources(self):
        """Initializes all the API resource classes."""
        # Initialize authentication first
        self.authentication = Authentication(self)

        # Then other resources
        self.accounts = Accounts(self)
        self.funding = Funding(self)
        # self.notifications = Notifications(self) # Endpoint listed

        # Infinity Card
        self.budgets = Budgets(self)
        self.infinity_card = InfinityCard(self)

        # Business Account
        self.business_account = BusinessAccount(self)

        # Crypto Assets
        self.wallets = Wallets(self)
        self.convert = Convert(self)

        # Payout
        self.payees = Payees(self)
        self.payouts = Payouts(self)

        # Pay
        self.charges = Charges(self)
        self.refunds = Refunds(self)
        # Renamed from Config to avoid name clash
        self.config_api = Config(self)

    def _is_token_expired(self):
        """Checks if the access token is expired or close to expiring."""
        token_expiry = self.config.get('token_expiry')
        if not token_expiry:
            return True  # Consider expired if no expiry time is set
        safety_margin = 60  # Refresh 60 seconds before actual expiry
        return time.time() >= (token_expiry - safety_margin)

    def _request(self, method, path, params=None, data=None, json_data=None,
                 files=None, requires_auth=True):
        """Makes an HTTP request to the Interlace API."""
        url = urljoin(self.base_url, path)

        headers = {
            'accept': 'application/json',
        }

        if requires_auth:
            # Check token validity before each authenticated request
            if self._is_token_expired():
                logger.debug("Access token expired, refreshing...")
                try:
                    self.authentication.refresh_access_token()
                except Exception as e:
                    self.authentication.generate_access_token()

            # Get access token from config dictionary
            headers['x-access-token'] = self.config['access_token']

        try:
            response = self.session.request(
                method=method,
                url=url,
                params=params,
                data=data,        # For form-encoded data
                json=json_data,   # For JSON body
                headers=headers,
                files=files       # For file uploads
            )

            # Check for specific auth error (invalid token)
            if response.status_code not in [200, 201, 204] and requires_auth:
                # Retry ONCE after refreshing token
                print("Received 401, attempting token refresh and retry...")
                try:
                    self.authentication.refresh_access_token()
                except Exception as e:
                    self.authentication.generate_access_token()
                # Update header with new token
                headers['x-access-token'] = self.config['access_token']
                response = self.session.request(
                    method=method,
                    url=url,
                    params=params,
                    data=data,
                    json=json_data,
                    headers=headers,
                    files=files)

            # Raise HTTPError for bad responses (4xx/5xx) after retry
            response.raise_for_status()

            # Handle responses with no content
            if response.status_code == 204 or not response.content:
                return None

            return response.json()

        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code
            try:
                response_data = e.response.json()
            except json.JSONDecodeError:
                response_data = e.response.text

            if status_code == 401:
                error_message = f"Authentication failed: {response_data}"
                # Check common invalid token messages
                resp_text = str(response_data).lower()
                token_is_invalid = (
                    "invalid_token" in resp_text or
                    "token expired" in resp_text
                )
                if token_is_invalid:
                    # Clear potentially invalid token
                    self.config['access_token'] = None
                    # Don't clear refresh token; it might still work
                    self._save_config()
                    error_message += " Access token cleared."
                raise AuthenticationError(
                    error_message, status_code, response_data
                )
            else:
                raise APIError(
                    f"API request failed: {response_data}",
                    status_code, response_data
                )

        except requests.exceptions.RequestException as e:
            # Handle network errors, timeouts, etc.
            error_msg = f"Network request failed: {e}"
            raise InterlaceError(error_msg)

    # Convenience methods for HTTP verbs
    def get(self, path, params=None, requires_auth=True):
        return self._request(
            'GET', path, params=params, requires_auth=requires_auth
        )

    def post(self, path, data=None, json_data=None, files=None,
             requires_auth=True):
        return self._request(
            'POST', path, data=data, json_data=json_data,
            files=files, requires_auth=requires_auth
        )

    def put(self, path, data=None, json_data=None, requires_auth=True):
        return self._request(
            'PUT', path, data=data, json_data=json_data,
            requires_auth=requires_auth
        )

    def delete(self, path, data=None, json_data=None, requires_auth=True):
        return self._request(
            'DELETE', path, data=data, json_data=json_data,
            requires_auth=requires_auth
        )
