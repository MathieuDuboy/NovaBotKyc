class Charges:
    """Handles charge related API calls."""

    def __init__(self, client):
        self._client = client
        self.base_path = "/open-api/v1/charges"

    def create_charge(self, charge_data):
        """Creates a new charge."""
        return self._client.post(self.base_path, json_data=charge_data)

    def list_all_charges(self, params=None):
        """Lists all charges."""
        return self._client.get(self.base_path, params=params)

    def cancel_charge(self, charge_id):
        """Cancels a charge."""
        path = f"{self.base_path}/{charge_id}/cancel"
        return self._client.post(path)


class Refunds:
    """Handles refund related API calls."""

    def __init__(self, client):
        self._client = client
        # Base path inferred, assuming refunds are related to charges
        self.base_path = "/open-api/v1/refunds"  # Or maybe /charges/{id}/refunds?

    def create_refund(self, refund_data):
        """Creates a new refund."""
        # Assuming refund_data contains charge_id, amount etc.
        # Path might need adjustment based on actual API structure
        return self._client.post(self.base_path, json_data=refund_data)


class Config:
    """Handles configuration related API calls (Pay section)."""

    def __init__(self, client):
        self._client = client
        # Paths inferred
        self.channels_path = "/open-api/v1/config/channels"
        self.risk_token_path = "/open-api/v1/config/risk_token"

    def list_all_available_channels(self, params=None):
        """Lists all available payment channels."""
        return self._client.get(self.channels_path, params=params)

    def get_risk_client_access_token(self, token_request):
        """Gets a Risk Client Access Token."""
        # Assuming token_request contains necessary parameters
        return self._client.post(self.risk_token_path, json_data=token_request) 