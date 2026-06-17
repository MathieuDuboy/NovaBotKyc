import asyncio
import logging
import random
import re
import string
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable, Tuple, Type

import httpx
import telegram
from telegram import (InlineKeyboardButton, InlineKeyboardMarkup, Update,
                      WebAppInfo)
from telegram.ext import ContextTypes

import config
from interlace import InterlaceClient
from interlace.resources.models import Card, CardDetails
from nova_api import NovaClient
from services.mongo_service import MongoClientWrapper
from services.mysql_service import mysql_client
from services.redis_service import RedisClientWrapper
from services.sheets_service import SheetsService
from telegram_bot.utils.language import get_string, load_languages
from telegram_bot.utils.validation import (is_valid_email, is_valid_name,
                                           is_valid_phone, is_valid_referral)
from utils.logger import logger


# Textes du bot pour le lancement du KYC (mini app) — localisés en dur car ces
# clés n'existent pas dans les fichiers de langue (get_string retomberait sinon
# toujours sur le default FR). Langues alignées sur la mini app (en/fr/ru).
KYC_FORM_INTRO = {
    "en": ("To get your card, complete your identity verification in the secure "
           "form (info + ID document + selfie) 👇"),
    "fr": ("Pour obtenir ta carte, complète ta vérification d'identité dans le "
           "formulaire sécurisé (infos + pièce d'identité + selfie) 👇"),
    "ru": ("Чтобы получить карту, пройдите проверку личности в защищённой форме "
           "(данные + документ + селфи) 👇"),
}
GET_CARD_BUTTON = {
    "en": "💳 Get my card",
    "fr": "💳 Obtenir ma carte",
    "ru": "💳 Получить карту",
}


def kyc_form_texts(language):
    """(intro, bouton) pour lancer la mini app KYC, selon la langue (fallback EN)."""
    lang = (language or "en").split("-")[0].lower()
    return (KYC_FORM_INTRO.get(lang, KYC_FORM_INTRO["en"]),
            GET_CARD_BUTTON.get(lang, GET_CARD_BUTTON["en"]))


# Initialize MongoDB and Redis clients
mongo_client = MongoClientWrapper()
redis_client = RedisClientWrapper()

# Get MongoDB collections
users_collection = mongo_client.users
api_requests_collection = mongo_client.api_requests_collection

INTERLACE_MODE = config.INTERLACE_MODE
if INTERLACE_MODE == "dev":
    BIN = config.INTERLACE_DEV.get("bin")
else:
    BIN = config.INTERLACE_PROD.get("bin")

PHONE_NUMBER = config.PHONE_NUMBER
EMAIL = config.EMAIL
OPEN_CARD_INITIAL_AMOUNT = config.NOVA_DEPOSITS_CONFIG.get("open_card_initial_amount")


def with_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (
        httpx.ConnectError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.NetworkError,
        telegram.error.NetworkError,
        telegram.error.TimedOut,
        telegram.error.RetryAfter,
    ),
) -> Callable:
    """
    Retry decorator for async functions.

    Args:
        max_retries: Maximum number of retries
        delay: Initial delay between retries in seconds
        backoff: Multiplier for delay after each retry
        exceptions: Tuple of exceptions to catch and retry
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt == max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for "
                            f"{func.__name__}. Last error: {str(e)}",
                            exc_info=True,
                        )
                        raise

                    # Calculate next delay with jitter
                    jitter = random.uniform(0, 0.1 * current_delay)
                    next_delay = current_delay + jitter

                    logger.warning(
                        f"Attempt {attempt + 1}/{max_retries} failed for "
                        f"{func.__name__}. Retrying in {next_delay:.2f} seconds..."
                    )
                    await asyncio.sleep(next_delay)
                    current_delay *= backoff

            raise last_exception

        return wrapper

    return decorator


@with_retry(max_retries=5, delay=2.0, backoff=1.5)
async def send_telegram_message(bot, chat_id: int, text: str) -> None:
    """Send a message to Telegram with retry logic."""
    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception as e:
        logger.error(f"Failed to send message to {chat_id}: {str(e)}", exc_info=True)
        raise


@with_retry(max_retries=5, delay=2.0, backoff=1.5)
async def update_user_state_with_retry(chat_id: int, update_data: dict) -> None:
    """Update user state with retry logic."""
    try:
        await update_user_state(chat_id, update_data)
    except Exception as e:
        logger.error(f"Failed to update state for {chat_id}: {str(e)}", exc_info=True)
        raise


# --- State Management Helpers ---


async def get_user_state(chat_id):
    if users_collection is not None:
        try:
            user = await users_collection.find_one({"chat_id": chat_id})
            return user or {}
        except Exception as e:
            logger.error(f"Error getting user state: {e}")
            return {}
    return {}


async def update_user_state(chat_id, update_data):
    if users_collection is not None:
        try:
            await users_collection.update_one(
                {"chat_id": chat_id}, {"$set": update_data}, upsert=True
            )
        except Exception as e:
            logger.error(f"Error updating user state: {e}")


async def mark_request_completed(chat_id):
    if users_collection is not None:
        try:
            await users_collection.update_one(
                {"chat_id": chat_id},
                {"$set": {"completed": True, "completed_at": datetime.now()}},
            )
        except Exception as e:
            logger.error(f"Error marking request completed: {e}")


async def is_request_completed(chat_id):
    if users_collection is None:
        return False
    try:
        user = await users_collection.find_one({"chat_id": chat_id})
        return bool(user and user.get("completed", False))
    except Exception as e:
        logger.error(f"Error checking request completion: {e}")
        return False


# --- Lead Submission Helper ---
async def add_lead_to_sheet_bot(lead_data):
    """Add a new lead to Google Sheets with proper error handling."""
    try:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        required_fields = ["chatId", "firstName", "lastName", "email", "phone"]

        # Validate required fields
        missing_fields = [
            field for field in required_fields if not lead_data.get(field)
        ]
        if missing_fields:
            logger.error(
                f"BOT: Incomplete lead data. Missing fields: "
                f"{', '.join(missing_fields)}"
            )
            return {
                "success": False,
                "message": f"Missing required fields: {', '.join(missing_fields)}",
            }

        # Log API request if collection exists
        if api_requests_collection is not None:
            try:
                await api_requests_collection.insert_one(
                    {
                        "type": "lead_submission",
                        "chat_id": lead_data.get("chatId"),
                        "timestamp": datetime.now(),
                        "data": lead_data,
                    }
                )
            except Exception as e:
                logger.error(f"Error logging API request: {e}")

        logger.info(
            f"BOT: Adding lead to Google Sheets for user " f"{lead_data.get('chatId')}"
        )

        # Initialize sheets service using the proper class
        try:
            sheets_service = SheetsService()
            sheets_service.initialize(
                config.ABS_CREDENTIALS_PATH,
                config.SPREADSHEET_ID)
        except Exception as e:
            logger.error(f"BOT: Failed to initialize Google Sheets service: {e}")
            return {"success": False, "message": "Sheets service unavailable"}

        # Prepare row data using field mappings from config
        row_data = {}

        # Map internal fields directly to API fields
        for internal_field, api_field in config.INTERNAL_TO_API_MAPPING.items():
            row_data[api_field] = lead_data.get(internal_field, "")

        # Add date field
        row_data["dateReception"] = current_date

        try:
            # Use the proper service method to append the row
            success = await sheets_service.append_row(config.USERS_SHEET, row_data)

            if success:
                logger.info(
                    f"BOT: Data saved to Google Sheets for user "
                    f"{lead_data.get('chatId')}"
                )
                return {"success": True, "message": "Lead added successfully."}
            else:
                logger.error("BOT: Failed to save lead to Google Sheets")
                return {"success": False, "message": "Failed to save lead data."}

        except Exception as e:
            logger.error(f"BOT: Error saving to Google Sheets: {e}")
            return {"success": False, "message": str(e)}

    except Exception as e:
        logger.error(f"BOT: Error adding lead: {e}")
        return {"success": False, "message": str(e)}


# --- Conversation Handlers ---


@with_retry(max_retries=5, delay=2.0, backoff=1.5)
async def send_welcome_message(
    update: Update, reply_markup: InlineKeyboardMarkup
) -> None:
    """Send welcome message with retry logic."""
    try:
        await update.message.reply_text(
            "Please select your language / " "Пожалуйста, выберите ваш язык:",
            reply_markup=reply_markup,
        )
    except Exception as e:
        logger.error(f"Failed to send welcome message: {str(e)}", exc_info=True)
        raise


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /start command with improved error handling."""
    try:
        chat_id = update.effective_chat.id
        logger.info(f"/start command received from chat_id: {chat_id}")

        # Update last activity timestamp
        await update_user_state_with_retry(
            chat_id, {"last_activity": datetime.now().isoformat()}
        )

        # Check if request is already completed
        try:
            if await is_request_completed(chat_id):
                await send_telegram_message(
                    context.bot, chat_id, "⏳ Your card is ready to use!"
                )
                return
        except Exception as e:
            logger.error(
                f"Error checking request completion for {chat_id}: {e}", exc_info=True
            )
            # Continue with normal flow if check fails

        # Create language selection keyboard
        keyboard = [
            [InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
            [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            # Send welcome message with language selection using retry logic
            await send_welcome_message(update, reply_markup)
            await update_user_state_with_retry(chat_id, {"step": "language"})
        except Exception as e:
            logger.error(
                f"Error sending welcome message to {chat_id}: {e}", exc_info=True
            )
            # Try to send a simpler message if the first attempt fails
            try:
                await send_telegram_message(
                    context.bot, chat_id, "Welcome! Please try again in a moment."
                )
            except Exception as retry_e:
                logger.error(
                    f"Failed to send fallback message to {chat_id}: {retry_e}",
                    exc_info=True,
                )

    except Exception as e:
        logger.error(f"Critical error in start handler: {e}", exc_info=True)
        # Try to notify user of the error
        try:
            if update and update.effective_chat:
                await send_telegram_message(
                    context.bot,
                    update.effective_chat.id,
                    "Sorry, we're experiencing technical difficulties. "
                    "Please try again in a few minutes.",
                )
        except Exception as notify_e:
            logger.error(
                f"Failed to send error notification: {notify_e}", exc_info=True
            )


async def language_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle language selection callback."""
    try:
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id
        language = query.data.split("_")[1]

        logger.info(f"Language selection: {language} for chat_id: {chat_id}")

        # Update user state
        await update_user_state_with_retry(
            chat_id, {"language": language, "step": "referral"}
        )

        # Send welcome message
        welcome_message = get_string("welcome", language, default="Welcome!")
        await send_telegram_message(context.bot, chat_id, welcome_message)

        # Send referral code request (non bloquant : "NONE" si pas de code)
        referral_message = get_string(
            "askReferralCode", language, default="Referral code:")
        hint = {"fr": "\n\nSi tu n'as pas de code de parrainage, écris « NONE ».",
                "ru": "\n\nЕсли у вас нет реферального кода, напишите «NONE»."}.get(
            (language or "en")[:2].lower(),
            "\n\nIf you don't have a referral code, write «NONE».")
        await send_telegram_message(context.bot, chat_id, referral_message + hint)

        logger.info(f"Successfully processed language selection for chat_id: {chat_id}")

    except Exception as e:
        logger.error(f"Error in language selection: {e}", exc_info=True)
        try:
            if update and update.effective_chat:
                await send_telegram_message(
                    context.bot,
                    update.effective_chat.id,
                    "Sorry, there was an error processing your language selection. Please try /start again."
                )
        except Exception as notify_e:
            logger.error(
                f"Failed to send error notification: {notify_e}",
                exc_info=True
            )


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /send command for sending messages to a specific user."""
    try:
        chat_id = update.effective_chat.id
        if str(chat_id) != str(config.ADMIN_CHAT_ID):
            await send_telegram_message(
                context.bot,
                chat_id,
                "This command is only available to administrators."
            )
            return

        await update_user_state_with_retry(chat_id, {"step": "send_user_id"})
        await send_telegram_message(
            context.bot,
            chat_id,
            "Please enter the user ID to send the message to:"
        )
    except Exception as e:
        logger.error(f"Error in send command: {e}", exc_info=True)
        await send_telegram_message(
            context.bot,
            update.effective_chat.id,
            "An error occurred. Please try again."
        )


async def send_all_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message to all users."""
    chat_id = update.effective_chat.id
    try:
        # Clear user state
        await update_user_state_with_retry(chat_id, {"step": "send_all_message"})
        await send_telegram_message(
            context.bot,
            chat_id,
            "Please enter the message to send to all users:"
        )
    except Exception as e:
        logger.error(f"Error in send_all command: {e}", exc_info=True)
        await send_telegram_message(
            context.bot,
            update.effective_chat.id,
            "An error occurred. Please try again."
        )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current operation and clear user state."""
    chat_id = update.effective_chat.id
    try:
        # Clear user state
        await update_user_state_with_retry(chat_id, {"step": "completed"})
        await send_telegram_message(
            context.bot,
            chat_id,
            "Operation cancelled. You can start a new command."
        )
    except Exception as e:
        logger.error(f"Error in cancel command: {e}", exc_info=True)
        await send_telegram_message(
            context.bot,
            chat_id,
            "An error occurred while cancelling the operation."
        )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chat_id = update.effective_chat.id
        text = update.message.text.strip()
        user_data = await get_user_state(chat_id)
        language = user_data.get("language", "en")
        current_step = user_data.get("step", "language")

        logger.info(
            f"Processing message for chat_id: {chat_id}, step: {current_step}, language: {language}")

        # Check if the user has been inactive for too long (30 minutes)
        last_activity = user_data.get("last_activity")
        if last_activity:
            last_activity = datetime.fromisoformat(last_activity)
            if (datetime.now() - last_activity).total_seconds() > 1800:  # 30 minutes
                logger.info(
                    f"User {chat_id} was inactive for too long, resetting to start")
                await update_user_state_with_retry(chat_id, {"step": "language"})
                # Use default English message if language is not set
                if not language or language not in ["en", "ru"]:
                    language = "en"
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "sessionExpired",
                        language,
                        default="Your session has expired. Please use /start to begin again.")
                )
                return

        # Update last activity timestamp
        await update_user_state_with_retry(
            chat_id, {"last_activity": datetime.now().isoformat()}
        )

        # Add handling for send and send_all commands
        if current_step == "send_user_id":
            try:
                target_user_id = int(text)
                await update_user_state_with_retry(
                    chat_id,
                    {"step": "send_message", "target_user_id": target_user_id}
                )
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    "Please enter the message to send:"
                )
            except ValueError:
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    "Invalid user ID. Please enter a valid numeric user ID:"
                )
            return

        elif current_step == "send_message":
            target_user_id = user_data.get("target_user_id")
            try:
                await send_telegram_message(context.bot, target_user_id, text)
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    f"Message sent successfully to user {target_user_id}"
                )
                await update_user_state_with_retry(chat_id, {"step": "completed"})
            except Exception as e:
                logger.error(f"Error sending message to user {target_user_id}: {e}")
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    f"Failed to send message to user {target_user_id}. Error: {str(e)}"
                )
                await update_user_state_with_retry(chat_id, {"step": "completed"})
            return

        elif current_step == "send_all_message":
            try:
                # Get all users from MySQL
                users_result = await mysql_client.get_all_users_from_db()
                if not users_result or not users_result.get("success"):
                    raise Exception("Failed to fetch users from database")

                users = users_result.get("users", [])
                success_count = 0
                fail_count = 0
                fail_reasons = []

                for user in users:
                    user_id = user.get("userId")
                    if not user_id:
                        continue

                    try:
                        await send_telegram_message(context.bot, user_id, text)
                        success_count += 1
                    except Exception as e:
                        fail_count += 1
                        fail_reasons.append(f"User {user_id}: {str(e)}")
                        logger.error(f"Failed to send message to user {user_id}: {e}")

                # Send summary to admin
                summary = (
                    f"Message broadcast complete:\n"
                    f"✅ Successfully sent: {success_count}\n"
                    f"❌ Failed: {fail_count}\n"
                )
                if fail_reasons:
                    summary += "\nFailed users:\n" + "\n".join(fail_reasons[:5])
                    if len(fail_reasons) > 5:
                        summary += f"\n... and {len(fail_reasons) - 5} more failures"

                await send_telegram_message(context.bot, chat_id, summary)
                await update_user_state_with_retry(chat_id, {"step": "completed"})
            except Exception as e:
                logger.error(f"Error in send_all_message: {e}", exc_info=True)
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    f"Failed to broadcast message. Error: {str(e)}"
                )
                await update_user_state_with_retry(chat_id, {"step": "completed"})
            return

        if current_step == "referral":
            # Étape NON bloquante : "NONE" (ou vide/équivalent) -> on passe sans code
            # (frais par défaut). Sinon on valide le code ; un code erroné est rejeté
            # mais l'user peut toujours écrire NONE pour continuer.
            _txt = str(text or "").strip()
            _no_code = _txt.lower() in (
                "none", "non", "no", "aucun", "skip", "-", "n/a", "na", "нет", "")
            proceed, ref_to_save = False, ""
            if _no_code:
                proceed, ref_to_save = True, ""
            elif is_valid_referral(_txt):
                valid, _df, _ff = await mysql_client.check_referral_code_valid_mysql(_txt)
                if valid:
                    proceed, ref_to_save = True, _txt
            if proceed:
                # Parcours RACCOURCI : la collecte (infos + pièce + selfie) se fait
                # dans la mini app. On garde juste le code (ou vide), puis on ouvre
                # le formulaire web_app.
                await update_user_state_with_retry(
                    chat_id, {"referralCode": ref_to_save, "step": "kyc_form"})
                _key = "thankYouReferralCode" if ref_to_save else "noReferralCode"
                _def = "Referral code saved!" if ref_to_save else "No referral code — standard fees apply."
                await send_telegram_message(
                    context.bot, chat_id, get_string(_key, language, default=_def))
                kyc_url = f"{config.MINIAPP_URL.rstrip(chr(47))}/kyc?uid={chat_id}&lang={language}"
                intro, btn = kyc_form_texts(language)
                await context.bot.send_message(
                    chat_id=chat_id, text=intro,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(btn, web_app=WebAppInfo(url=kyc_url))]]),
                )
            else:
                await send_telegram_message(
                    context.bot, chat_id,
                    get_string("invalidReferralCode", language,
                               default="This referral code is not valid. Enter a valid code, "
                                       "or write «NONE» if you don't have one:"))
                await update_user_state_with_retry(chat_id, {"step": "referral"})
        elif current_step == "kyc_form":
            # L'user doit utiliser le bouton (mini app), pas taper du texte.
            kyc_url = f"{config.MINIAPP_URL.rstrip(chr(47))}/kyc?uid={chat_id}&lang={language}"
            intro, btn = kyc_form_texts(language)
            await context.bot.send_message(
                chat_id=chat_id,
                text=intro,
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(btn, web_app=WebAppInfo(url=kyc_url))
                ]]),
            )
        elif current_step == "firstName":
            if is_valid_name(text):
                await update_user_state_with_retry(
                    chat_id, {"firstName": text, "step": "lastName"}
                )
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string("askLastName", language, default="Last name:")
                )
            else:
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "invalidName",
                        language,
                        default="Invalid name. Please enter a valid name:")
                )
                # Keep the user in the firstName step
                await update_user_state_with_retry(chat_id, {"step": "firstName"})
        elif current_step == "lastName":
            if is_valid_name(text):
                await update_user_state_with_retry(
                    chat_id, {"lastName": text, "step": "email"}
                )
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string("askEmail", language, default="Email:")
                )
            else:
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "invalidLastName",
                        language,
                        default="Invalid last name. Please enter a valid last name:")
                )
                # Keep the user in the lastName step
                await update_user_state_with_retry(chat_id, {"step": "lastName"})
        elif current_step == "email":
            if is_valid_email(text):
                await update_user_state_with_retry(
                    chat_id, {"email": text, "step": "phone"}
                )
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string("askPhone", language, default="Phone number:")
                )
            else:
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "invalidEmail",
                        language,
                        default="Invalid email. Please enter a valid email address:")
                )
                # Keep the user in the email step
                await update_user_state_with_retry(chat_id, {"step": "email"})
        elif current_step == "phone":
            if is_valid_phone(text):
                logger.info(f"User {chat_id} completed phone verification")
                await update_user_state_with_retry(chat_id, {"phone": text})
                user_data = await get_user_state(chat_id)
                thank_you = get_string("thankYou", language, default="Thank you!")
                first_name = get_string("firstName", language, default="First Name")
                last_name = get_string("lastName", language, default="Last Name")
                email = get_string("email", language, default="Email")
                phone = get_string("phone", language, default="Phone")
                referral = get_string("referralCode", language, default="Referral Code")

                summary = (
                    f"{thank_you}\n\n"
                    f"✨ {first_name}: {user_data.get('firstName')}\n"
                    f"✨ {last_name}: {user_data.get('lastName')}\n"
                    f"📧 {email}: {user_data.get('email')}\n"
                    f"📱 {phone}: {user_data.get('phone')}\n"
                    f"🔗 {referral}: {user_data.get('referralCode', 'N/A')}"
                )
                await send_telegram_message(context.bot, chat_id, summary)
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "goodbye",
                        language,
                        default="Your account is being created. Please wait...")
                )

                try:
                    # Create Nova address and card
                    nova_address = ""
                    card_number = ""
                    users_result = await mysql_client.get_all_users_from_db()
                    existing_users = [
                        u.get("userId") for u in users_result.get(
                            "users", []) if u.get("userId")]
                    new_user_index = len(list(dict.fromkeys(existing_users)))
                    nova_address = [u.get("novaAddress")
                                    for u in users_result.get("users", []) if u.get("novaAddress")][new_user_index]
                except Exception as e:
                    logger.error(f"handler found address: {e}")
                    nova_address = ""
                # unique_address_count = len(list(dict.fromkeys(nova_addresses)))

                # try:
                #     nova_client = NovaClient()
                #     nova_addr_obj = nova_client.create_deposit_address("trc20usdt")
                #     nova_address = nova_addr_obj.get("address", "")
                # except Exception as e:
                #     logger.error(f"Error creating Nova address: {e}")
                #     # Fallback: assign an existing address from users table
                #     users_result = await mysql_client.get_all_users_from_db()
                #     if not users_result or not users_result.get("success"):
                #         logger.error(
                #             "Failed to fetch users from DB for fallback address "
                #             "assignment."
                #         )
                #         nova_address = ""
                #     else:
                #         users = users_result.get("users", [])
                #         existing_users = [
                #             u.get("userId") for u in users if u.get("userId")
                #         ]
                #         unique_addresses = await mysql_client.get_pool_addresses()
                #         unique_address_count = len(unique_addresses)
                #         new_user_index = len(list(dict.fromkeys(existing_users)))
                #         if unique_address_count == 0:
                #             logger.error(
                #                 "No unique addresses available for fallback "
                #                 "assignment."
                #             )
                #             nova_address = ""
                #         else:
                #             fallback_address = unique_addresses[
                #                 new_user_index % unique_address_count
                #             ]
                #             logger.info(
                #                 f"Assigning fallback address {fallback_address} "
                #                 f"to new user at index {new_user_index}"
                #             )
                #             nova_address = fallback_address

                try:
                    interlace_client = InterlaceClient()
                    # Parse phone number for country code and local number
                    phone_full = user_data.get('phone')
                    # phone_full = PHONE_NUMBER
                    phone_code = ""
                    phone_local = ""
                    match = re.match(
                        r"^\+?(\d{1,4})[\s-]?([\d]+)$", phone_full.replace(" ", "")
                    )
                    if match:
                        phone_code = match.group(1)
                        phone_local = match.group(2)
                    else:
                        # fallback: use first 2-3 digits as code
                        phone_code = phone_full[:2]
                        phone_local = phone_full[2:]

                    # First, get available BINs
                    available_bins = (
                        interlace_client.infinity_card.list_available_bins()
                    )
                    if not available_bins or not available_bins.get("data"):
                        raise Exception("No available BINs found")

                    name_additional = "".join(
                        random.choices(string.ascii_uppercase, k=2)
                    )
                    # Get the first available BIN
                    # supported_bin = available_bins['data'][0]['bin']
                    # logger.info(f"Using supported BIN: {supported_bin}")

                    card_payload = {
                        "type": "PrepaidCard",
                        "bin": BIN,
                        "batchCount": 1,
                        "cost": OPEN_CARD_INITIAL_AMOUNT,
                        "firstName": user_data.get("firstName", ""),
                        "lastName": f"{user_data.get('lastName', '')}{name_additional}",
                        "email": EMAIL,
                        "phoneCode": phone_code,
                        "phone": phone_local,
                        "clientTransactionId": f"createCard_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}",
                        "useType": "unlimited",
                        "cardMode": "PhysicalCard",
                    }
                    card_resp = interlace_client.infinity_card.create_infinity_card(
                        card_payload
                    )
                    if card_resp and card_resp.get("code") == 0:
                        cards = interlace_client.infinity_card.list_all_infinity_cards()
                        for card in cards:
                            if isinstance(card, Card) and card.user_name == (
                                f"{card_payload['firstName']} "
                                f"{card_payload['lastName']}"
                            ):
                                card_id = card.id
                                try:
                                    transfer_response = interlace_client.infinity_card.infinity_card_transfer_out(
                                        {
                                            "cardId": card_id,
                                            "cost": OPEN_CARD_INITIAL_AMOUNT,
                                            "clientTransactionId": f"createCard_telegram_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}",
                                        }
                                    )
                                    logger.info(
                                        f"Successfully transferred out card creation fee: {transfer_response}"
                                    )
                                except BaseException:
                                    logger.error(
                                        f"Error transferring out card creation fee: {e} in telegram handler"
                                    )
                                card_details = interlace_client.infinity_card.get_infinity_card_details(
                                    card_id
                                )
                                if card_details and isinstance(
                                    card_details, CardDetails
                                ):
                                    card_number = card_details.card_no
                                    break
                    else:
                        logger.error(f"Card creation failed: {card_resp}")
                except Exception as e:
                    card_number = ""
                    logger.error(f"Error creating card: {e}")

                # Process the lead
                user_tg = update.effective_user
                lead_data = {
                    "chatId": chat_id,
                    "username": user_tg.username if user_tg else "",
                    "firstName": user_data.get("firstName", ""),
                    "lastName": user_data.get("lastName", ""),
                    "email": user_data.get("email", ""),
                    "phone": user_data.get("phone", ""),
                    "referralCode": user_data.get("referralCode", ""),
                    "firstNameChat": user_tg.first_name if user_tg else "",
                    "lastNameChat": user_tg.last_name if user_tg else "",
                    "language": language,
                    "CARD ID": card_number,
                    "nova_address": nova_address,
                }
                result = await add_lead_to_sheet_bot(lead_data)

                if result.get("success"):
                    result = await mysql_client.add_user_to_db(lead_data)

                if result.get("success"):
                    await mark_request_completed(chat_id)
                    await update_user_state_with_retry(chat_id, {"step": "completed"})
                    logger.info(f"BOT: Completed request for {chat_id}")
                    # Send notification to Telegram channel
                    try:
                        channel_id = getattr(config, "ID_CHANNEL", None)
                        if channel_id:
                            recap = (
                                f"🎉 New user enrolled!\n"
                                f"ID: {chat_id}\n"
                                f"Name: {user_data.get('firstName')} "
                                f"{user_data.get('lastName')}\n"
                                f"Email: {user_data.get('email')}\n"
                                f"Phone: {user_data.get('phone')}\n"
                                f"Referral: {user_data.get('referralCode', 'N/A')}\n"
                                f"Card: {card_number}\n"
                                f"Nova Address: {nova_address}"
                            )
                            await send_telegram_message(context.bot, channel_id, recap)

                            await send_telegram_message(
                                context.bot,
                                chat_id,
                                get_string(
                                    "accountCreated", language, default="Your account has being created")
                            )

                    except Exception as e:
                        logger.error(f"Error sending channel notification: {e}")
                else:
                    await send_telegram_message(
                        context.bot,
                        chat_id,
                        "Error submitting your request. Please try again later.",
                    )
            else:
                logger.warning(f"User {chat_id} provided invalid phone number: {text}")
                await send_telegram_message(
                    context.bot,
                    chat_id,
                    get_string(
                        "invalidPhone",
                        language,
                        default="Invalid phone number. Please enter a valid phone number:")
                )
                await update_user_state_with_retry(chat_id, {"step": "phone"})
        else:
            logger.warning(f"User {chat_id} in unknown state: {current_step}")
            await send_telegram_message(
                context.bot,
                chat_id,
                get_string(
                    "restart",
                    language,
                    default="Please use /start to begin the enrollment process.")
            )
            await update_user_state_with_retry(chat_id, {"step": "language"})

    except Exception as e:
        logger.error(
            f"Error in handle_message for chat_id {chat_id}: {e}",
            exc_info=True)
        try:
            await send_telegram_message(
                context.bot,
                chat_id,
                get_string(
                    "error",
                    language,
                    default="An error occurred. Please use /start to begin again.")
            )
            await update_user_state_with_retry(chat_id, {"step": "language"})
        except Exception as notify_e:
            logger.error(
                f"Failed to send error notification: {notify_e}",
                exc_info=True)


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")


async def background_tasks():
    while True:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in background task: {e}")
            await asyncio.sleep(5)
