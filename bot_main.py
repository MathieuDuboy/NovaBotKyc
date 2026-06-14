"""
Telegram Bot Implementation (Standalone).

This module contains the bot logic with MongoDB state management,
Redis-based message queue, and Google Sheets integration.
Optimized for high concurrency.
"""

import asyncio
import json
import logging
import os
import platform
import signal
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (AIORateLimiter, Application, CallbackQueryHandler,
                          CommandHandler, ContextTypes, Defaults, ExtBot,
                          MessageHandler, filters)

# Import Redis - for high-performance message queue and state caching
try:
    from services.redis_service import RedisClientWrapper
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("Redis not found. Install with: pip install redis")

# Import MongoDB client with connection pooling settings
try:
    from bson.objectid import ObjectId
    from motor.motor_asyncio import AsyncIOMotorClient
    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    logging.warning("MongoDB not found. Install with: pip install motor")

# Import Google Sheets service
try:
    from services.sheets_service import SheetsService
    SHEETS_AVAILABLE = True
except ImportError:
    SHEETS_AVAILABLE = False
    logging.warning(
        "Google Sheets not found. Install with: pip install google-api-python-client")

# Import MySQL client
try:
    from services.mysql_service import mysql_client
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    logging.warning("MySQL not found. Install with: pip install aiomysql")

# Import configuration
import config
# Import handlers
from telegram_bot.handlers import (background_tasks, error_handler,
                                   handle_message, language_selection, start)
# Import language utilities
from telegram_bot.utils.language import load_languages
from utils.logger import logger

# --- Global State ---
# Initialize Redis client for message queue and state caching
redis_client = RedisClientWrapper() if REDIS_AVAILABLE else None

# Initialize MongoDB client with connection pooling
mongo_client = None
if MONGODB_AVAILABLE:
    try:
        mongo_client = AsyncIOMotorClient(
            config.MONGODB_URI,
            maxPoolSize=config.MONGODB_MAX_POOL_SIZE,
            minPoolSize=config.MONGODB_MIN_POOL_SIZE,
            maxIdleTimeMS=config.MONGODB_MAX_IDLE_TIME_MS,
            waitQueueTimeoutMS=config.MONGODB_WAIT_QUEUE_TIMEOUT_MS,
            retryWrites=True,
            retryReads=True
        )
        logger.info("MongoDB connection established successfully")
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        MONGODB_AVAILABLE = False

# Initialize Google Sheets service
sheets_service = None
if SHEETS_AVAILABLE:
    try:
        sheets_service = SheetsService()
        sheets_service.initialize(config.ABS_CREDENTIALS_PATH, config.SPREADSHEET_ID)
        logger.info("Google Sheets service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets service: {e}")
        SHEETS_AVAILABLE = False

# --- Message Queue Implementation ---
# Redis-based message queue for ordered message delivery


async def enqueue_message_redis(context, chat_id, text, **kwargs):
    """Add message to Redis queue and process in order."""
    try:
        # Add message to Redis list
        await redis_client.rpush(f"queue:{chat_id}", json.dumps((text, kwargs)))

        # Process queue if not already processing
        if not await redis_client.exists(f"processing:{chat_id}"):
            await process_queue_redis(None, chat_id)
    except Exception as e:
        logger.error(f"Error enqueueing message to Redis: {e}")
        # Fall back to memory queue
        await enqueue_message_memory(None, chat_id, text, **kwargs)


# --- In-memory Message Queue (Fallback) ---
message_queue = {}  # For ordered message delivery
is_processing = {}  # Lock mechanism for message processing


async def enqueue_message_memory(context, chat_id, text, **kwargs):
    """Add message to memory queue and process in order (fallback)."""
    if chat_id not in message_queue:
        message_queue[chat_id] = []

    message_queue[chat_id].append((text, kwargs))

    if not is_processing.get(chat_id, False):
        await process_queue_memory(context, chat_id)


async def process_queue_memory(context, chat_id):
    """Process memory-based message queue for a user in order."""
    if is_processing.get(chat_id, False):
        return  # Prevent concurrent execution

    is_processing[chat_id] = True

    try:
        while chat_id in message_queue and message_queue[chat_id]:
            text, kwargs = message_queue[chat_id].pop(0)
            await send_message(context, chat_id, text, **kwargs)
    finally:
        is_processing[chat_id] = False


async def process_queue_redis(context, chat_id):
    """Process Redis-based message queue for a user in order."""
    try:
        # Set processing flag with 30-second expiry
        if not await redis_client.set(f"processing:{chat_id}", "1", ex=30, nx=True):
            return

        while True:
            # Get next message from queue
            message_data = await redis_client.lpop(f"queue:{chat_id}")
            if not message_data:
                break

            # Parse message data
            text, kwargs = json.loads(message_data)

            # Send message
            try:
                await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
            except Exception as e:
                logger.error(f"Error sending message: {e}")
                # Re-queue failed message
                await redis_client.rpush(f"queue:{chat_id}", message_data)
                break

            # Rate limiting
            await asyncio.sleep(0.1)  # 100ms between messages

    except Exception as e:
        logger.error(f"Error processing Redis queue: {e}")
    finally:
        # Clear processing flag
        await redis_client.delete(f"processing:{chat_id}")


# --- MongoDB State Management with Redis Caching ---
async def get_user_state(chat_id: int) -> dict:
    """Get user state from Redis or MongoDB."""
    try:
        # Try Redis first
        if REDIS_AVAILABLE:
            state_data = await redis_client.get(f"state:{chat_id}")
            if state_data:
                return json.loads(state_data)

        # Fall back to MongoDB
        if MONGODB_AVAILABLE:
            user = await mongo_client[config.MONGODB_DB_NAME].users.find_one({"chat_id": chat_id})
            if user:
                # Cache in Redis for next time
                if REDIS_AVAILABLE:
                    await redis_client.set(
                        f"state:{chat_id}",
                        json.dumps(user),
                        ex=3600  # 1 hour cache
                    )
                return user

        return {}
    except Exception as e:
        logger.error(f"Error getting user state: {e}")
        return {}


async def update_user_state(chat_id: int, update_data: dict):
    """Update user state in both Redis and MongoDB."""
    try:
        # Update MongoDB
        if MONGODB_AVAILABLE:
            await mongo_client[config.MONGODB_DB_NAME].users.update_one(
                {"chat_id": chat_id},
                {"$set": update_data},
                upsert=True
            )

        # Update Redis cache
        if REDIS_AVAILABLE:
            # Get current state
            current_state = await get_user_state(chat_id)
            # Merge with updates
            current_state.update(update_data)
            # Update cache
            await redis_client.set(
                f"state:{chat_id}",
                json.dumps(current_state),
                ex=3600  # 1 hour cache
            )
    except Exception as e:
        logger.error(f"Error updating user state: {e}")


async def is_request_completed(chat_id):
    """Checks if a user has completed their request."""
    # Try Redis cache first
    if redis_client and REDIS_AVAILABLE:
        try:
            completed = await redis_client.get(f"completed:{chat_id}")
            if completed:
                return True
        except Exception as e:
            logger.warning(f"Redis error checking completion: {e}")

    # Fall back to MongoDB
    if not MONGODB_AVAILABLE or mongo_client is None or mongo_client.completed_requests is None:
        logger.warning("MongoDB not available. Request completion unknown.")
        return False

    try:
        result = await mongo_client[config.MONGODB_DB_NAME].completed_requests.find_one({"chat_id": chat_id})
        completed = bool(result)

        # Cache result in Redis if available
        if redis_client and REDIS_AVAILABLE and completed:
            try:
                # 24hr cache
                await redis_client.set(f"completed:{chat_id}", "1", ex=86400)
            except Exception as e:
                logger.warning(f"Redis error caching completion: {e}")

        return completed
    except Exception as e:
        logger.error(f"Error checking request completion: {e}")
        return False


async def mark_request_completed(chat_id):
    """Marks a user's request as completed."""
    # Update MongoDB
    if MONGODB_AVAILABLE and mongo_client is not None and mongo_client.completed_requests is not None:
        try:
            await mongo_client[config.MONGODB_DB_NAME].completed_requests.insert_one({
                "chat_id": chat_id,
                "timestamp": datetime.now(timezone.utc)
            })
        except Exception as e:
            logger.error(f"Error marking request completed in MongoDB: {e}")

    # Update Redis cache if available
    if redis_client and REDIS_AVAILABLE:
        try:
            await redis_client.set(f"completed:{chat_id}", "1", ex=86400)  # 24hr cache
        except Exception as e:
            logger.warning(f"Redis error marking completion: {e}")


async def log_to_mongodb(log_data):
    """Logs an event to MongoDB with batching for high volume."""
    if not MONGODB_AVAILABLE or mongo_client is None or mongo_client.logs is None:
        return

    try:
        log_data["timestamp"] = datetime.now()

        # If Redis available, use batching for high throughput
        if redis_client and REDIS_AVAILABLE:
            try:
                # Push to Redis list for batched processing
                await redis_client.lpush(
                    "log_queue",
                    json.dumps(log_data, default=str)
                )

                # If queue is long enough, process batch
                queue_len = await redis_client.llen("log_queue")
                if queue_len >= 50:  # Batch size of 50
                    await process_log_batch()
            except Exception as e:
                logger.warning(f"Redis batching error: {e}")
                # Fall back to direct MongoDB insert
                await mongo_client[config.MONGODB_DB_NAME].logs.insert_one(log_data)
        else:
            # Direct insert to MongoDB
            await mongo_client[config.MONGODB_DB_NAME].logs.insert_one(log_data)
    except Exception as e:
        logger.error(f"Error logging to MongoDB: {e}")


async def process_log_batch():
    """Process a batch of logs from Redis queue."""
    if not redis_client or mongo_client is None or mongo_client.logs is None:
        return

    try:
        # Get up to 50 log items
        pipe = redis_client.pipeline()
        pipe.lrange("log_queue", 0, 49)
        pipe.ltrim("log_queue", 50, -1)
        results = await pipe.execute()

        items = results[0]
        if not items:
            return

        # Parse logs and prepare for bulk insert
        logs_to_insert = []
        for item in items:
            try:
                log_data = json.loads(item)
                if isinstance(log_data, dict):
                    logs_to_insert.append(log_data)
            except Exception:
                continue

        # Bulk insert to MongoDB
        if logs_to_insert:
            await mongo_client[config.MONGODB_DB_NAME].logs.insert_many(logs_to_insert)
    except Exception as e:
        logger.error(f"Error processing log batch: {e}")


# --- Message Sending ---
async def send_message(context, chat_id, text, **kwargs):
    """Safely sends a message using the bot context with retry logic."""
    if not context or not context.bot:
        logger.error("Bot context unavailable for sending message.")
        return

    max_retries = 3
    for attempt in range(max_retries):
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
            logger.debug(f"Sent message to {chat_id}: {text[:50]}...")

            # Log message to MongoDB
            await log_to_mongodb({
                "type": "message_sent",
                "chat_id": chat_id,
                "text_length": len(text),
                "has_markup": "reply_markup" in kwargs
            })
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                # Exponential backoff: wait longer between retries
                wait_time = (2 ** attempt) * 0.5  # 0.5, 1, 2 seconds
                logger.warning(
                    f"Retrying send message to {chat_id} after {wait_time}s: {e}"
                )
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Failed to send message to {chat_id}: {e}")
                return False


# --- Enhanced enqueue_message function (Redis + Fallback) ---
async def enqueue_message(context, chat_id, text, **kwargs):
    """Smart message queueing with Redis or memory fallback."""
    if redis_client and REDIS_AVAILABLE:
        await enqueue_message_redis(context, chat_id, text, **kwargs)
    else:
        await enqueue_message_memory(context, chat_id, text, **kwargs)


# --- Google Sheets Lead Addition with Caching ---
async def add_lead_to_sheet_bot(context, lead_data):
    """Adds lead record to Google Sheets first, which will trigger MySQL save."""
    try:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        required_fields = ['chatId', 'firstName', 'lastName', 'email', 'phone']

        if not all(lead_data.get(field) for field in required_fields):
            logger.error(f"BOT: Incomplete lead data: {lead_data}")
            return {
                'success': False,
                'message': "Incomplete lead data provided."
            }

        logger.info(f"BOT: Adding lead to Google Sheets for {lead_data.get('chatId')}")

        # Initialize Google Sheets service
        sheets_service = initialize_sheets_service()
        if not sheets_service:
            logger.error("BOT: Failed to initialize Google Sheets service")
            return {'success': False, 'message': "Sheets service unavailable"}

        # Prepare row data for Google Sheets
        row_data = [
            lead_data.get('chatId', ''),  # USER_ID
            lead_data.get('username', ''),  # username
            current_date,  # created_at
            lead_data.get('firstName', ''),  # firstName
            lead_data.get('lastName', ''),  # lastName
            lead_data.get('email', ''),  # email
            lead_data.get('phone', ''),  # phone
            lead_data.get('referralCode', ''),  # referralCode
            lead_data.get('firstNameChat', ''),  # firstNameChat
            lead_data.get('lastNameChat', ''),  # lastNameChat
            lead_data.get('language', ''),  # language
            '',  # CARD ID (empty initially)
            '',  # nova_address (empty initially)
            'active'  # status (active by default)
        ]

        try:
            # Append row to users sheet
            range_name = f'{config.USERS_SHEET}!A:N'  # tab user (config-driven)
            body = {
                'values': [row_data]
            }
            result = sheets_service.spreadsheets().values().append(
                spreadsheetId=config.SPREADSHEET_ID,
                range=range_name,
                valueInputOption='RAW',
                insertDataOption='INSERT_ROWS',
                body=body
            ).execute()

            if result.get('updates', {}).get('updatedRows', 0) > 0:
                logger.info(
                    f"BOT: Data saved to Google Sheets for user {lead_data.get('chatId')}")
                return {'success': True, 'message': "Lead added successfully."}
            else:
                logger.error("BOT: Failed to save lead to Google Sheets")
                return {'success': False, 'message': "Failed to save lead data."}

        except Exception as e:
            logger.error(f"BOT: Error saving to Google Sheets: {e}")
            return {'success': False, 'message': str(e)}

    except Exception as e:
        logger.error(f"BOT: Error adding lead: {e}")
        return {'success': False, 'message': str(e)}


# --- Background tasks for processing queues ---
async def process_pending_leads():
    """Process any pending leads in the Redis queue."""
    if not redis_client or not REDIS_AVAILABLE:
        return

    try:
        # Get pending leads (up to 5 at a time)
        pipe = await redis_client.pipeline()
        pipe.lrange("pending_leads", 0, 4)
        pipe.ltrim("pending_leads", 5, -1)
        results = await redis_client.execute_pipeline(pipe)

        items = results[0]
        if not items:
            return

        for item in items:
            try:
                lead_data = json.loads(item)
                # Process each lead
                if isinstance(lead_data, dict) and "chatId" in lead_data:
                    # Store lead data in MongoDB for now
                    if mongo_client and mongo_client.logs:
                        await mongo_client[config.MONGODB_DB_NAME].logs.insert_one(
                            {
                                "type": "pending_lead",
                                "data": lead_data,
                                "timestamp": datetime.now(timezone.utc),
                            }
                        )
                    # Re-queue for later processing
                    await redis_client.lpush(
                        "pending_leads", json.dumps(lead_data, default=str)
                    )
            except Exception as e:
                logger.error(f"Error processing pending lead: {e}")
    except Exception as e:
        logger.error(f"Error in process_pending_leads: {e}")


async def background_tasks():
    """Run background tasks for queue processing."""
    while True:
        try:
            # Process log batches
            if mongo_client is not None and mongo_client.logs is not None:
                await process_log_batch()

            # Process pending leads
            await process_pending_leads()

            # Check for expired processing locks and clear them
            if redis_client and REDIS_AVAILABLE:
                # Find all processing locks
                processing_keys = await redis_client.keys("processing:*")
                for key in processing_keys:
                    # Check if older than 5 minutes (possible dead lock)
                    ttl = await redis_client.ttl(key)
                    if ttl < 0 or ttl < 30:  # No TTL or less than 30 seconds left
                        # Clear lock
                        await redis_client.delete(key)
                        logger.info(f"Cleared potentially dead lock: {key}")
        except Exception as e:
            logger.error(f"Error in background tasks: {e}")

        # Run every 10 seconds
        await asyncio.sleep(10)


# --- Telegram Bot Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command, initiating the conversation."""
    if not update.effective_chat:
        logger.warning("BOT: /start handler: No effective chat.")
        return

    chat_id = update.effective_chat.id
    logger.info(f"BOT: /start: Processing for chat_id {chat_id}")

    # Log start command to MongoDB
    await log_to_mongodb({
        "type": "command",
        "command": "start",
        "chat_id": chat_id,
        "username": update.effective_user.username if update.effective_user else None
    })

    # Check if user has already completed a request
    if await is_request_completed(chat_id):
        await send_message(
            context,
            chat_id,
            "⏳ Your request is being processed - Ваш запрос обрабатывается. 🎉 We will inform you as soon as your account is active."
        )
        return

    # Initialize user data structure
    await update_user_state(chat_id, {"step": "language"})

    # Send language selection keyboard
    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data='en'),
            InlineKeyboardButton("🇷🇺 Русский", callback_data='ru')
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_msg = "👋 Welcome! Please choose your language/ Пожалуйста, выберите ваш язык:"

    await send_message(
        context,
        chat_id,
        welcome_msg,
        reply_markup=reply_markup
    )
    logger.info(f"BOT: /start: Sent language selection to {chat_id}")


async def language_selection(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handles language selection callback."""
    query = update.callback_query
    if not query or not query.message:
        return

    await query.answer()  # Acknowledge the callback
    chat_id = query.message.chat_id
    lang_code = query.data

    # Log language selection to MongoDB
    await log_to_mongodb({
        "type": "language_selection",
        "chat_id": chat_id,
        "language": lang_code
    })

    if lang_code in languages:
        # Save language preference
        await update_user_state(chat_id, {"lang": lang_code})

        # Edit message to confirm selection
        try:
            await query.edit_message_text(f"Language: {lang_code.upper()}")
        except Exception as e:
            logger.warning(f"Could not edit message: {e}")

        # Send welcome messages
        thank_you = get_string(
            languages, lang_code, 'thankYouLanguage', "Thanks!"
        )
        await enqueue_message(context, chat_id, thank_you)

        # Send account details
        creation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        account_created = get_string(
            languages, lang_code, 'accountCreated', "Account created."
        )
        account_id = get_string(languages, lang_code, 'accountId', "ID")
        date_text = get_string(languages, lang_code, 'creationDate', "Date")

        details = (
            f"Your account has been created.\n"
            f"<b>Account ID</b>: {chat_id}\n"
            f"<b>Creation date</b>: {creation_date}"
        )
        await enqueue_message(
            context, chat_id, details, parse_mode='HTML'
        )

        # Ask for referral code
        referral_prompt = get_string(
            languages, lang_code, 'askReferralCode', "Referral code:"
        )
        await enqueue_message(context, chat_id, referral_prompt)

        # Update conversation state
        await update_user_state(chat_id, {"step": "referral"})
    else:
        error_msg = "❌ Please choose a valid language / Пожалуйста, выберите язык"
        await send_message(context, chat_id, error_msg)


async def handle_message(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle incoming messages with rate limiting and state management."""
    try:
        # Get user state
        user_state = await get_user_state(update.effective_chat.id)

        # Check rate limits
        if not await check_rate_limits(update.effective_chat.id):
            await update.message.reply_text(
                "Please wait a moment before sending another message."
            )
            return

        # Process message
        response = await process_message(update.message.text, user_state)

        # Update state
        await update_user_state(update.effective_chat.id, {
            "last_message": update.message.text,
            "last_response": response,
            "updated_at": datetime.now(timezone.utc).isoformat()
        })

        # Send response
        await enqueue_message_redis(
            context,
            update.effective_chat.id,
            response
        )

    except Exception as e:
        logger.error(f"Error handling message: {e}")
        await error_handler(update, context)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Logs errors caused by updates."""
    error_message = f"Exception handling update: {context.error}"
    logger.error(f"BOT: {error_message}", exc_info=context.error)

    # Log error to MongoDB
    try:
        if mongo_client is not None and mongo_client.logs is not None:
            await mongo_client[config.MONGODB_DB_NAME].logs.insert_one({
                "type": "error",
                "timestamp": datetime.now(),
                "error": str(context.error),
                "update_json": str(update) if update else None
            })
    except Exception as e:
        logger.error(f"Failed to log error to MongoDB: {e}")


# --- Bot Configuration and Setup ---
def setup_application(token=None):
    """Set up the bot application with handlers and configuration."""
    bot_token = token or config.BOT_TOKEN
    if not bot_token:
        logger.critical("BOT_TOKEN not configured or missing. Bot cannot start.")
        return None

    # Ensure we have an event loop
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        # Create new event loop if needed
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Define bot defaults with optimized settings
    defaults = Defaults(
        parse_mode='HTML',  # Default parse mode for messages
        disable_notification=False
    )

    # Build application with rate limiting and optimized settings
    builder = Application.builder().token(bot_token).defaults(defaults)

    # Try to add rate limiter if available
    try:
        builder = builder.rate_limiter(AIORateLimiter(
            max_retries=3  # Max retries for rate limited calls
        ))
        logger.info("Rate limiter configured successfully")
    except RuntimeError as e:
        logger.warning(
            f"Rate limiter not available: {e}. Consider installing with: pip install \"python-telegram-bot[rate-limiter]\"")

    application = builder.build()

    # Register handlers only for main bot
    if not token:
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CallbackQueryHandler(language_selection))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        )
        application.add_error_handler(error_handler)

    # Set up graceful shutdown
    setup_shutdown_handlers(application)

    return application


# --- Graceful Shutdown Handling ---
def setup_shutdown_handlers(application):
    """Set up handlers for graceful shutdown."""
    # Define shutdown handler
    async def shutdown_bot(signal_num, frame):
        """Gracefully shut down the bot."""
        logger.info(f"Received shutdown signal {signal_num}, shutting down...")

        # Stop the application
        if application:
            await application.stop()
            logger.info("Application stopped.")

        # Close Redis connection
        if redis_client and REDIS_AVAILABLE:
            try:
                await redis_client.close()
                logger.info("Redis connection closed.")
            except Exception as e:
                logger.error(f"Error closing Redis: {e}")

        # Close MongoDB connection
        if mongo_client:
            try:
                mongo_client.close()
                logger.info("MongoDB connection closed.")
            except Exception as e:
                logger.error(f"Error closing MongoDB: {e}")

        # Stop the event loop
        loop = asyncio.get_event_loop()
        loop.stop()

    # Replace the signal handler setup in bot_main.py:
    if platform.system() != 'Windows':
        # Unix-style signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.create_task(
                    shutdown_bot(
                        s, None)))
    else:
        # Windows fallback
        signal.signal(
            signal.SIGINT,
            lambda s,
            f: asyncio.create_task(
                shutdown_bot(
                    s,
                    f)))


# --- Bot Runner Functions ---
async def run_polling(application):
    """Run the bot in polling mode (development)."""
    logger.info("Starting bot in polling mode")

    # Start background tasks
    bg_task = asyncio.create_task(background_tasks())

    try:
        # Start polling
        await application.initialize()
        await application.start()
        await application.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=[
                "message", "callback_query", "inline_query",
                "chosen_inline_result", "chat_member"
            ]
        )
        # Just keep running until interrupted
        running = asyncio.Event()
        await running.wait()
    finally:
        # Clean up background task
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass
        # Properly shut down the application
        await application.stop()
        await application.shutdown()


async def run_webhook(application):
    """Run the bot in webhook mode (production)."""
    # Access webhook configuration from the config module
    webhook_url = config.WEBHOOK_URL
    webhook_path = config.WEBHOOK_PATH
    listen_host = config.WEBHOOK_LISTEN or "0.0.0.0"
    listen_port = config.WEBHOOK_PORT or 8443

    if not webhook_url or not webhook_path:
        logger.critical("Webhook configuration missing. Cannot start in webhook mode.")
        return

    logger.info(f"Starting bot in webhook mode at {webhook_url}")

    # Start background tasks
    bg_task = asyncio.create_task(background_tasks())

    try:
        # Set webhook
        await application.bot.set_webhook(
            url=webhook_url,
            allowed_updates=[
                "message", "callback_query", "inline_query",
                "chosen_inline_result", "chat_member"
            ],
            drop_pending_updates=True,
            secret_token=config.WEBHOOK_SECRET,  # Secure webhook with secret
            max_connections=40  # Allow multiple concurrent webhook connections
        )

        # Run webhook
        await application.run_webhook(
            listen=listen_host,
            port=listen_port,
            webhook_url=webhook_url,
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=True,
            url_path=webhook_path
        )
    finally:
        # Clean up background task and webhook
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass

        await application.bot.delete_webhook()


def run_bot_instance():
    """Initialize resources and run the bot application."""
    global sheets_service, languages, redis_client
    global mongo_client

    # Create and set the event loop for the entire process
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        # Initialize resources for this bot instance
        logger.info("BOT Instance: Initializing resources...")

        # Initialize Google Sheets service
        sheets_service = initialize_sheets_service()

        # Load language files
        languages = load_languages(config.LANG_DIR)

        # Initialize Redis connection if available
        if REDIS_AVAILABLE:
            try:
                # Get Redis config from config.py
                redis_uri = f"redis://{config.REDIS_HOST}:{config.REDIS_PORT}/{config.REDIS_DB}"
                logger.info(f"Connecting to Redis: {redis_uri}")

                # Create asyncio Redis client
                redis_pool = redis.ConnectionPool.from_url(
                    redis_uri,
                    max_connections=config.MAX_REDIS_CONNECTIONS,
                    decode_responses=True
                )
                redis_client = redis.Redis(connection_pool=redis_pool)

                # Test connection using the async API properly
                async def test_redis():
                    await redis_client.ping()
                    logger.info("Redis connection established")

                # Run test in the event loop
                loop.run_until_complete(test_redis())

            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                redis_client = None

        # Initialize MongoDB connection if available
        if MONGODB_AVAILABLE:
            try:
                # Get MongoDB config from config.py
                mongo_uri = config.MONGO_URI
                db_name = config.MONGO_DB_NAME

                logger.info(f"Connecting to MongoDB: {mongo_uri}, DB: {db_name}")

                # Initialize with connection pooling
                mongo_client = AsyncIOMotorClient(
                    mongo_uri,
                    maxPoolSize=config.MONGODB_MAX_POOL_SIZE,
                    minPoolSize=config.MONGODB_MIN_POOL_SIZE,
                    maxIdleTimeMS=config.MONGODB_MAX_IDLE_TIME_MS,
                    waitQueueTimeoutMS=config.MONGODB_WAIT_QUEUE_TIMEOUT_MS,
                    retryWrites=True,
                    retryReads=True
                )

                # Get collection names from config or use defaults
                collections = config.MONGO_COLLECTIONS
                mongo_client.users = mongo_client[collections.get(
                    'users', 'users')]
                mongo_client.completed_requests = mongo_client[
                    collections.get('completed_requests', 'completed_requests')
                ]
                mongo_client.logs = mongo_client[collections.get(
                    'logs', 'logs')]

                # Create indexes properly
                async def create_indexes():
                    await mongo_client.users.create_index("chat_id", unique=True)
                    await mongo_client.completed_requests.create_index("chat_id", unique=True)
                    await mongo_client.logs.create_index("timestamp")
                    await mongo_client.logs.create_index("type")
                    await mongo_client.logs.create_index("chat_id")

                # Run in the event loop
                loop.run_until_complete(create_indexes())

                logger.info("MongoDB connection established")
            except Exception as e:
                logger.error(f"Failed to connect to MongoDB: {e}")
                mongo_client = None
        else:
            logger.warning(
                "MongoDB driver not available. Install with: pip install motor"
            )

        if not languages:
            logger.error(
                "BOT Instance: Failed to load languages. "
                "Using default strings only."
            )

        # Set up and run bot application
        application = setup_application()
        if not application:
            return

        # Choose polling or webhook mode based on config
        use_webhook = config.USE_WEBHOOK

        if use_webhook:
            # Production mode with webhook
            loop.run_until_complete(run_webhook(application))
        else:
            # Development mode with polling - run directly in the loop
            loop.run_until_complete(asyncio.wait_for(run_polling(application), None))

    except Exception as e:
        logger.error(f"Error in bot instance: {e}", exc_info=True)
    finally:
        # Clean up the event loop
        try:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()

            # Run loop until tasks are cancelled
            if pending:
                loop.run_until_complete(asyncio.gather(
                    *pending, return_exceptions=True))

            # Close the loop properly
            loop.stop()
            loop.close()
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

        logger.info("Bot shutdown complete.")


# --- Main execution block ---
if __name__ == '__main__':
    asyncio.run(run_telegram_bot())
