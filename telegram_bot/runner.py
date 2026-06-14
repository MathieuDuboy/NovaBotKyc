import asyncio
import json
import logging
import platform
import signal
from datetime import datetime, timezone

import telegram.error
from telegram import (BotCommand, BotCommandScopeAllChatAdministrators,
                      BotCommandScopeAllGroupChats,
                      BotCommandScopeAllPrivateChats, BotCommandScopeChat,
                      BotCommandScopeDefault, Update)
from telegram.ext import (AIORateLimiter, Application, CallbackQueryHandler,
                          CommandHandler, ContextTypes, Defaults,
                          MessageHandler, filters)

import config
from services.mongo_service import MongoClientWrapper
from services.mysql_service import mysql_client
from services.sheets_service import initialize_sheets_service
from telegram_bot.handlers import (background_tasks, cancel_command,
                                   error_handler, handle_message,
                                   language_selection, send_all_command,
                                   send_command, start)
from telegram_bot.utils.language import load_languages
from utils.logger import logger

ADMIN_CHAT_ID = config.ADMIN_CHAT_ID
# Import REDIS_AVAILABLE, MONGODB_AVAILABLE, redis
try:
    from services.redis_service import RedisClientWrapper

    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logging.warning("Redis not found. Install with: pip install redis")

try:
    from motor.motor_asyncio import AsyncIOMotorClient

    MONGODB_AVAILABLE = True
except ImportError:
    MONGODB_AVAILABLE = False
    AsyncIOMotorClient = None
    logging.warning("MongoDB driver not found. Install with: pip install motor")

# --- Globals for this process ---
sheets_service_client = None
languages = {}
mongo_client_instance = None
redis_client = None  # Initialize in run_telegram_bot

# Connection pool settings
MAX_MONGODB_POOL_SIZE = config.MAX_MONGODB_POOL_SIZE
MAX_REDIS_CONNECTIONS = config.MAX_REDIS_CONNECTIONS

# Rate limiting settings
CONCURRENT_UPDATES = config.CONCURRENT_UPDATES
RATE_LIMIT_WINDOW_SIZE = config.RATE_LIMIT_WINDOW_SIZE


# --- Bot Configuration and Setup ---
# Set up menu commands asynchronously
async def setup_menu_commands(application):
    # Regular user commands
    commands = [
        BotCommand(
            command="start",
            description="Start the bot and select language"),
    ]

    # Admin commands
    admin_cmds = [
        BotCommand(
            command="start",
            description="Start the admin bot -- only for admins"),
        BotCommand(command="send", description="Send message to user"),
        BotCommand(command="send_all", description="Send message to all users"),
        BotCommand(command="cancel", description="Cancel current operation"),
    ]

    max_retries = 5
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            # First, delete commands from all possible scopes
            scopes = [
                BotCommandScopeDefault(),
                BotCommandScopeAllPrivateChats(),
                BotCommandScopeAllGroupChats(),
                BotCommandScopeAllChatAdministrators(),
            ]

            for scope in scopes:
                try:
                    await application.bot.delete_my_commands(scope=scope)
                    logger.info(f"Cleared commands for scope: {scope}")
                except Exception as e:
                    logger.error(f"Error clearing commands for scope {scope}: {e}")

            # Wait a moment to ensure commands are cleared
            await asyncio.sleep(1)

            # Set commands for default scope (all users)
            await application.bot.set_my_commands(
                commands,
                scope=BotCommandScopeDefault()
            )
            logger.info("Menu commands set up successfully for default scope")

            # Set commands for admin chat using private chats scope
            await application.bot.set_my_commands(
                admin_cmds,
                scope=BotCommandScopeAllPrivateChats()
            )
            logger.info(f"Admin commands set up successfully for private chats")

            # Verify the commands were set correctly
            default_commands = await application.bot.get_my_commands(
                scope=BotCommandScopeDefault()
            )
            admin_commands = await application.bot.get_my_commands(
                scope=BotCommandScopeAllPrivateChats()
            )

            logger.info(
                f"Default scope commands: {[cmd.command for cmd in default_commands]}"
            )
            logger.info(
                f"Admin scope commands: {[cmd.command for cmd in admin_commands]}"
            )

            break  # Success
        except Exception as e:
            logger.error(
                f"Error setting up menu commands (attempt {attempt}/{max_retries}): {e}"
            )
            if attempt == max_retries:
                logger.critical(
                    "Failed to set up menu commands after maximum retries."
                )
            else:
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff


def setup_application():
    """Set up the bot application with handlers and configuration."""
    if not config.BOT_TOKEN:
        logger.critical("BOT_TOKEN not configured or missing. Bot cannot start.")
        return None

    # Ensure we have an event loop
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Define bot defaults with optimized settings
    defaults = Defaults(parse_mode="HTML", disable_notification=False)

    # Build application with rate limiting and optimized settings
    builder = Application.builder().token(config.BOT_TOKEN).defaults(defaults)

    # Try to add rate limiter if available
    try:
        builder = builder.rate_limiter(AIORateLimiter(max_retries=3))
        logger.info("Rate limiter configured successfully")
    except RuntimeError as e:
        logger.warning(
            f"Rate limiter not available: {e}. "
            "Consider installing with: pip install "
            '"python-telegram-bot[rate-limiter]"'
        )

    application = builder.build()
    logger.info("Bot application built successfully")

    # Register handlers
    application.add_handler(CommandHandler("start", start))

    # Admin-only command handlers
    admin_filter = filters.Chat(chat_id=ADMIN_CHAT_ID)

    application.add_handler(
        CommandHandler("send", send_command, filters=admin_filter)
    )
    application.add_handler(
        CommandHandler("send_all", send_all_command, filters=admin_filter)
    )
    application.add_handler(
        CommandHandler("cancel", cancel_command, filters=admin_filter)
    )

    # Regular handlers
    application.add_handler(
        CallbackQueryHandler(language_selection, pattern="^lang_")
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message))
    application.add_error_handler(error_handler)
    logger.info("Handlers registered successfully")

    # Set up the menu commands asynchronously
    asyncio.create_task(setup_menu_commands(application))

    # Set up graceful shutdown
    setup_shutdown_handlers(application)
    logger.info("Shutdown handlers configured")

    return application


# --- Graceful Shutdown Handling ---


def setup_shutdown_handlers(application):
    """Set up handlers for graceful shutdown."""

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
        if mongo_client_instance:
            try:
                await mongo_client_instance.close()
                logger.info("MongoDB connection closed.")
            except Exception as e:
                logger.error(f"Error closing MongoDB: {e}")

        # Stop the event loop
        loop = asyncio.get_event_loop()
        loop.stop()

    # Replace the signal handler setup in bot_main.py:
    if platform.system() != "Windows":
        # Unix-style signal handlers
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop = asyncio.get_event_loop()
            loop.add_signal_handler(
                sig, lambda s=sig: asyncio.create_task(shutdown_bot(s, None))
            )
    else:
        # Windows fallback
        signal.signal(
            signal.SIGINT, lambda s, f: asyncio.create_task(shutdown_bot(s, f))
        )


# --- Bot Runner Functions ---


async def run_polling(application):
    """Run the bot in polling mode (development) with retry logic."""
    logger.info("Starting bot in polling mode")

    # Start background tasks
    bg_task = asyncio.create_task(background_tasks())
    logger.info("Background tasks started")

    max_retries = 5
    delay = 2
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Initializing bot (attempt {attempt}/{max_retries})...")
            await application.initialize()
            logger.info("Bot initialized successfully")

            logger.info("Starting bot...")
            await application.start()
            logger.info("Bot started successfully")

            logger.info("Starting polling...")
            await application.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "inline_query",
                    "chosen_inline_result",
                    "chat_member",
                ],
            )
            logger.info("Polling started successfully")
            break  # Success, exit retry loop
        except (telegram.error.NetworkError, telegram.error.RetryAfter, Exception) as e:
            logger.error(
                f"Polling failed (attempt {attempt}/{max_retries}): {e}", exc_info=True
            )
            if attempt == max_retries:
                logger.critical(
                    "Polling failed after maximum retries. " "Exiting polling loop."
                )
                raise
            else:
                logger.info(f"Retrying polling in {delay} seconds...")
                await asyncio.sleep(delay)
                delay *= 2  # Exponential backoff

    try:
        # Just keep running until interrupted
        logger.info("Bot is now running and waiting for messages...")
        running = asyncio.Event()
        await running.wait()
    finally:
        # Clean up background task
        logger.info("Shutting down bot...")
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass
        # Properly shut down the application
        await application.stop()
        await application.shutdown()
        logger.info("Bot shutdown complete")


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
                "message",
                "callback_query",
                "inline_query",
                "chosen_inline_result",
                "chat_member",
            ],
            drop_pending_updates=True,
            secret_token=config.WEBHOOK_SECRET,
            max_connections=40,
        )

        # Run webhook
        await application.run_webhook(
            listen=listen_host,
            port=listen_port,
            webhook_url=webhook_url,
            secret_token=config.WEBHOOK_SECRET,
            drop_pending_updates=True,
            url_path=webhook_path,
        )
    finally:
        # Clean up background task and webhook
        bg_task.cancel()
        try:
            await bg_task
        except asyncio.CancelledError:
            pass

        await application.bot.delete_webhook()


async def run_telegram_bot():
    """Main entry point for running the Telegram bot."""
    global sheets_service_client, mongo_client_instance, redis_client
    logger.info("Starting Telegram bot initialization...")

    # Initialize MongoDB if available
    if MONGODB_AVAILABLE:
        try:
            mongo_client_instance = MongoClientWrapper()
            logger.info("MongoDB connection established")
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            mongo_client_instance = None

    # Initialize Redis if available
    if REDIS_AVAILABLE:
        try:
            redis_client = RedisClientWrapper()
            # Test connection
            if not await redis_client.ping():
                raise Exception("Redis ping failed")
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            redis_client = None

    # Initialize Google Sheets service
    sheets_service_client = initialize_sheets_service()
    logger.info("Google Sheets service initialized")

    # Load languages
    global languages
    languages = load_languages(config.LANG_DIR_REL)
    logger.info(f"Loaded languages: {list(languages.keys())}")

    # Set up the application
    logger.info("Setting up bot application...")
    application = setup_application()
    if not application:
        logger.critical("Failed to set up application. Exiting.")
        return
    logger.info("Bot application setup complete")

    # Initialize handlers with MongoDB and Redis clients
    logger.info("Handlers initialized with database connections")

    # Check if webhook mode is enabled
    if config.WEBHOOK_ENABLED:
        logger.info("Starting bot in webhook mode...")
        try:
            # Set up webhook
            await application.bot.set_webhook(
                url=config.WEBHOOK_URL + config.WEBHOOK_PATH,
                allowed_updates=[
                    "message",
                    "callback_query",
                    "inline_query",
                    "chosen_inline_result",
                    "chat_member",
                ],
                drop_pending_updates=True,
                secret_token=config.WEBHOOK_SECRET,
                max_connections=40,
            )
            logger.info("Webhook configured successfully")
        except Exception as e:
            logger.error(f"Error setting up webhook: {e}", exc_info=True)
            raise
    else:
        # Run in polling mode
        logger.info("Starting bot in polling mode...")
        try:
            # Ensure we're in the right event loop
            loop = asyncio.get_event_loop()
            logger.info(f"Using event loop: {loop}")

            # Start the bot in polling mode
            await run_polling(application)
        except Exception as e:
            logger.error(f"Error in run_polling: {e}", exc_info=True)
            raise


async def process_log_batch():
    """Process a batch of logs from Redis queue."""
    if (
        not redis_client
        or mongo_client_instance is None
        or mongo_client_instance.logs is None
    ):
        return

    try:
        # Get up to 50 log items
        pipe = await redis_client.pipeline()
        await pipe.lrange("log_queue", 0, 49)
        await pipe.ltrim("log_queue", 50, -1)
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
            except Exception as e:
                logger.error(f"Error parsing log item: {e}")
                continue

        # Bulk insert to MongoDB
        if logs_to_insert:
            try:
                await mongo_client_instance.logs.insert_many(logs_to_insert)
            except Exception as e:
                logger.error(f"Error inserting logs to MongoDB: {e}")
    except Exception as e:
        logger.error(f"Error processing log batch: {e}")


async def process_pending_leads():
    """Process any pending leads in the Redis queue."""
    if not redis_client or not REDIS_AVAILABLE:
        return

    try:
        # Get pending leads (up to 5 at a time)
        pipe = await redis_client.pipeline()
        await pipe.lrange("pending_leads", 0, 4)
        await pipe.ltrim("pending_leads", 5, -1)
        results = await pipe.execute()

        items = results[0]
        if not items:
            return

        for item in items:
            try:
                lead_data = json.loads(item)
                # Process each lead
                if isinstance(lead_data, dict) and "chatId" in lead_data:
                    # Store lead data in MongoDB for now
                    if mongo_client_instance and mongo_client_instance.logs:
                        await mongo_client_instance.logs.insert_one(
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
            if (
                mongo_client_instance is not None
                and mongo_client_instance.logs is not None
            ):
                try:
                    await process_log_batch()
                except Exception as e:
                    logger.error(f"Error processing log batch: {e}")

            # Process pending leads
            try:
                await process_pending_leads()
            except Exception as e:
                logger.error(f"Error processing pending leads: {e}")

            # Check for expired processing locks and clear them
            if redis_client and REDIS_AVAILABLE:
                try:
                    # Get all keys matching the pattern
                    keys = await redis_client.keys("processing:*")
                    for key in keys:
                        # Check if older than 5 minutes (possible dead lock)
                        ttl = await redis_client.ttl(key)
                        if ttl < 0 or ttl < 30:  # No TTL or less than 30s left
                            # Clear lock
                            await redis_client.delete(key)
                            logger.info(f"Cleared potentially dead lock: {key}")
                except Exception as e:
                    logger.error(f"Error clearing expired locks: {e}")

        except Exception as e:
            logger.error(f"Error in background tasks: {e}")

        # Run every 10 seconds
        await asyncio.sleep(10)


class TelegramRunner:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.application = None

    async def start(self):
        try:
            self.application = Application.builder().token(self.bot_token).build()
            logger.info("Successfully initialized Telegram application")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram application: {e}")
            raise

    async def stop(self):
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
            logger.info("Successfully stopped Telegram application")

    async def run(self):
        try:
            await self.application.run_polling()
            logger.info("Successfully started Telegram bot polling")
        except Exception as e:
            logger.error(f"Error running Telegram bot: {e}")
            raise

    async def add_handlers(self, handlers):
        try:
            for handler in handlers:
                self.application.add_handler(handler)
            logger.info("Successfully added handlers to Telegram application")
        except Exception as e:
            logger.error(f"Error adding handlers to Telegram application: {e}")
            raise

    async def remove_handlers(self, handlers):
        try:
            for handler in handlers:
                self.application.remove_handler(handler)
            logger.info("Successfully removed handlers from Telegram application")
        except Exception as e:
            logger.error(f"Error removing handlers from Telegram application: {e}")
            raise

    async def update_handlers(self, handlers):
        try:
            await self.remove_handlers(handlers)
            await self.add_handlers(handlers)
            logger.info("Successfully updated handlers in Telegram application")
        except Exception as e:
            logger.error(f"Error updating handlers in Telegram application: {e}")
            raise
