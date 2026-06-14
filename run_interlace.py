#!/usr/bin/env python3
"""
Script to run the Interlace API client.

Usage:
  python run_interlace.py
"""
import asyncio
import json
import logging
import sys
import traceback

import config
from interlace.client import InterlaceClient
from utils.logger import logger


def get_config():
    """Get configuration from config.py"""
    return {
        'testing': config.get('testing', False),
        'testing_url': config.get('testing_url', '')
    }


def main():
    """Demonstrates the direct authentication flow."""
    try:
        # Initialize the client (reads config from params.json by default)
        logger.info("Initializing InterlaceClient...")
        client = InterlaceClient()
        # available_bins = client.infinity_card.list_available_bins()
        transactions = client.infinity_card.list_all_infinity_card_transactions()
        print(transactions)
        # if not available_bins or not available_bins.get('data'):
        #     raise Exception("No available BINs found")

        # # Get the first available BIN
        # supported_bin = available_bins['data'][0]['bin']

        # # Check if tokens already exist and are potentially valid
        # if client.config['access_token'] and not client._is_token_expired():
        #     logger.info("Existing valid access token found in params.json.")
        # else:
        #     logger.info("No valid access token found or token expired.")
        #     logger.info("Attempting to generate new token using direct flow...")
        #     # Generate new tokens using the direct flow
        #     try:
        #         token_info = client.authentication.generate_access_token()
        #         logger.info("\n--- New Token Information Received ---")
        #         logger.info(f"Access Token: {token_info.get('accessToken')}")
        #         logger.info(f"Refresh Token: {token_info.get('refreshToken')}")
        #         logger.info(f"Expires In: {token_info.get('expiresIn')}")
        #     except InterlaceError as auth_err:
        #         logger.error(f"\nError generating access token: {auth_err}")
        #         return  # Exit if we can't authenticate

        # # --- Example API Call (List Infinity Cards) ---
        # logger.info("\n--- Attempting Example API Call (List Infinity Cards) ---")
        # try:
        #     # Client instance should now have valid tokens
        #     # response = client.accounts.list_all_accounts({"id": client.config["account_id"]})
        #     # response = client.infinity_card.list_all_infinity_cards()
        #     infinity_cards = client.infinity_card.list_all_infinity_cards()
        #     # infinity_cards = response["data"]["data"]
        #     # infinity_cards = [
        #     #     card for card in infinity_cards if card["status"] == "Active"]
        #     for card in infinity_cards:
        #         card_details = client.infinity_card.get_infinity_card_details(card.id)
        #         logger.info(f"Card details for {card.id}:")
        #         logger.info(f"  Card Number: {card_details.card_no}")
        #         logger.info(f"  Expiry: {card_details.expiry_date}")
        #         logger.info(f"  CVV: {card_details.cvv}")
        #         logger.info(f"  Status: {card_details.status}")
        #         logger.info(
        #             f"  Balance: {card_details.available_balance} {card_details.currency}")
        #     # response = client.infinity_card.infinity_card_transfer_in({"cardId": card["id"], "cost": 100})
        #     # response = client.infinity_card.infinity_card_transfer_out({"cardId": card["id"], "cost": 50})
        #     # response = client.infinity_card.freeze_infinity_card(card["id"])
        #     # response = client.infinity_card.unfreeze_infinity_card(card["id"])
        #         response = client.infinity_card.list_all_infinity_card_transactions({
        #                                                                             "cardId": card.id})
        #         logger.info(f"  Status: {response}")
        #     # response = client.wallets.list_all_addresses()
        #     # response = client.wallets.create_blockchain_address({"chain": "TRX", "currency": "USDT"})
        #     # response = client.funding.list_all_balances()
        #     # response = client.convert.get_estimate_quote({"baseCurrency": "USDT", "quoteCurrency": "USD", "side": "sell", "rfqCurrency": "USD", "rfqAmount": "100"})
        #     # response = client.convert.create_trade({"baseCurrency": "USDT", "quoteCurrency": "USD", "side": "sell", "rfqCurrency": "USD", "rfqAmount": "100", "quoteId": response["data"]["id"]})
        #     # response = client.funding.create_transfer({"source": {"type": "master_account"}, "destination": {"type": "crypto_assets", "currency": "USD"}, "amount": "100"})

        #     # response = client.funding.create_transfer({"source": {"type":
        #     # "crypto_assets", "currency": "USD"}, "destination": {"type":
        #     # "quantum_account"}, "amount": "100"})
        #     logger.info("Successfully fetched data")

    # except InterlaceError as api_err:
    #     logger.error(f"API call failed: {api_err}")
    #     if isinstance(api_err, AuthenticationError):
    #         logger.error(
    #             "Authentication error during API call. "
    #             "Token might be invalid or expired."
    #         )

    # except InterlaceError as e:
    #     logger.error(f"\nAn error occurred during client init or API call: {e}")
    except Exception as e:
        logger.error(f"\nAn unexpected error occurred: {e}")


if __name__ == "__main__":
    main()
