import asyncio

from services.sheets_service import SheetsService
from telegram_bot.handlers import add_lead_to_sheet_bot

sheets_service = SheetsService()


async def main():
    users = await add_lead_to_sheet_bot({
        'chatId': "check",
        'username': "check",
                    'firstName': "check",
                    'lastName': "check",
                    'email': "check",
                    'phone': "check",
                    'referralCode': "check",
                    'firstNameChat': "check",
                    'lastNameChat': "check",
                    'language': "check",
                    'CARD ID': "check",
    })
    print(users)

if __name__ == "__main__":

    asyncio.run(main())
