class Funding:
    """Handles funding-related API calls (balances, transfers)."""

    def __init__(self, client):
        self._client = client
        self.balances_path = "/open-api/v1/balances"
        self.transfers_path = "/open-api/v1/asset/transfers"

    def list_all_balances(self, params=None):
        """Lists all balances, handling pagination to retrieve all results."""
        all_balances = []
        page = 0
        page_size = params.get("pageSize", 100) if params else 100

        while True:
            current_params = {"page": page, "limit": page_size}
            if params:
                current_params.update(params)
            response = self._client.get(
                self.balances_path,
                params=current_params
            )
            data = response.get("data", [])
            try:
                data = data.get("data", [])
            except Exception as e:
                print(f"Error getting balances: {e}")
                break
            all_balances.extend(data)
            total = response.get("data", {}).get("total", 0)
            if len(all_balances) >= total or not data:
                break
            page += 1

        return all_balances

    def create_transfer(self, transfer_data):
        """Creates a new transfer."""
        # Assuming transfer_data is a dict matching the API spec
        return self._client.post(self.transfers_path, json_data=transfer_data)

    def get_transfer(self, transfer_id):
        """Retrieves details for a specific transfer."""
        path = f"{self.transfers_path}/{transfer_id}"
        return self._client.get(path)
