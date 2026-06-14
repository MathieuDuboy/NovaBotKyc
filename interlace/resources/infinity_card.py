from typing import Any, Dict, List, Optional

from .models import (Budget, BudgetTransaction, Card, CardDetails, Cardholder,
                     CardTransaction)


class Budgets:
    """Handles budget-related API calls for Infinity Cards."""

    def __init__(self, client):
        self._client = client
        self.base_path = "/open-api/v1/budget"

    def create_budget(self, budget_data):
        """Creates a new budget."""
        return self._client.post(self.base_path, json_data=budget_data)

    def update_budget(self, budget_id, update_data):
        """Updates an existing budget."""
        path = f"{self.base_path}/{budget_id}"
        return self._client.put(path, json_data=update_data)

    def list_all_budgets(self, params=None):
        """Lists all budgets."""
        return self._client.get(self.base_path, params=params)

    def delete_budget(self, budget_id):
        """Deletes a budget."""
        path = f"{self.base_path}/{budget_id}"
        # Returns 204 No Content on success, _request handles this
        return self._client.delete(path)

    def increase_budget_balance(self, budget_id, amount_data):
        """Increases the balance of a budget."""
        # Assuming amount_data = {"amount": 100.00, "currency": "USD"}
        path = f"{self.base_path}/{budget_id}/balance/increase"
        return self._client.post(path, json_data=amount_data)

    def decrease_budget_balance(self, budget_id, amount_data):
        """Decreases the balance of a budget."""
        path = f"{self.base_path}/{budget_id}/balance/decrease"
        return self._client.post(path, json_data=amount_data)

    def list_all_budget_transactions(
            self, budget_id, params=None) -> List[BudgetTransaction]:
        """Lists all transactions for a specific budget."""
        path = f"{self.base_path}/{budget_id}/transactions"
        response = self._client.get(path, params=params)

        # Extract transaction data from the response
        transactions_data = response.get('data', {}).get('data', [])

        # Convert to BudgetTransaction objects
        return [
            BudgetTransaction.from_dict(transaction_data)
            for transaction_data in transactions_data
        ]


class InfinityCard:
    """Handles Infinity Card related API calls."""

    def __init__(self, client):
        self._client = client
        self.base_path = "/open-api/v1/cards"
        self.bins_path = "/open-api/v1/cards/bins"

    def list_maintained_bins(self, params=None):
        """Lists all card BINs currently under maintenance."""
        path = f"{self.bins_path}/maintenance"
        return self._client.get(path, params=params)

    def list_available_bins(self, params=None):
        """Lists all available card BINs."""
        path = f"{self.bins_path}"
        return self._client.get(path, params=params)

    def query_bin_scenarios(self, bin_number):
        """Queries a card BIN for high success rate transaction scenarios."""
        path = f"{self.bins_path}/{bin_number}/scenarios"
        return self._client.get(path)

    def check_create_card_params(self, params_data):
        """Checks parameters for creating an Infinity Card."""
        path = f"{self.base_path}/parameters_check"
        return self._client.post(path, json_data=params_data)

    def create_infinity_card(self, card_data):
        """Creates a new Infinity Card."""
        return self._client.post(self.base_path, json_data=card_data)

    def delete_infinity_card(self, card_id):
        """Deletes an Infinity Card."""
        path = f"{self.base_path}/{card_id}"
        return self._client.delete(path)  # Expect 204 No Content

    def list_all_infinity_cards(
            self, params: Optional[Dict[str, Any]] = None) -> List[Card]:
        """Lists all Infinity Cards with pagination support."""
        all_cards = []
        page = 0
        page_size = 250  # Maximum page size to minimize API calls

        while True:
            # Set pagination parameters
            if params is None:
                params = {}
            params['page'] = page
            params['limit'] = page_size

            response = self._client.get(self.base_path, params=params)

            # Extract card data from the response
            cards_data = response.get('data', {}).get('data', [])

            # If no cards returned, we've reached the end
            if not cards_data:
                break

            # Convert to Card objects and add to our list
            all_cards.extend([
                Card.from_dict(card_data) for card_data in cards_data
            ])

            # If we got fewer cards than the page size, we've reached the end
            if len(cards_data) < page_size:
                break

            # Move to next page
            page += 1

        return all_cards

    def infinity_card_transfer_in(self, transfer_data):
        """Transfers funds into an Infinity Card."""
        path = f"{self.base_path}/transfer/in"
        return self._client.post(path, json_data=transfer_data)

    def infinity_card_transfer_out(self, transfer_data):
        """Transfers funds out of an Infinity Card."""
        path = f"{self.base_path}/transfer/out"
        return self._client.post(path, json_data=transfer_data)

    def freeze_infinity_card(self, card_id):
        """Freezes an Infinity Card."""
        path = f"{self.base_path}/suspend"
        return self._client.put(path, json_data={"cardId": card_id})

    def unfreeze_infinity_card(self, card_id):
        """Unfreezes an Infinity Card."""
        path = f"{self.base_path}/enable"
        return self._client.put(path, json_data={"cardId": card_id})

    def set_velocity_control(self, card_id, control_data):
        """Sets velocity controls for an Infinity Card."""
        path = f"{self.base_path}/{card_id}/velocity_control"
        return self._client.put(path, json_data=control_data)

    def freeze_infinity_card_balance(self, card_id, freeze_data):
        """Freezes the balance of an Infinity Card."""
        path = f"{self.base_path}/{card_id}/balance/frozen"
        return self._client.post(path, json_data=freeze_data)

    def unfreeze_infinity_card_balance(self, card_id, unfreeze_data):
        """Unfreezes the balance of an Infinity Card."""
        path = f"{self.base_path}/{card_id}/balance/unfrozen"
        return self._client.post(path, json_data=unfreeze_data)

    def get_infinity_card_details(self, card_id: str) -> CardDetails:
        """Gets the details of an Infinity Card."""
        path = f"{self.base_path}/info?cardId={card_id}"
        response = self._client.get(path)

        # Extract card data from the response
        card_data = response.get('data', {})

        # For debugging purposes, log the received data structure
        import logging
        logging.getLogger(__name__).debug(f"Card data received: {card_data}")

        # Convert to CardDetails object
        return CardDetails.from_dict(card_data)

    def get_infinity_card_transaction(self, card_id, transaction_id):
        """Gets details of a specific Infinity Card transaction."""
        path = f"{self.base_path}/{card_id}/transactions/{transaction_id}"
        return self._client.get(path)

    def list_all_infinity_card_transactions(
            self,
            params: Optional[Dict[str, Any]] = {}
    ) -> List[CardTransaction]:
        """Lists all transactions for an Infinity Card using pagination
        parameters to retrieve all results in one request."""
        all_transactions = []
        page = params.get("page", 0)
        page_size = params.get("limit", 250)
        path = f"{self.base_path}/transactions"

        while True:
            # Set pagination parameters for current page
            params["page"] = page
            params["limit"] = page_size

            response = self._client.get(path, params=params)
            transactions_data = response.get('data', [])

            if not transactions_data:
                break

            all_transactions.extend(
                [CardTransaction.from_dict(tx) for tx in transactions_data]
            )

            if len(transactions_data) < page_size:
                break

            page += 1

        return all_transactions

    def create_cardholder(self, cardholder_data: Dict[str, Any]) -> Cardholder:
        """Creates a new cardholder."""
        path = "/open-api/v1/infinity/cardholders"
        response = self._client.post(path, json_data=cardholder_data)

        # Extract cardholder data from the response
        cardholder_data = response.get('data', {})

        # Convert to Cardholder object
        return Cardholder.from_dict(cardholder_data)

    def get_cardholder_details(self, cardholder_id: str) -> Cardholder:
        """Get details for a specific cardholder"""
        path = f"/open-api/v1/infinity/cardholders/{cardholder_id}"
        response = self._client.get(path)

        # Extract cardholder data from the response
        cardholder_data = response.get('data', {})

        # Convert to Cardholder object
        return Cardholder.from_dict(cardholder_data)

    def list_all_cardholders(
            self, params: Optional[Dict[str, Any]] = None) -> List[Cardholder]:
        """List all cardholders"""
        path = "/open-api/v1/infinity/cardholders"
        response = self._client.get(path, params=params)

        # Extract cardholder data from the response
        cardholders_data = response.get('data', {}).get('data', [])

        # Convert to Cardholder objects
        return [Cardholder.from_dict(cardholder_data)
                for cardholder_data in cardholders_data]

    def list_all_budgets(
        self, params: Optional[Dict[str, Any]] = None
    ) -> List[Budget]:
        """Get a list of all budgets"""
        response = self._client.get('/budgets', params=params)

        # Extract budget data from the response
        budgets_data = response.get('data', {}).get('data', [])

        # Convert to Budget objects
        return [Budget.from_dict(budget_data) for budget_data in budgets_data]
