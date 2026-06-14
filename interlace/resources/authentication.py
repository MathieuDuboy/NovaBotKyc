import time
from urllib.parse import urlencode, urljoin


class Authentication:
    """Handles authentication-related API calls using the direct flow."""

    def __init__(self, client):
        self._client = client
        self.authorize_path = "/open-api/oauth/authorize"
        self.access_token_path = "/open-api/oauth/access-token"
        # Assuming refresh still uses the standard token endpoint
        self.refresh_token_path = "/open-api/oauth/refresh-token"

    def _get_a_code(self):
        """Gets the authorization code directly via GET request."""
        params = {
            'clientId': self._client.config['client_id']
        }
        # This GET request returns the code directly in the JSON response
        response_data = self._client.get(
            self.authorize_path, params=params, requires_auth=False)
        if not response_data or 'code' not in response_data:
            raise self._client.AuthenticationError(
                "Failed to get direct auth code from /authorize endpoint.",
                response_data=response_data
            )
        return response_data['code']

    def generate_access_token(self):
        """Gets code directly and exchanges it for an access token."""
        print("Getting direct authorization code...")
        auth_code = self._get_a_code()
        print(f"Received direct code: {auth_code}")

        print("Exchanging direct code for access token...")
        json_payload = {
            'clientId': self._client.config['client_id'],
            'clientSecret': self._client.config['client_secret'],
            'code': auth_code
        }
        # This POST request uses the /access-token endpoint and JSON payload
        response_data = self._client.post(
            self.access_token_path, json_data=json_payload, requires_auth=False
        )

        # Update client's token info and save
        self._update_client_tokens(response_data)
        print("Access token generated and saved.")
        return response_data

    def refresh_access_token(self):
        """Refreshes an expired access token using a refresh token."""
        if not self._client.config['refresh_token']:
            raise self._client.AuthenticationError(
                "Cannot refresh token: No refresh token available."
            )

        # Standard refresh uses form data and /token endpoint
        data = {
            'client_id': self._client.config['client_id'],
            'refresh_token': self._client.config['refresh_token'],
        }
        response_data = self._client.post(
            self.refresh_token_path, data=data, requires_auth=False)

        # Update client's token info and save
        self._update_client_tokens(response_data)
        return response_data

    def _update_client_tokens(self, token_info):
        """Helper to update token attributes on the client and save config."""
        self._client.config['access_token'] = token_info.get(
            'accessToken')  # Note: key is accessToken
        self._client.config['timestamp'] = token_info.get('timestamp')
        expires_in = token_info.get('expiresIn')  # Note: key is expiresIn
        try:
            self._client.config['refresh_token'] = token_info.get(
                'refreshToken')  # Note: key is refreshToken
        except (ValueError, TypeError):
            pass

        if expires_in is not None:
            try:
                # Calculate expiry timestamp (seconds since epoch)
                self._client.config['token_expiry'] = int(
                    self._client.config['timestamp']) + int(expires_in)
            except (ValueError, TypeError):
                print(f"Warning: Invalid expiresIn value received: {expires_in}")
                self._client.config['token_expiry'] = None  # Set expiry to unknown
        else:
            self._client.config['token_expiry'] = None

        self._client._save_config()
