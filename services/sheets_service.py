import asyncio
import logging
import os
from typing import List, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Assuming config module is in the parent directory or PYTHONPATH
from config import (
    ABS_CREDENTIALS_PATH,
    FIELD_MAPPING,
    GOOGLE_SHEETS_CONFIG,
    REVERSE_FIELD_MAPPING,
    SCOPES,
    SPREADSHEET_ID,
    USERS_SHEET,
)
from services.mysql_service import mysql_client
from utils.logger import logger

logger = logging.getLogger(__name__)


def initialize_sheets_service():
    """Initializes and returns a Google Sheets API service instance."""
    if not SPREADSHEET_ID or not ABS_CREDENTIALS_PATH or not SCOPES:
        logger.error(
            "Google Sheets config (SPREADSHEET_ID, CREDENTIALS_PATH, SCOPES) "
            "missing. Cannot initialize service."
        )
        return None

    if not os.path.exists(ABS_CREDENTIALS_PATH):
        logger.error(f"Google credentials file not found at: {ABS_CREDENTIALS_PATH}")
        return None

    try:
        creds = service_account.Credentials.from_service_account_file(
            ABS_CREDENTIALS_PATH, scopes=SCOPES
        )
        service = build("sheets", "v4", credentials=creds)
        logger.info("Google Sheets API service instance created successfully.")
        return service
    except Exception as e:
        logger.error(f"Error initializing Google Sheets API: {e}", exc_info=True)
        return None


async def get_row_number_for_user_id(sheets_service_client, user_id):
    """
    Efficiently find the row number for a user_id by fetching only the USER_ID
    column. Returns the row number (1-based, including header) or None if not
    found.
    """
    try:
        # USER_ID is assumed to be in column A
        range_name = f"{USERS_SHEET}!A:A"
        result = (
            sheets_service_client.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
            .execute()
        )
        rows = result.get("values", [])
        for idx, row in enumerate(rows, start=1):
            if row and str(row[0]) == str(user_id):
                return idx
        return None
    except Exception as e:
        logger.error(f"Error finding row for user_id {user_id}: {e}")
        return None


def row_to_api_dict(row: dict) -> dict:
    """Convert a row dictionary to API field names."""
    return {REVERSE_FIELD_MAPPING.get(k, k): v for k, v in row.items()}


def api_dict_to_row(api_dict: dict) -> dict:
    """Convert an API dictionary to sheet field names."""
    return {FIELD_MAPPING.get(k, k): v for k, v in api_dict.items()}


async def get_user_from_sheet(
    sheets_service_client,
    user_id=None,
    nova_address=None,
    card_number=None,
    get_all=False,
):
    """Get user data from MySQL database, always returning API field names."""
    return await mysql_client.get_user_from_db(
        user_id=user_id,
        nova_address=nova_address,
        card_number=card_number,
        get_all=get_all,
    )


async def get_all_users_from_sheet(sheets_service_client):
    """Get all users from MySQL database."""
    return await mysql_client.get_all_users_from_db()


def get_fees_for_user(
    sheets_service_client, user_id=None, nova_address=None, card_number=None
):
    """Get deposit/foreign fees for a user by looking up their referral code."""
    return asyncio.run(
        mysql_client.get_fees_for_user_mysql(
            user_id=user_id
        )
    )


def check_referral_code_valid(sheets_service_client, referral_code):
    """Check if a referral code exists and is valid in the ReferralCodes sheet."""
    try:
        range_name = "ReferralCodes!A2:E10001"
        result = (
            sheets_service_client.spreadsheets()
            .values()
            .get(spreadsheetId=SPREADSHEET_ID, range=range_name)
            .execute()
        )
        rows = result.get("values", [])
        for row in rows:
            code = row[0].strip() if len(row) > 0 else ""
            valid = row[4].strip() if len(row) > 4 else "0"
            if code.upper() == referral_code.upper() and valid == "0":
                # Return also the fees for convenience
                deposit_fee = float(row[1]) if len(row) > 1 else 2.5
                foreign_fee = float(row[2]) if len(row) > 2 else 2.5
                return True, deposit_fee, foreign_fee
        return False, None, None
    except Exception as e:
        logger.error(f"Error checking referral code in sheet: {e}")
        return False, None, None


async def update_user_field_in_sheet(
    sheets_service_client, user_id, field_name, new_value
):
    """
    Update a specific field for a user in the Google Sheet by user_id.
    Only fetches the USER_ID column to find the row, then updates only the
    target cell.
    """
    if not sheets_service_client:
        logger.error(
            "Sheets service client not provided to update_user_field_in_sheet."
        )
        return False
    try:
        headers = [
            entry["sheet"] for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])
        ]
        if field_name not in FIELD_MAPPING:
            logger.error(f"Field {field_name} not found in FIELD_MAPPING.")
            return False
        sheet_col_name = FIELD_MAPPING[field_name]
        col_idx = headers.index(sheet_col_name)
        row_number = await get_row_number_for_user_id(sheets_service_client, user_id)
        if not row_number:
            logger.error(f"User {user_id} not found in sheet for update.")
            return False
        if hasattr(new_value, 'isoformat'):
            new_value = new_value.isoformat()
        update_range = f"{USERS_SHEET}!{chr(65+col_idx)}{row_number}"
        body = {"values": [[new_value]]}
        (
            sheets_service_client.spreadsheets()
            .values()
            .update(
                spreadsheetId=SPREADSHEET_ID,
                range=update_range,
                valueInputOption="RAW",
                body=body,
            )
            .execute()
        )
        logger.info(
            f"Updated {field_name} for user {user_id} to {new_value} at "
            f"{update_range}"
        )
        return True
    except Exception as e:
        logger.error(f"Error updating {field_name} for user {user_id} in sheet: {e}")
        return False


class SheetsService:
    def __init__(self):
        self.service = None
        self.spreadsheet_id = None

    def initialize(self, credentials_path: str, spreadsheet_id: str):
        try:
            credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/spreadsheets"],
            )
            self.service = build("sheets", "v4", credentials=credentials)
            self.spreadsheet_id = spreadsheet_id
            logger.info("Successfully initialized Google Sheets service")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            raise

    def append_row(self, sheet_name: str, values: List[str]):
        try:
            range_name = f"{sheet_name}!A:A"
            body = {"values": [values]}
            result = (
                self.service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=range_name,
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body=body,
                )
                .execute()
            )
            logger.info(f"Successfully appended row to {sheet_name}")
            return result
        except Exception as e:
            logger.error(f"Error appending row to {sheet_name}: {e}")
            return None

    def get_values(self, sheet_name: str, range_name: Optional[str] = None):
        try:
            if range_name is None:
                range_name = f"{sheet_name}!A:Z"
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=range_name)
                .execute()
            )
            return result.get("values", [])
        except Exception as e:
            logger.error(f"Error getting values from {sheet_name}: {e}")
            return []

    def update_values(self, sheet_name: str, range_name: str, values: List[List[str]]):
        try:
            body = {"values": values}
            result = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet_name}!{range_name}",
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )
            logger.info(f"Successfully updated values in {sheet_name}")
            return result
        except Exception as e:
            logger.error(f"Error updating values in {sheet_name}: {e}")
            return None

    def clear_values(self, sheet_name: str, range_name: str):
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .clear(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"{sheet_name}!{range_name}",
                    body={},
                )
                .execute()
            )
            logger.info(f"Successfully cleared values in {sheet_name}")
            return result
        except Exception as e:
            logger.error(f"Error clearing values in {sheet_name}: {e}")
            return None

    def _initialize_sheets_service(self):
        """Initializes and returns a Google Sheets API service instance."""
        return initialize_sheets_service()

    async def get_row_number_for_user_id(self, user_id):
        """
        Efficiently find the row number for a user_id by fetching only the USER_ID
        column. Returns the row number (1-based, including header) or None if not
        found.
        """
        return await get_row_number_for_user_id(self.service, user_id)

    def row_to_api_dict(self, row: dict) -> dict:
        """Convert a row dictionary to API field names."""
        return row_to_api_dict(row)

    def api_dict_to_row(self, api_dict: dict) -> dict:
        """Convert an API dictionary to sheet field names."""
        return api_dict_to_row(api_dict)

    async def get_user_from_sheet(
        self, user_id=None, nova_address=None, card_number=None, get_all=False
    ):
        """Get user data from MySQL database, always returning API field names."""
        return await get_user_from_sheet(
            self.service, user_id, nova_address, card_number, get_all
        )

    async def get_all_users_from_sheet(self):
        """Get all users from MySQL database."""
        return await get_all_users_from_sheet(self.service)

    def check_referral_code_valid(self, referral_code):
        """Check if a referral code exists and is valid in the ReferralCodes sheet."""
        return check_referral_code_valid(self.service, referral_code)

    async def update_user_field_in_sheet(self, user_id, field_name, new_value):
        """
        Update a specific field for a user in the Google Sheet by user_id.
        Only fetches the USER_ID column to find the row, then updates only the
        target cell.
        """
        return await update_user_field_in_sheet(
            self.service, user_id, field_name, new_value
        )

    async def append_row(self, sheet_name: str, row_data: dict) -> bool:
        """
        Append a new row to the specified sheet.

        Args:
            sheet_name: Name of the sheet to append to
            row_data: Dictionary of column names and values

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Get sheet metadata to find sheet ID
            spreadsheet = (
                self.service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
            )

            # Find the sheet ID for the given sheet name
            sheet_id = None
            target_sheet_name = sheet_name.lower()
            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"].lower() == target_sheet_name:
                    sheet_id = sheet["properties"]["sheetId"]
                    break

            if sheet_id is None:
                logger.error(
                    f"Sheet '{sheet_name}' not found. Available sheets: "
                    f"{[s['properties']['title'] for s in spreadsheet.get('sheets', [])]}"
                )
                return False

            # Get all rows to find first empty USER_ID
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=f"{sheet_name}!A:A")
                .execute()
            )
            rows = result.get("values", [])

            # Find first empty row (0-based index for batchUpdate)
            row_index = 0
            for idx, row in enumerate(rows):
                if not row or not row[0].strip():
                    row_index = idx
                    break
                row_index = idx + 1

            # Get sheet field names in order
            sheet_fields = [
                entry["sheet"] for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])
            ]

            # Convert API field names to sheet field names
            sheet_data = {}
            for api_field, sheet_field in FIELD_MAPPING.items():
                # Get value from row_data using API field name
                value = row_data.get(api_field, "")
                # Store in sheet_data using sheet field name
                sheet_data[sheet_field] = value

            # Convert to ordered list based on sheet columns
            ordered_values = []
            for field in sheet_fields:
                value = sheet_data.get(field, "")
                ordered_values.append(value)

            # Validate required fields
            missing_fields = []
            required_fields = ["USER_ID", "CARD NAME", "CARD SURNAME"]
            for field in required_fields:
                if not sheet_data.get(field):
                    missing_fields.append(field)

            if missing_fields:
                logger.error(f"Missing required fields: {', '.join(missing_fields)}")
                return False

            # Simple values update
            range_name = f"{sheet_name}!A{row_index + 1}"
            body = {"values": [ordered_values]}

            result = (
                self.service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=SPREADSHEET_ID,
                    range=range_name,
                    valueInputOption="RAW",
                    body=body,
                )
                .execute()
            )

            if result:
                logger.info(
                    f"Successfully updated row {row_index + 1} in sheet "
                    f"'{sheet_name}'"
                )
                return True
            else:
                logger.error(
                    f"Failed to update row in sheet '{sheet_name}'. "
                    f"Response: {result}"
                )
                return False

        except Exception as e:
            logger.error(f"Error adding row to {sheet_name}: {str(e)}", exc_info=True)
            return False
