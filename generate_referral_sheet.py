import json
import random
import string

import gspread
from oauth2client.service_account import ServiceAccountCredentials

import config

# Get spreadsheet ID and credentials from config.py
SPREADSHEET_ID = config.SPREADSHEET_ID
CREDENTIALS_PATH = config.ABS_CREDENTIALS_PATH

# Google Sheets API setup
scope = ['https://spreadsheets.google.com/feeds',
         'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_PATH, scope)
client = gspread.authorize(creds)

# Create or open the spreadsheet
spreadsheet = client.open_by_key(SPREADSHEET_ID)

# Create new sheet/tab for referral codes
sheet_name = 'ReferralCodes'
try:
    worksheet = spreadsheet.worksheet(sheet_name)
    print(f"Sheet '{sheet_name}' already exists.")
except gspread.exceptions.WorksheetNotFound:
    worksheet = spreadsheet.add_worksheet(title=sheet_name, rows="10001", cols="5")
    print(f"Created new sheet '{sheet_name}'.")

# Define columns
columns = ['referal code', 'deposit fee', 'foregin fee', 'name', 'valid']
worksheet.update('A1:E1', [columns])

# Generate 10,000 unique referral codes
codes = set()
while len(codes) < 10000:
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    codes.add(code)
codes = list(codes)

# Prepare rows
rows = [[code, '2.5', '2.5', '', '0'] for code in codes]

# Batch update (Google Sheets API limit is 500 rows per request)
for i in range(0, 10000, 500):
    batch = rows[i:i + 500]
    worksheet.update(f'A{i+2}:E{i+1+len(batch)}', batch)

print(f"Populated '{sheet_name}' with 10,000 referral codes.")
