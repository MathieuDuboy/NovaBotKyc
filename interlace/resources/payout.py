class Payees:
    """Handles payee related API calls for payouts."""

    def __init__(self, client):
        self._client = client
        # Base path inferred
        self.base_path = "/open-api/v1/payees"

    def get_required_fields(self, fields_request):
        """Gets the required fields for creating a payee bank account."""
        # Assuming fields_request: country, currency, payout_method etc.
        path = f"{self.base_path}/required_fields"
        return self._client.post(path, json_data=fields_request)

    def delete_payee_bank_account(self, payee_id, bank_account_id):
        """Deletes a payee bank account."""
        # Path structure assumed, adjust if necessary based on API details
        path = f"{self.base_path}/{payee_id}/bank_accounts/{bank_account_id}"
        return self._client.delete(path)  # Expect 204

    def create_payee_bank_account(self, payee_id, bank_account_data):
        """Creates a new bank account for a payee."""
        # Path structure assumed
        path = f"{self.base_path}/{payee_id}/bank_accounts"
        return self._client.post(path, json_data=bank_account_data)

    def list_all_payee_bank_accounts(self, payee_id, params=None):
        """Lists all bank accounts for a specific payee."""
        # Path structure assumed
        path = f"{self.base_path}/{payee_id}/bank_accounts"
        return self._client.get(path, params=params)


class Payouts:
    """Handles payout transaction related API calls."""

    def __init__(self, client):
        self._client = client
        # Base path inferred
        self.base_path = "/open-api/v1/payouts"

    def get_quotation(self, quotation_request):
        """Gets a quotation for a payout transaction."""
        path = f"{self.base_path}/quotation"
        return self._client.post(path, json_data=quotation_request)

    def check_payout(self, check_data):
        """Checks the status or details of a potential payout."""
        # Endpoint name ambiguous, assuming checks params/feasibility
        path = f"{self.base_path}/check"
        return self._client.post(path, json_data=check_data)

    def create_payout_transaction(self, payout_data):
        """Creates a new payout transaction."""
        return self._client.post(self.base_path, json_data=payout_data)

    def list_all_payouts(self, params=None):
        """Lists all payout transactions."""
        return self._client.get(self.base_path, params=params) 