from dataclasses import dataclass
from interlace.resources.models import Balance
from datetime import datetime, timezone
from typing import List
import logging
from interlace.client import InterlaceClient
from services.mysql_service import mysql_client
from pymongo import MongoClient
from services.sheets_service import initialize_sheets_service
from interlace.resources.models import CardTransaction
import asyncio
from config import NOVA_CONSUMPTION_FEE_T
import numpy as np
import os
import pandas as pd
import config
import random
from telegram_bot.messaging import telegram_messaging

# Create logs directory if it doesn't exist
os.makedirs('logs', exist_ok=True)

# Generate log filename with timestamp and transaction_process identifier
log_filename = f"logs/transaction_process_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def update_sheet(updated_df, sheet_name):
    sheets_service = initialize_sheets_service()
    if sheets_service:
        try:
            # Convert DataFrame to list of lists for Google Sheets
            # Convert any timestamp columns to strings
            for col in updated_df.columns:
                if pd.api.types.is_datetime64_any_dtype(updated_df[col]):
                    updated_df[col] = updated_df[col].dt.strftime('%Y-%m-%d %H:%M:%S')

            values = [updated_df.columns.tolist()] + updated_df.values.tolist()

            # Update the deposits sheet
            range_name = f"{sheet_name}!A1:Z10000"
            # First clear the sheet
            sheets_service.spreadsheets().values().clear(
                spreadsheetId=config.SPREADSHEET_ID,
                range=range_name,
                body={}
            ).execute()

            # Then update with new values
            body = {"values": values}
            result = (
                sheets_service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=config.SPREADSHEET_ID,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body
                )
                .execute()
            )
            logger.info(f"Successfully updated {sheet_name} sheet")
        except Exception as sheet_err:
            logger.error(f"Error updating Google Sheet: {sheet_err}")


mongodb_config = config.MONGODB_CONFIG
mongo_uri = mongodb_config.get("uri", "mongodb://localhost:27017")
mongo_db_name = mongodb_config.get("db_name", "nova")

# Global MongoDB client instance using configuration
mongo_client_global = MongoClient(mongo_uri)

# Removed persistent event loop for MySQL operations; now relying on
# asyncio.run to manage the event loop


async def get_user_fees(user_id: str) -> dict:
    """Get user fees from MySQL."""
    deposit_fee, foreign_fee = await mysql_client.get_fees_for_user_mysql(user_id=user_id)
    return {"deposit_fee": deposit_fee, "foreign_fee": foreign_fee}


async def get_user_info(card_id: str) -> dict:
    """Get user information from MySQL."""
    user_result = await mysql_client.get_user_from_db(card_number=card_id)
    if not user_result.get("success"):
        logger.error(
            f"No user found for card_id {card_id}"
        )
        return None

    user = user_result.get("user", {})
    user_id = user.get("userId")
    card_number = user.get("cardNumber")

    if not user_id or not card_number:
        logger.error(f"Missing user_id or card_number for card_id {card_id}")
        return None

    return {"user_id": user_id, "card_number": card_number}


def extract_transaction_details(data: dict) -> dict:
    """Extract and format transaction details from the callback data."""
    data = data.to_dict()
    transaction_id = data.get("id")
    card_id = data.get("card_id")
    amount = float(data.get("amount", 0))
    fee = float(data.get("fee", 0))
    currency = data.get("currency")
    transaction_type = data.get("type")
    status = data.get("status")
    client_transaction_id = data.get("client_transaction_id", "")
    transaction_amount = float(data.get("transaction_amount", 0))
    transaction_currency = data.get("transaction_currency")
    remark = data.get("remark", "")
    detail = data.get("detail", "")
    transaction_time = data.get("transaction_time", "")

    # if transaction_type == "Consumption":
    #     print(1)

    tid = (
        client_transaction_id.split("_")[1]
        if "tid_" in client_transaction_id
        else client_transaction_id
    )
    is_fee_callback = "Fee_Consumption" in client_transaction_id

    return {
        "transaction_id": transaction_id,
        "cardId": card_id,
        "amount": amount,
        "fee": fee,
        "currency": currency,
        "transaction_type": transaction_type,
        "status": status,
        "client_transaction_id": client_transaction_id,
        "transaction_amount": transaction_amount,
        "transaction_currency": transaction_currency,
        "transaction_time": transaction_time,
        "remark": remark,
        "detail": detail,
        "tid": tid,
        "is_fee_callback": is_fee_callback,
    }


def get_mongo_collection():
    """
    Connect to MongoDB and return the collection named "combined_transactions".
    Create the collection if it does not exist using the global MongoDB client.
    """
    db = mongo_client_global[mongo_db_name]
    coll_name = "combined_transactions"
    if coll_name not in db.list_collection_names():
        logger.info(f"Creating collection {coll_name}")
        db.create_collection(coll_name)
    return db[coll_name]


def check_and_handle_quantum_balance():
    """
    Dummy implementation for checking quantum balance.
    In the real implementation, this would contact your Interlace/Nova systems;
    here we just log the action.
    """
    logger.info("Checking quantum balance (dummy implementation)")


async def calculate_transaction_fees(transaction_details: dict) -> dict:
    """Calculate fees for a transaction."""
    nova_fee_usd = 0
    nova_fee_foreign = 0
    conversion_rate = 0

    is_foreign = (
        transaction_details["transaction_amount"] != 0 and
        transaction_details["transaction_currency"] and
        transaction_details["transaction_currency"] != transaction_details["currency"]
    )

    if is_foreign:
        try:
            interlace_client = InterlaceClient()
            card_info = interlace_client.infinity_card.get_infinity_card_details(
                transaction_details["cardId"]
            )
            user_info = await get_user_info(card_info.card_no)
            if not user_info:
                return {
                    "nova_fee_usd": 0,
                    "nova_fee_foreign": 0,
                    "conversion_rate": 0
                }

            fees = await get_user_fees(user_info["user_id"])
            fee_rate = fees["foreign_fee"] / 100.0
            nova_fee_usd = (
                transaction_details["amount"] - transaction_details["fee"]) * fee_rate
            if transaction_details["amount"] != 0:
                conversion_rate = transaction_details["transaction_amount"] / \
                    transaction_details["amount"]
            else:
                conversion_rate = 0
            try:
                nova_fee_usd = round(float(nova_fee_usd), 2)
            except Exception as e:
                logger.error(
                    f"Error rounding nova fee: {e}: "
                    f"{transaction_details}"
                )
                nova_fee_usd = 0

            if nova_fee_usd > 0:
                nova_fee_foreign = nova_fee_usd * conversion_rate

        except Exception as e:
            logger.error(f"Error calculating nova fee: {e}")

    return {"nova_fee_usd": nova_fee_usd, "nova_fee_foreign": nova_fee_foreign,
            "conversion_rate": conversion_rate}


def prepare_transaction_doc(tx_details: dict, fee_details: dict,
                            existing_doc: dict = None) -> dict:
    """
    Prepare/merge a transaction document using current details and fee data.
    """
    if tx_details["transaction_type"] == "Consumption":
        print(1)
    now = datetime.now(timezone.utc)
    combined_doc = existing_doc.copy() if existing_doc else {}
    combined_doc.update({
        "tid": tx_details["tid"],
        "transaction_id": tx_details["transaction_id"],
        "cardId": tx_details["cardId"],
        "amount": tx_details["amount"],
        "fee": tx_details["fee"],
        "currency": tx_details["currency"],
        "transaction_type": tx_details["transaction_type"],
        "status": tx_details["status"],
        "client_transaction_id": tx_details["client_transaction_id"],
        "transaction_amount": tx_details["transaction_amount"],
        "transaction_currency": tx_details["transaction_currency"],
        "transaction_time": tx_details["transaction_time"],
        "detail": tx_details["detail"],
        "remark": tx_details["remark"],
        "nova_fee_usd": fee_details["nova_fee_usd"],
        "nova_fee_foreign": fee_details["nova_fee_foreign"],
        "conversion_rate": fee_details["conversion_rate"],
        "consumption_fee": {
            "usd": 0.5 if tx_details["amount"] < NOVA_CONSUMPTION_FEE_T else 0,
            "foreign": 0
        },
        "timestamp": now,
        "updated_at": now,
    })
    return combined_doc


def upsert_combined_doc(collection, tx_details: dict, fee_details: dict):
    """
    Update an existing combined document or insert a new one in combined_transactions,
    based on the transaction's tid.
    """
    query = {
        "tid": tx_details["tid"],
        "transaction_type": tx_details["transaction_type"]}
    existing_doc = collection.find_one(query)
    combined_doc = prepare_transaction_doc(tx_details, fee_details, existing_doc)
    if existing_doc:
        collection.update_one({"_id": existing_doc["_id"]}, {"$set": combined_doc})
        logger.info(
            f"Updated existing combined doc for tid "
            f"{tx_details['tid']}"
        )
    else:
        collection.insert_one(combined_doc)
        logger.info(
            f"Inserted new combined doc for tid "
            f"{tx_details['tid']}"
        )


async def handle_transfer_in(tx_details: dict, collection):
    """
    Handle TransferIn transactions.
    If the client_transaction_id indicates a Nova fee reversal, skip processing.
    Otherwise, update the combined document and check quantum balance.
    """
    if "NovafeeReversal" in tx_details["client_transaction_id"]:
        logger.info(
            f"Skipping Nova fee reversal for transaction {tx_details['transaction_id']}"
        )
        return
    logger.info(
        f"Handling TransferIn for transaction {tx_details['transaction_id']}"
    )
    fee_details = await calculate_transaction_fees(tx_details)
    upsert_combined_doc(collection, tx_details, fee_details)
    # Instead of sending Telegram messages, just check quantum balance.
    check_and_handle_quantum_balance()


async def handle_main_transaction(tx_details: dict, collection):
    """
    Handle main transactions (amount > 0, not TransferIn).
    """
    logger.info(f"Handling main transaction for tid {tx_details['tid']}")
    fee_details = await calculate_transaction_fees(tx_details)

    if tx_details["transaction_type"] in ["Reversal", "Credit"]:
        tx_details["amount"] = -np.abs(tx_details["amount"])
        if "transaction_amount" in tx_details.keys():
            tx_details["transaction_amount"] = -np.abs(tx_details["transaction_amount"])
    tx_details["nova_fee_usd"] = fee_details["nova_fee_usd"]
    upsert_combined_doc(collection, tx_details, fee_details)


async def handle_fee_callback(tx_details: dict, collection):
    """
    Handle fee callbacks.
    """
    logger.info(f"Handling fee callback for tid {tx_details['tid']}")
    fee_details = await calculate_transaction_fees(tx_details)
    upsert_combined_doc(collection, tx_details, fee_details)


async def process_transactions(transactions: List[CardTransaction]):
    """
    Process a list of CardTransaction objects, update or create the combined transaction document
    in the MongoDB collection, and compute real balance per card based on transactions identified
    as belonging to createCard or nova fee categories. The real balance is computed as:
         (create_transfer_in - create_transfer_out) + \
          (nova_transfer_in - nova_transfer_out)
    """
    # Sort transactions by transaction_time to simulate arrival order
    transactions.sort(key=lambda tx: tx.transaction_time)
    transactions_flat = []
    collection = get_mongo_collection()

    # Group transactions by card for summary and processing
    for tx in transactions:
        tx_details = extract_transaction_details(tx)

        # Process each transaction to update or create the combined document
        tx_type = tx_details.get("transaction_type")
        # Instead of skipping transactions based on client_transaction_id, process all
        if tx_type == "TransferIn":
            await handle_transfer_in(tx_details, collection)
        elif tx_type == "TransferOut":
            logger.info(
                f"Processing TransferOut transaction: {tx_details}")
        elif tx_type in ["Reversal", "Credit"] or tx_details["amount"] > 0:
            await handle_main_transaction(tx_details, collection)
        elif tx_details.get("is_fee_callback"):
            await handle_fee_callback(tx_details, collection)
        else:
            logger.info(
                f"Unhandled transaction type for {tx_details.get('transaction_id')}")
        card_id = tx_details.get("cardId")
        client_tx_id = tx_details.get("client_transaction_id", "")
        amount = tx_details.get("amount", 0)
        transactions_flat.append({
            "cardId": card_id,
            "time": tx_details.get("transaction_time"),
            "tx_type": tx_type,
            "tx_status": tx_details.get("status"),
            "client_transaction_id": client_tx_id,
            "amount": float(amount) if tx_type in ["Reversal", "Credit", "TransferIn"] else -float(amount),
            "nova_fee_usd": tx_details.get("nova_fee_usd"),
            "is_consumption_fee": int(tx_details.get("is_fee_callback")),
            "is_nova_fee": int("NovaFee" in client_tx_id),
            "is_create_card": int("createCard" in client_tx_id),
            "is_admin": int(("createCard" not in client_tx_id) and ("NovaFee" not in client_tx_id) and (not tx_details.get("is_fee_callback")))
        })

    return transactions_flat

 # Define a helper function to fetch real balance using the funding API


def fetch_real_balance(client, card_id):
    real_balance = 0
    user_cards = client.infinity_card.list_all_infinity_cards(params={
        "id": card_id})
    if user_cards and len(user_cards) > 0:
        user_card = user_cards[0]
        if user_card and user_card.balance_id:
            balance_data = client.funding.list_all_balances(
                params={"id": user_card.balance_id})
            if (balance_data and isinstance(balance_data, list)
                    and len(balance_data) > 0):
                balance_obj = Balance.from_dict(balance_data[0])
                # Assuming the Balance model has an attribute 'balance'
                real_balance = balance_obj.available

    return real_balance


if __name__ == "__main__":

    async def main():
        try:
            logger.info("Initializing InterlaceClient...")
            client = InterlaceClient()
            # available_bins = client.infinity_card.list_available_bins()
            transactions = client.infinity_card.list_all_infinity_card_transactions()
            print(len(transactions))
            transactions_flat = await process_transactions(transactions)
            print(transactions_flat)
            # Save transactions_flat as CSV using pandas in 'transactions_check' folder
            output_folder = "transactions_check"
            os.makedirs(output_folder, exist_ok=True)
            transactions_csv_path = os.path.join(
                output_folder, "transactions_table.csv")
            df = pd.DataFrame(transactions_flat)
            df.to_csv(transactions_csv_path, index=False)
            update_sheet(df, "transactions")
            logger.info(f"Saved transactions table CSV to {transactions_csv_path}")

            # Create summary table grouping by cardId and summing numeric columns
            summary_df = df.groupby("cardId").sum(numeric_only=True).reset_index()
            summary_df["current_balance"] = summary_df["amount"]

            # Fetch real balance for each card id in the summary
            real_balances = []
            for card_id in summary_df["cardId"]:
                real_balance = fetch_real_balance(client, card_id)
                real_balances.append(real_balance)
            summary_df["real_balance"] = real_balances
            summary_df["difference"] = summary_df["current_balance"] - \
                summary_df["real_balance"]

            summary_csv_path = os.path.join(output_folder, "summary_table.csv")
            summary_df.to_csv(summary_csv_path, index=False)
            logger.info(f"Saved summary table CSV to {summary_csv_path}")
            update_sheet(summary_df, "transactions_summary")

            check = df[((df["tx_type"].isin(["Consumption", "Reversal", "Credit"])) & (df["nova_fee_usd"] > 0)) | (
                df["client_transaction_id"].apply(lambda x: "novafee" in x.lower()))]
            check["tid"] = check["client_transaction_id"].apply(
                lambda x: x.split("_")[1] if len(x.split("_")) > 1 else x)

            tids = check.groupby(["tid"])["cardId"].count().reset_index()
            tids = tids[tids["cardId"] == 1]
            check = check[(check["tid"].isin(tids["tid"])) & (
                check["tx_type"].isin(["Consumption", "Reversal", "Credit"]))]
            check = check[["cardId", "nova_fee_usd", "tx_type", "tid"]]
            check.to_csv(
                os.path.join(
                    output_folder,
                    "return_nova_fee.csv"),
                index=False)
            update_sheet(check, "fix_nova_fee")
            # for cardId, nova_fee_usd, tx_type, tid in check.values:
            #     try:
            #         if tx_type == "Consumption":
            #             client.infinity_card.infinity_card_transfer_out(
            #                 {
            #                     "cardId": cardId,
            #                     "cost": round(nova_fee_usd, 2),
            #                     "clientTransactionId": f"fix_NovaFee_{tid}_{int(datetime.now().timestamp())}_{random.randint(100000, 999999)}",
            #                 }
            #             )
            #         else:
            #             old_transferouts = client.infinity_card.list_all_infinity_card_transactions(
            #                 params={
            #                     "cardId": cardId,
            #                     "type": "TransferIn"}
            #             )
            #             old_exists = False
            #             took_nova_fee = False
            #             if old_transferouts:
            #                 for transferout in old_transferouts:
            #                     if f"NovafeeReversal_{tid}" in transferout.client_transaction_id:
            #                         logger.info(
            #                             f"Skipping transfer out for pending transaction: {transferout}")
            #                         old_exists = True
            #                     elif f"NovaFee_{tid}" in transferout.client_transaction_id:
            #                         took_nova_fee = True

            #             if not old_exists and took_nova_fee:
            #                 client.infinity_card.infinity_card_transfer_in(
            #                     {
            #                         "cardId": cardId,
            #                         "cost": round(nova_fee_usd, 2),
            #                         "clientTransactionId": f"fix_NovaFeeReversal_{tid}_{int(datetime.now().timestamp())}_{random.randint(100000, 999999)}",
            #                     }
            #                 )
            #     except Exception as e:
            #         logger.error(
            # f"Error processing Nova fee: {e} {cardId} {tid} {tx_type}
            # {nova_fee_usd}")

            df["tid"] = df["client_transaction_id"].apply(
                lambda x: x.split("_")[1] if len(x.split("_")) > 1 else x)
            df["is_balance_account"] = df["client_transaction_id"].apply(
                lambda x: 1 if "BalanceAccount" in x else 0)
            # df["amount"] = df.apply(
            #     lambda x:
            #     -x["amount"] if "BalanceAccount_in" in x["client_transaction_id"] else x["amount"],
            #     axis=1)
            df["amount"] = df.apply(
                lambda x:
                np.abs(x["amount"]) if (x["is_balance_account"] == 1
                                        and x["tx_type"] == "TransferIn") else x["amount"],
                axis=1)
            df["amount"] = df.apply(
                lambda x:
                -np.abs(x["amount"]) if (x["is_balance_account"] ==
                                         1 and x["tx_type"] == "TransferOut") else x["amount"], axis=1)

            df["is_nova_fee_reversal"] = df["client_transaction_id"].apply(
                lambda x: 1 if "reversal" in x.lower() else 0)
            try:
                multiple_balance_account = df[df["is_balance_account"] == 1].groupby(
                    ["cardId"])[["is_balance_account", "amount"]].sum().reset_index()
            except Exception as e:
                logger.error(f"Error calculating multiple balance account: {e}")
                multiple_balance_account = pd.DataFrame()

            multiple_reversal = df[df["is_nova_fee_reversal"] == 1].groupby(
                ["cardId", "tid"])[["is_nova_fee_reversal", "amount"]].sum().reset_index()
            multiple_reversal = multiple_reversal[multiple_reversal["is_nova_fee_reversal"] > 1]
            multiple_nova_fee = df[df["is_nova_fee"] == 1].groupby(
                ["cardId", "tid"])[["is_nova_fee", "amount"]].sum().reset_index()
            multiple_nova_fee = multiple_nova_fee[multiple_nova_fee["is_nova_fee"] > 1]

            multiple_nova_fee["return_amount"] = - (multiple_nova_fee["amount"] /
                                                    multiple_nova_fee["is_nova_fee"]) * (multiple_nova_fee["is_nova_fee"] - 1)
            multiple_reversal["remove_amount"] = - (
                multiple_reversal["amount"] / multiple_reversal["is_nova_fee_reversal"]) * (
                multiple_reversal["is_nova_fee_reversal"] - 1)

            novafee_total = multiple_nova_fee.groupby(
                ["cardId"])["return_amount"].sum().reset_index()
            reversal_total = multiple_reversal.groupby(
                ["cardId"])["remove_amount"].sum().reset_index()

            total = novafee_total.merge(reversal_total, on="cardId", how="outer")
            if not multiple_balance_account.empty:
                multiple_balance_account.rename(
                    columns={
                        "amount": "balance_account_amount"},
                    inplace=True)
                total = total.merge(multiple_balance_account, on="cardId", how="outer")
            else:
                total["balance_account_amount"] = 0

            total.fillna(0, inplace=True)

            total["balance"] = total["return_amount"] + \
                total["remove_amount"] - total["balance_account_amount"]
            total = total[(total["balance"] > 1) | (total["balance"] < -1)]
            total.to_csv(os.path.join(output_folder, "total_table.csv"), index=False)
            update_sheet(total, "total_fix")
            total_list = total[["cardId", "balance"]].values.tolist()

            for cardId, balance in total_list:
                card_info = client.infinity_card.get_infinity_card_details(cardId)
                if balance > 0:
                    try:
                        client.infinity_card.infinity_card_transfer_in(
                            {
                                "cardId": cardId,
                                "cost": round(np.abs(balance), 2),
                                "clientTransactionId": f"BalanceAccount_in_{int(datetime.now().timestamp())}_{random.randint(100000, 999999)}",
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error transferring in balance: {e}")
                    await telegram_messaging.send_admin_alert(
                        f"Transfer in {round(balance, 2)} to card id: {cardId} - card no: {card_info.card_no} fix")

                else:
                    try:
                        client.infinity_card.infinity_card_transfer_out(
                            {
                                "cardId": cardId,
                                "cost": round(np.abs(balance), 2),
                                "clientTransactionId": f"BalanceAccount_out_{int(datetime.now().timestamp())}_{random.randint(100000, 999999)}",
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error transferring out balance: {e}")
                    await telegram_messaging.send_admin_alert(
                        f"Transfer out {round(np.abs(balance), 2)} to card id: {cardId} - card no: {card_info.card_no} fix")

            success_message = (
                f"✅ Transaction Processing Complete\n\n"
                f"Processed {len(transactions_flat)} transactions\n"
                f"Generated reports in {output_folder}"
            )
            await telegram_messaging.send_admin_alert(success_message)

            # Allow pending cleanup callbacks to run
            await asyncio.sleep(0.1)

        except Exception as e:
            error_message = f"❌ Error in transaction processing: {str(e)}"
            logger.error(error_message)
            await telegram_messaging.send_admin_alert(error_message)
            raise

    asyncio.run(main())
