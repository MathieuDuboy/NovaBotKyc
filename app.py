import base64
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
import unicodedata
import numpy as np
from fastapi import HTTPException, Request
from fastapi import Request, HTTPException
import asyncio
import json
import os
import threading
import time
import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import uvicorn
from fastapi import (BackgroundTasks, Body, FastAPI, HTTPException, Query,
                     Request, Response, status, Depends)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse, HTMLResponse, JSONResponse
from telegram import Update
from telegram.ext import (CallbackQueryHandler, CommandHandler, MessageHandler,
                          filters)
from starlette.middleware import Middleware
from middleware.endpoint_guard import EndpointGuardMiddleware

# Import config and service functions
import config
from config import (INTERLACE_ADDRESS, INTERLACE_DEV, INTERLACE_MODE,
                    INTERLACE_POOL_MAX, INTERLACE_POOL_THRESHOLD,
                    INTERLACE_PROD, MAX_MONGODB_POOL_SIZE,
                    MAX_REDIS_CONNECTIONS, NOVA_API_ACCESS_KEY,
                    NOVA_API_SECRET_KEY, NOVA_CONSUMPTION_FEE_T,
                    NOVA_DEPOSITS_CONFIG, TESTING_MODE, TESTING_URL)
from interlace.client import InterlaceClient
from interlace.resources.models import Balance
from nova_api.client import NovaClient
from services.mongo_service import MongoClientWrapper
from services.mysql_service import mysql_client
from services.redis_service import RedisClientWrapper
from services.sheets_service import initialize_sheets_service
from telegram_bot.handlers import (cancel_command, error_handler,
                                   handle_message, language_selection,
                                   send_all_command, send_command, start)
from telegram_bot.messaging import telegram_messaging
from telegram_bot.runner import (run_polling, setup_application,
                                 setup_menu_commands)
from utils.interlace_utils import InterlaceClient
from utils.logger import logger

# Add new imports for cryptographic verification
import hashlib
import hmac
import urllib.parse

# --- Static Files Setup ---
MINI_APP_ABS_PATH = config.MINI_APP_DIR
STATIC_PATH = os.path.join(MINI_APP_ABS_PATH, "static")
logger.info(f"Mini App absolute path: {MINI_APP_ABS_PATH}")
logger.info(f"Static files path: {STATIC_PATH}")
logger.info(f"Directory exists: {os.path.isdir(MINI_APP_ABS_PATH)}")
logger.info(f"Current working directory: {os.getcwd()}")


class DateTimeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


# Redis import - for high performance state management
REDIS_AVAILABLE = False
try:
    import redis.asyncio as redis

    from services.redis_service import RedisClientWrapper
    REDIS_AVAILABLE = True
except ImportError:
    logger.warning("Redis client not available. Install with: pip install redis")

# MongoDB imports with connection pooling
MONGODB_AVAILABLE = False
try:
    from bson.objectid import ObjectId
    from motor.motor_asyncio import AsyncIOMotorClient
    from pymongo.mongo_client import MongoClient
    MONGODB_AVAILABLE = True
except ImportError:
    logger.warning("MongoDB driver not found. Install with: pip install motor")


# --- Global variables for this process ---
# These will be initialized during startup
sheets_service_client = None
bot_task = None
mongo_client_instance = None
redis_client = None
nova_client = None

# Connection pool settings - adjust based on expected load
MAX_MONGODB_POOL_SIZE = config.MAX_MONGODB_POOL_SIZE
MAX_REDIS_CONNECTIONS = config.MAX_REDIS_CONNECTIONS
NOVA_API_ACCESS_KEY = config.NOVA_API_ACCESS_KEY
NOVA_API_SECRET_KEY = config.NOVA_API_SECRET_KEY
INTERLACE_POOL_THRESHOLD = config.INTERLACE_POOL_THRESHOLD
INTERLACE_POOL_MAX = config.INTERLACE_POOL_MAX
INTERLACE_ADDRESS = config.INTERLACE_ADDRESS
NOVA_DEPOSITS_CONFIG = config.NOVA_DEPOSITS_CONFIG
OPEN_CARD_INITIAL_AMOUNT = NOVA_DEPOSITS_CONFIG.get("open_card_initial_amount", 10)
# Load params.json to check if testing is enabled
TESTING_MODE = config.get("testing", False)

# In-memory user address counters (for demo; use Redis/DB in production)
user_address_counters = {}
user_address_lock = threading.Lock()

# Track active deposit timers in memory (for demo; use Redis/DB in production)
active_deposit_timers = {}

# --- Background Tasks ---


async def process_api_request_batch():
    """Process a batch of API requests from Redis queue."""
    if not redis_client or mongo_client_instance.api_requests_collection is None:
        return
    try:
        # Get up to 50 items from the queue
        pipe = await redis_client.pipeline()
        pipe.lrange("api_request_queue", 0, 49)
        pipe.ltrim("api_request_queue", 50, -1)
        results = await redis_client.execute_pipeline(pipe)
        items = results[0]
        if not items:
            return
        # Parse JSON and prepare for bulk insert
        docs = []
        for item in items:
            try:
                doc = json.loads(item)
                if isinstance(doc, dict):
                    docs.append(doc)
            except BaseException:
                continue
        # Bulk insert to MongoDB
        if docs:
            await mongo_client_instance.api_requests_collection.insert_many(docs)
    except Exception as e:
        logger.error(f"Error processing API request batch: {e}")


async def process_log_batch():
    """Process log batches in the background"""
    while True:
        try:
            # Process any pending logs
            await asyncio.sleep(1)  # Adjust sleep time based on needs
        except Exception as e:
            logger.error(f"Error in log batch processing: {e}")
            await asyncio.sleep(5)  # Back off on error


# --- FastAPI Lifespan Management ---


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for FastAPI application.
    Handles startup and shutdown events.
    """
    global sheets_service_client, bot_task, mongo_client_instance, redis_client, nova_client, REDIS_AVAILABLE, MONGODB_AVAILABLE

    try:
        # Initialize logger first
        logger.info("Starting application...")

        # Initialize Redis client if available
        if REDIS_AVAILABLE:
            try:
                redis_client = RedisClientWrapper()
                await redis_client.initialize()
                # Test the connection
                if not await redis_client.ping():
                    raise Exception("Redis ping failed")
                logger.info("Redis client initialized and connected successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Redis client: {e}")
                REDIS_AVAILABLE = False
                redis_client = None

        # Initialize MongoDB client if available
        if MONGODB_AVAILABLE:
            try:
                mongo_client_instance = MongoClientWrapper()
                await mongo_client_instance.initialize()
                logger.info("MongoDB client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MongoDB client: {e}")
                MONGODB_AVAILABLE = False
                mongo_client_instance = None

        # Start background tasks only if Redis is available
        background_tasks = []
        if REDIS_AVAILABLE and redis_client:
            background_tasks.extend([
                asyncio.create_task(process_api_request_batch()),
                asyncio.create_task(process_log_batch()),
                asyncio.create_task(deposit_timer_background_task()),
            ])

        # Initialize Nova client and WebSocket connection
        try:
            nova_client = NovaClient(
                access_key=NOVA_API_ACCESS_KEY,
                secret_key=NOVA_API_SECRET_KEY,
                mongo_client_instance=mongo_client_instance,
            )
            # Start WebSocket connection
            if not TESTING_MODE:  # Don't connect in testing mode
                await nova_client.connect_websocket()
                logger.info("Nova WebSocket connection established")
            logger.info("Nova client initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Nova client: {e}")
            nova_client = None

        # Initialize Telegram bot only in the main worker
        try:
            # Check if we're the main worker
            if True:
                # if os.environ.get('WORKER_ID') == '0':
                application = setup_application()
                if application:
                    if config.USE_WEBHOOK:
                        # Set up webhook
                        await application.bot.set_webhook(
                            url=config.WEBHOOK_URL + config.WEBHOOK_PATH,
                            allowed_updates=[
                                "message",
                                "callback_query",
                                "inline_query",
                                "chosen_inline_result",
                                "chat_member"
                            ],
                            drop_pending_updates=True,
                            secret_token=config.WEBHOOK_SECRET,
                            max_connections=40
                        )
                        logger.info("Telegram webhook configured successfully")
                    else:
                        # Initialize handlers for polling mode
                        admin_filter = filters.Chat(chat_id=config.ADMIN_CHAT_ID)

                        # Register handlers
                        application.add_handler(CommandHandler("start", start))
                        application.add_handler(
                            CommandHandler(
                                "send", send_command, filters=admin_filter)
                        )
                        application.add_handler(
                            CommandHandler(
                                "send_all", send_all_command, filters=admin_filter)
                        )
                        application.add_handler(
                            CommandHandler(
                                "cancel", cancel_command, filters=admin_filter)
                        )
                        application.add_handler(
                            CallbackQueryHandler(
                                language_selection, pattern="^lang_")
                        )
                        application.add_handler(
                            MessageHandler(
                                filters.TEXT & ~filters.COMMAND, handle_message)
                        )
                        application.add_error_handler(error_handler)

                        # Set up menu commands
                        asyncio.create_task(setup_menu_commands(application))

                        # Démarrage RÉEL du polling — manquait dans le code d'origine
                        # (sans ça, aucun update n'est récupéré -> /start muet).
                        await application.initialize()
                        await application.start()
                        await application.updater.start_polling(
                            drop_pending_updates=True,
                            allowed_updates=["message", "callback_query"],
                        )
                        app.state.bot_application = application
                        logger.info("Bot polling started successfully")
                else:
                    logger.error("Failed to initialize Telegram bot application")
            else:
                logger.info("Skipping bot initialization in worker process")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            bot_task = None

        # Initialize Google Sheets service
        try:
            sheets_service_client = initialize_sheets_service()
            logger.info("Google Sheets service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Google Sheets service: {e}")
            sheets_service_client = None

        logger.info("Application startup complete")
        yield

    except Exception as e:
        logger.critical(
            f"Critical error during application startup: {e}",
            exc_info=True)
        raise

    finally:
        # Cleanup
        # Cancel all background tasks
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)

        # Cancel bot task if it exists
        if bot_task:
            bot_task.cancel()
            try:
                await bot_task
            except asyncio.CancelledError:
                pass

        # Close Nova WebSocket connection
        if nova_client:
            try:
                await nova_client.disconnect_websocket()
                logger.info("Nova WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error closing Nova WebSocket connection: {e}")

        # Close Redis connection
        if redis_client and REDIS_AVAILABLE:
            try:
                await redis_client.close()
                logger.info("Redis connection closed successfully")
            except Exception as e:
                logger.error(f"Error closing Redis connection: {e}")

        # Close MongoDB connection
        if mongo_client_instance and MONGODB_AVAILABLE:
            try:
                await mongo_client_instance.close()
                logger.info("MongoDB connection closed successfully")
            except Exception as e:
                logger.error(f"Error closing MongoDB connection: {e}")

        logger.info("Application shutdown complete")


# --- FastAPI App Initialization ---
def verify_telegram_miniapp(request: Request):

    token = request.headers.get("x-telegram-miniapp-token")
    # TELEGRAM_MINIAPP_TOKEN should be defined in config
    expected_token = config.TELEGRAM_MINIAPP_TOKEN
    if token != expected_token:
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: Unauthorized miniapp request")


def verify_telegram_init_data(request: Request):
    """
    Verifies Telegram WebApp (Mini App) init_data.
    1) Grabs raw init_data from header or query param.
    2) Splits on '&' into segments.
    3) Extracts query_id, user, auth_date, hash and signature.
    4) Builds data_check_string = "<BOT_ID>:WebAppData\nauth_date=…\nquery_id=…\nuser=…"
       (where user=… is the URL-decoded JSON).
    5) Base64‐URL‐decode the signature (64 bytes).
    6) Load Telegram's Ed25519 public key from PUBLIC_KEY_HEX.
    7) Call public_key.verify(signature, data_check_string_bytes).
    8) If valid, URL-decode all fields and return them.
    """
    BOT_ID = config.BOT_ID
    PUBLIC_KEY_HEX = config.PUBLIC_KEY_HEX
    # STEP 1: get raw init_data
    init_data = (
        request.headers.get("X-Telegram-InitData")
        or request.query_params.get("tgInitData")
    )
    if not init_data:
        logger.warning("Missing Telegram init data header/param")
        raise HTTPException(status_code=403, detail="Missing Telegram init data")

    # logger.warning("Raw init_data: %r", init_data)

    # STEP 2: split on '&'
    raw_segments = [seg for seg in init_data.split("&") if "=" in seg]
    # logger.warning("Raw segments: %r", raw_segments)

    # STEP 3: extract required fields
    signature_b64url = None
    query_id_enc = None
    user_enc = None
    auth_date = None
    payload_hash = None

    for seg in raw_segments:
        k_raw, v_raw = seg.split("=", 1)
        key = urllib.parse.unquote_plus(k_raw)

        if key == "signature":
            signature_b64url = v_raw
        elif key == "query_id":
            query_id_enc = v_raw
        elif key == "user":
            user_enc = v_raw
        elif key == "auth_date":
            auth_date = v_raw
        elif key == "hash":
            payload_hash = v_raw

    # all four must be present, plus signature
    # if not (signature_b64url and query_id_enc and user_enc and auth_date and
    # payload_hash):
    if not (signature_b64url and user_enc and auth_date and payload_hash):
        # logger.warning(
        #     "Missing one of required fields; "
        #     "signature=%r, query_id=%r, user=%r, auth_date=%r, hash=%r",
        #     signature_b64url,
        #     user_enc,
        #     auth_date,
        #     payload_hash,
        # )
        raise HTTPException(status_code=403, detail="Missing required init_data fields")

    # logger.warning("Provided signature (base64url): %r", signature_b64url)

    # STEP 4: build data_check_string
    #   1) URL-decode the user JSON
    parsed = {}
    for seg in raw_segments:
        k_raw, v_raw = seg.split("=", 1)
        key = urllib.parse.unquote_plus(k_raw)
        val = urllib.parse.unquote_plus(v_raw)
        parsed[key] = val

    lines = []
    for key in sorted(parsed.keys()):
        if key not in ['hash', 'signature']:
            lines.append(f"{key}={parsed[key]}")
    data_check_string = f"{BOT_ID}:WebAppData\n" + "\n".join(lines)

    data_check_string = unicodedata.normalize('NFC', data_check_string)
    # logger.warning("data_check_string (ascii repr): %s", ascii(data_check_string))

    # STEP 5: base64‐URL‐decode the signature
    padding = "=" * ((4 - len(signature_b64url) % 4) % 4)
    try:
        signature_bytes = base64.urlsafe_b64decode(signature_b64url + padding)
    except Exception as e:
        logger.warning("Failed to base64-URL-decode signature: %r", e)
        raise HTTPException(status_code=403, detail="Invalid signature encoding")

    logger.warning("Decoded signature bytes (hex): %s", signature_bytes.hex())

    # STEP 6: load Ed25519 public key from PUBLIC_KEY_HEX
    try:
        pubkey_bytes = bytes.fromhex(PUBLIC_KEY_HEX)
        if len(pubkey_bytes) != 32:
            raise ValueError("Public key length is not 32 bytes")
        public_key = Ed25519PublicKey.from_public_bytes(pubkey_bytes)
    except Exception as e:
        logger.error("Failed to load Telegram WebApp public key: %r", e)
        raise HTTPException(status_code=500, detail="Server misconfiguration")

    logger.warning("Using Ed25519 public key (hex): %s", pubkey_bytes.hex())

    # STEP 7: verify Ed25519(signature, data_check_string_bytes)
    try:
        public_key.verify(signature_bytes, data_check_string.encode('utf-8'))
    except InvalidSignature:
        logger.warning("Ed25519 signature verification failed")
        raise HTTPException(status_code=403,
                            detail="Invalid Telegram init data signature")
    except Exception as e:
        logger.warning("Unexpected error during signature verification: %r", e)
        raise HTTPException(status_code=403,
                            detail="Invalid Telegram init data signature")

    logger.warning("Signature verified successfully! ")

    # STEP 8: check auth_date is recent (optional)
    auth_date = parsed.get("auth_date")
    try:
        ad = int(auth_date)
        now_ts = int(time.time())
        delta = now_ts - ad
        logger.warning("auth_date: %d, now: %d, delta: %d seconds", ad, now_ts, delta)
        if delta > 500:
            logger.warning("Telegram init data is outdated")
            raise HTTPException(
                status_code=403,
                detail="Telegram init data is outdated")
    except ValueError:
        logger.warning("Invalid auth_date (not integer): %r", auth_date)
        raise HTTPException(status_code=403, detail="Missing or invalid auth_date")

    # STEP 9: URL-decode all fields into a dict
    parsed = {}
    for seg in raw_segments:
        k_raw, v_raw = seg.split("=", 1)
        key = urllib.parse.unquote_plus(k_raw)
        val = urllib.parse.unquote_plus(v_raw)
        parsed[key] = val

    # In verify_telegram_init_data, add a new debug log after normalizing
    # data_check_string
    # logger.debug("data_check_string (hex): %s", data_check_string.encode('utf-8').hex())

    return parsed


# Update FastAPI app instantiation to include both dependencies globally
app = FastAPI(
    lifespan=lifespan,
    title="Nova API",
    description="API for Nova System",
    version="1.0.0",
    default_response_class=JSONResponse,
    docs_url=None,
    redoc_url=None,
    middleware=[Middleware(EndpointGuardMiddleware)]
)

# Add CORS middleware with specific origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Conditionally serve test UI if testing is enabled
if TESTING_MODE:
    app.mount(
        "/test_ui", StaticFiles(directory="miniapp_telegram/static/test_ui"), name="test_ui"
    )

    @app.get("/test-ui", response_class=HTMLResponse)
    async def serve_test_ui():
        """Serve the test UI for simulating events."""
        with open("miniapp_telegram/static/test_ui/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())


# --- Exception Handling ---


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc):
    logger.warning(
        f"HTTP Exception: {exc.status_code} for {request.url}. " f"Detail: {exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    logger.error(f"Unhandled Exception for {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"success": False, "message": "Internal Server Error"},
    )


# --- Rate Limiting Middleware ---
# Simple rate limiter using Redis
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if redis_client and REDIS_AVAILABLE:
        client_ip = request.client.host
        path = request.url.path
        key = f"ratelimit:{client_ip}:{path}"

        # Allow 50 requests per minute per IP per endpoint
        if await redis_client.exists(key):
            count = await redis_client.incr(key)
            if count > 50:
                return JSONResponse(
                    status_code=429,
                    content={"success": False, "message": "Rate limit exceeded"},
                )
        else:
            # Set key with expiration using set with ex parameter
            await redis_client.set(key, "1", ex=60)  # 60 seconds expiry

    response = await call_next(request)
    return response


# --- API Routes ---
# See the implementation at the end of this file


async def process_notification(request: Request, payload: dict, method: str):
    """Process notification from various API sources (Interlace, Google Sheets, etc.)

    Handles notifications from different sources based on payload structure:
    - Interlace: Contains id, businessType, data, sign fields
    - Google Sheets: Contains event_type='google_sheets_edit'
    - Generic API callbacks: Contains event_type field

    Args:
        request: The FastAPI request object
        payload: The parsed JSON payload
        method: HTTP method (GET/POST)

    Returns:
        JSONResponse: Appropriate response based on notification type
    """
    # Initialize required clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # Log request to MongoDB
    await mongo_client_instance.log_api_request(
        {
            "ip": request.client.host if request else request,
            "endpoint": "/api/callback",
            "method": method,
            "payload": payload,
            "user_agent": (
                request.headers.get("user-agent", "Unknown") if request else "Unknown"
            ),
            "timestamp": datetime.now(timezone.utc),
        }
    )

    try:
        # Determine notification type based on payload structure
        required_fields = ["id", "businessType", "data", "sign"]
        is_interlace = all(field in payload for field in required_fields)
        # is_google_sheets = payload.get("event_type") == "google_sheets_edit"
        is_generic_callback = "event_type" in payload

        if is_interlace:
            # Handle Interlace notification
            logger.info(
                f"Processing Interlace notification from {request.client.host if request else request}"
            )

            # Extract notification details
            notification_id = payload["id"]
            business_type = payload["businessType"]
            data = payload["data"]
            signature = payload["sign"]

            # Save to MongoDB for record keeping (if available)
            if MONGODB_AVAILABLE:
                try:
                    # Store with timestamp for future analysis
                    await mongo_client_instance.interlace_notifications.insert_one(
                        {
                            "notification_id": notification_id,
                            "business_type": business_type,
                            "data": data,
                            "signature": signature,
                            "received_at": datetime.now(timezone.utc),
                            "ip": request.client.host if request else request,
                            "processed": False,
                        }
                    )
                except Exception as mongo_err:
                    logger.error(
                        f"Error storing Interlace notification in MongoDB: {mongo_err}"
                    )

            # Check for duplicate notifications (idempotency)
            if redis_client and REDIS_AVAILABLE:
                # Use a Redis set to track processed notification IDs
                key = f"processed_notification:{notification_id}"
                already_processed = await redis_client.exists(key)

                if already_processed:
                    logger.info(
                        f"Duplicate notification received with ID: "
                        f"{notification_id}"
                    )
                    # Return success for duplicates as per Interlace docs
                    return JSONResponse(content={"received": True})

                # Mark this notification as processed (expire after 24 hours)
                await redis_client.set(key, "1", ex=86400)

            # Process notification based on businessType
            logger.info(f"Processing Interlace notification of type: {business_type}")

            # Handle different notification types based on businessType
            # 1. Account Notifications
            if business_type == "AccountRegistered":
                # Handle account registration
                logger.info(f"Account registered: {data.get('id', 'unknown')}")
                # TODO: Implement account registration handling

            elif business_type == "KYC":
                # Handle KYC notification
                logger.info(f"KYC update for account: {data.get('id', 'unknown')}")
                # TODO: Implement KYC handling

            elif business_type == "FaceAuthentication":
                # Handle face authentication
                logger.info(
                    f"Face authentication for account: "
                    f"{data.get('accountId', 'unknown')}"
                )
                # TODO: Implement face authentication handling

            # 2. Infinity Card Notifications
            elif business_type == "CreateCard":
                card_id = data.get("id", "")
                logger.info(f"Processing CreateCard notification with data: {data}")

                # Validate card ID
                if not card_id or not isinstance(card_id, str) or card_id.strip() == "":
                    logger.error(
                        f"Invalid card ID in CreateCard notification: {card_id}"
                    )
                    # Store the invalid notification for debugging
                    if MONGODB_AVAILABLE:
                        try:
                            await mongo_client_instance.invalid_notifications.insert_one(
                                {
                                    "type": "CreateCard",
                                    "data": data,
                                    "received_at": datetime.now(timezone.utc),
                                    "error": "Empty or invalid card ID",
                                }
                            )
                        except Exception as mongo_err:
                            logger.error(
                                f"Error storing invalid notification: {mongo_err}"
                            )
                    return JSONResponse(content={"received": True})

                try:
                    # Verify card exists before attempting transfer
                    card_details = (
                        interlace_client.infinity_card.get_infinity_card_details(
                            card_id
                        )
                    )
                    if not card_details:
                        logger.error(f"Card {card_id} not found after creation")
                        # Store the missing card notification
                        if MONGODB_AVAILABLE:
                            try:

                                await mongo_client_instance.invalid_notifications.insert_one(
                                    {
                                        "type": "CreateCard",
                                        "card_id": card_id,
                                        "data": data,
                                        "received_at": datetime.now(timezone.utc),
                                        "error": "Card not found after creation",
                                    }
                                )
                            except Exception as mongo_err:
                                logger.error(
                                    f"Error storing missing card notification: {mongo_err}"
                                )
                        return JSONResponse(content={"received": True})

                    done_creation = mongo_client_instance.interlace_transactions.find_one(
                        {"data.cardId": card_id,
                         "data.clientTransactionId": {"$exists": True,
                                                      "$regex": "Create",
                                                      "$options": "i"
                                                      },
                         "data.type": "TransferOut"}
                    )
                    if done_creation:
                        logger.info(
                            f"Card {card_id} already created and transfered out")
                        return JSONResponse(content={"received": True})
                    else:
                        logger.info(f"Card {card_id} didn't transfered out yet")

                    # Attempt transfer with retry logic
                    max_retries = 3
                    retry_delay = 2

                    for attempt in range(max_retries):
                        try:
                            transfer_response = interlace_client.infinity_card.infinity_card_transfer_out(
                                {"cardId": card_id, "cost": OPEN_CARD_INITIAL_AMOUNT,
                                    "clientTransactionId": f"CreateCard_inside_webhook_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}"}
                            )
                            logger.info(
                                f"Successfully transferred out card creation fee: {transfer_response}"
                            )
                            break
                        except Exception as transfer_err:
                            if attempt < max_retries - 1:
                                logger.warning(
                                    f"Transfer attempt {attempt + 1} failed, retrying in {retry_delay}s: {transfer_err}"
                                )
                                await asyncio.sleep(retry_delay)
                            else:
                                logger.error(
                                    f"All transfer attempts failed for card {card_id}: {transfer_err}"
                                )
                                # Store the failed transfer notification
                                if MONGODB_AVAILABLE:
                                    try:
                                        await mongo_client_instance.invalid_notifications.insert_one(
                                            {
                                                "type": "CreateCard",
                                                "card_id": card_id,
                                                "data": data,
                                                "received_at": datetime.now(timezone.utc),
                                                "error": f"Transfer failed after {max_retries} attempts: {transfer_err}",
                                            }
                                        )
                                    except Exception as mongo_err:
                                        logger.error(
                                            f"Error storing failed transfer notification: {mongo_err}"
                                        )
                                return JSONResponse(content={"received": True})

                except Exception as e:
                    logger.error(f"Error processing card creation: {e}")
                    # Store the error notification
                    if MONGODB_AVAILABLE:
                        try:
                            await mongo_client_instance.invalid_notifications.insert_one(
                                {
                                    "type": "CreateCard",
                                    "card_id": card_id,
                                    "data": data,
                                    "received_at": datetime.now(timezone.utc),
                                    "error": str(e),
                                }
                            )
                        except Exception as mongo_err:
                            logger.error(
                                f"Error storing error notification: {mongo_err}"
                            )
                    return JSONResponse(content={"received": True})

            elif business_type == "FrozenCard":
                logger.info(f"Card frozen: {data.get('id', 'unknown')}")
                # TODO: Implement card freezing handling

            elif business_type == "UnfrozenCard":
                logger.info(f"Card unfrozen: {data.get('id', 'unknown')}")
                # TODO: Implement card unfreezing handling

            elif business_type == "DeleteCard":
                logger.info(f"Card deleted: {data.get('id', 'unknown')}")
                # TODO: Implement card deletion handling

            elif business_type == "CardStateChange":
                logger.info(
                    f"Card state changed for: {data.get('id', 'unknown')} "
                    f"to {data.get('status', 'unknown')}"
                )
                # TODO: Implement card state change handling

            elif business_type == "CardTransaction":
                logger.info(f"Card transaction: {data}")
                try:
                    # Save raw callback for audit
                    await mongo_client_instance.interlace_transactions.insert_one(
                        {**payload, "received_at": datetime.now(timezone.utc)}
                    )

                    # Extract transaction details
                    transaction_details = extract_transaction_details(data)
                    # Get latest combined doc for this transaction
                    latest_combined = (
                        await mongo_client_instance.combined_transactions.find_one(
                            {
                                "tid": transaction_details["tid"],
                                "amount": {"$gt": 0}
                            },
                            sort=[("timestamp", -1)],
                        )
                    )
                    # Handle different transaction types
                    if transaction_details["transaction_type"] == "TransferIn":
                        # For TransferIn, update both internal and user-facing status
                        # Check if this is a Nova fee reversal
                        if "NovafeeReversal" in transaction_details.get(
                                "clientTransactionId", ""):
                            logger.info(
                                f"Processing Nova fee reversal for transaction {transaction_details['transaction_id']}"
                            )
                            return

                        await handle_transfer_in(transaction_details)
                        # Check quantum balance after user deposit
                        await check_and_handle_quantum_balance(
                            interlace_client, nova_client
                        )

                    elif transaction_details["transaction_type"] == "TransferOut":
                        logger.info(
                            f"Card transaction TransferOut: {transaction_details}")
                        return
                    elif transaction_details["amount"] > 0:

                        await handle_main_transaction(
                            transaction_details, latest_combined
                        )
                    elif transaction_details["is_fee_callback"]:
                        await handle_fee_callback(transaction_details, latest_combined)

                except Exception as e:
                    logger.error(f"Error processing card transaction: {e}")

            elif business_type == "FrozenAmount":
                logger.info(f"Amount frozen on card: {data.get('id', 'unknown')}")
                # TODO: Implement amount freezing handling

            elif business_type == "UnfrozenAmount":
                logger.info(f"Amount unfrozen on card: {data.get('id', 'unknown')}")
                # TODO: Implement amount unfreezing handling

            elif business_type == "BudgetTransaction":
                logger.info(f"Budget transaction: {data.get('id', 'unknown')}")
                # TODO: Implement budget transaction handling

            elif business_type == "Card3dsOtp":
                logger.info(f"Card 3DS OTP: {data}")
                try:
                    # Get the card number from the notification
                    card_id = data.get("cardId", "")
                    card_details = (
                        interlace_client.infinity_card.get_infinity_card_details(
                            card_id
                        )
                    )
                    card_number = card_details.card_no
                    otp = data.get("otp", "")
                    merchant = data.get("detail", "Unknown Merchant")
                    amount = data.get("amount", 0)
                    currency = data.get("currency", "USD")

                    if not card_number or not otp:
                        logger.error("Missing card number or OTP in notification")
                        return JSONResponse(content={"received": True})

                    user_result = await mysql_client.get_user_from_db(
                        card_number=card_number
                    )
                    if user_result.get("success"):
                        user_result = user_result.get("user", {})
                        try:
                            user_id = user_result.get("userId")
                        except Exception as e:
                            user_id = user_result.get("USER_ID")

                    if not user_id:
                        logger.error("User found but no Telegram ID available")
                        return JSONResponse(content={"received": True})

                    # Send 3DS OTP message using TelegramMessaging service
                    await telegram_messaging.send_3ds_otp(
                        user_id=user_id,
                        otp=otp,
                        amount=amount,
                        currency=currency,
                        merchant=merchant,
                    )

                except Exception as e:
                    logger.error(f"Error processing 3DS OTP notification: {e}")

            elif business_type == "ThreeDomainSecureForwarding":
                logger.info(f"3DS forwarding: {data}")

                card_id = data.get("cardId")
                account_id = data.get("accountId")
                action_id = data.get("actionId")
                currency = data.get("currency")
                amount = data.get("amount")
                card_number = data.get("cardNumber")
                detail = data.get("detail")
                timestamp = data.get("timestamp")
                expiration_time = data.get("expirationTime")
                url = data.get("url")
                card_details = (
                    interlace_client.infinity_card.get_infinity_card_details(
                        card_id
                    )
                )
                card_number = card_details.card_no

                if not card_number:
                    logger.error("Missing card number")
                    return JSONResponse(content={"received": True})

                user_result = await mysql_client.get_user_from_db(
                    card_number=card_number
                )

                if user_result.get("success"):
                    user_result = user_result.get("user", {})
                    try:
                        user_id = user_result.get("userId")
                    except Exception as e:
                        user_id = user_result.get("USER_ID")
                else:
                    logger.error(f"User not found for card {card_number}")
                    return JSONResponse(content={"received": True})

                if not card_id or not account_id or not action_id or not currency or not amount or not card_number or not detail or not timestamp or not expiration_time or not url:
                    logger.error(
                        "Missing required fields in 3DS forwarding notification")
                    return JSONResponse(content={"received": True})

                telegram_messaging.send_message(
                    user_id=user_id,
                    message=f"3DS forwarding: {card_number} - {detail} - {amount} - {currency} - {timestamp} - {expiration_time} - {url}"
                )
                # TODO: Implement 3DS forwarding handling

            elif business_type == "Overspend":
                logger.info(f"Card overspend: {data.get('id', 'unknown')}")
                # TODO: Implement overspend handling

            elif business_type == "CardBinStatus":
                logger.info(f"Card BIN status: {data.get('id', 'unknown')}")
                # TODO: Implement BIN status handling

            elif business_type == "CardHolder":
                logger.info(f"Card holder update: {data.get('id', 'unknown')}")
                # TODO: Implement card holder update handling

            # 3. Business Account Notifications
            elif business_type == "CreateGlobalAccount":
                logger.info(f"Global account created: {data.get('id', 'unknown')}")
                # TODO: Implement global account creation handling

            elif business_type == "GlobalAccountTransaction":
                logger.info(f"Global account transaction: {data.get('id', 'unknown')}")
                # TODO: Implement global account transaction handling

            # 4. Crypto Connect Notifications
            elif business_type == "CryptoConnectWallet":
                logger.info(f"Crypto wallet connected: {data.get('id', 'unknown')}")
                # TODO: Implement crypto wallet connection handling

            elif business_type == "AssetsDeposit":
                logger.info(f"Assets deposited: {data.get('id', 'unknown')}")
                try:
                    # Extract deposit details
                    deposit_amount = float(data.get("amount", 0))
                    deposit_time = data.get("createTime")

                    # 3. Transfer the converted USD to quantum account
                    transfer_response = (
                        interlace_client.funding.create_transfer(
                            {
                                "source": {
                                    "type": "crypto_assets",
                                    "currency": "USDT",
                                },
                                "destination": {
                                    "type": "quantum_account",
                                    "currency": "USD",
                                },
                                "amount": str(deposit_amount),
                            }
                        )
                    )

                    if not transfer_response:
                        raise Exception("Failed to transfer to quantum account")

                    pool_refill = await mongo_client_instance.pool_refills.find_one(
                        {"status": "Processing", "amount": deposit_amount}
                    )

                    if pool_refill:
                        # This is a pool refill case
                        logger.info(f"Processing pool refill deposit: {deposit_amount}")

                        try:

                            # Update pool refill status
                            await mongo_client_instance.pool_refills.update_one(
                                {"_id": pool_refill["_id"]},
                                {
                                    "$set": {
                                        "status": "Done",
                                        "completed_at": datetime.now(timezone.utc),
                                        "conversion_trade_id": trade_response["id"],
                                        "transfer_id": transfer_response["id"],
                                    }
                                },
                            )

                            logger.info(
                                f"Successfully processed pool refill: {deposit_amount} USDT -> USD -> Quantum"
                            )

                        except Exception as e:
                            logger.error(f"Error processing pool refill: {e}")
                            # Update pool refill status to failed
                            await mongo_client_instance.pool_refills.update_one(
                                {"_id": pool_refill["_id"]},
                                {
                                    "$set": {
                                        "status": "Failed",
                                        "error": str(e),
                                        "failed_at": datetime.now(timezone.utc),
                                    }
                                },
                            )
                            return JSONResponse(content={"received": True})

                    else:
                        # This is a user deposit case
                        # Find matching combined_transaction document
                        matching_deposit = await mongo_client_instance.combined_transactions.find_one(
                            {
                                "requires_withdrawal": True,
                                "withdrawal_status": "Pending",
                                # Convert back to original amount
                                "withdrawal_amount": deposit_amount
                            }
                        )

                        if not matching_deposit:
                            logger.info(
                                f"No matching deposit found for AssetsDeposit amount {deposit_amount}"
                            )
                            return JSONResponse(content={"received": True})

                        # Update deposit status
                        await mongo_client_instance.combined_transactions.update_one(
                            {"_id": matching_deposit["_id"]},
                            {
                                "$set": {
                                    "withdrawal_status": "Completed",
                                    "quantum_deposit_time": deposit_time,
                                    "internal_status": "Pending",
                                    "status": "Processing",
                                }
                            },
                        )

                        # Transfer from quantum account to card

                        try:
                            transfer_payload = {
                                "cardId": matching_deposit["cardId"],
                                "cost": round(float(matching_deposit["final_amount"]), 2),
                                "clientTransactionId": f"AssetsDeposit_{matching_deposit['_id']}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                            }
                            transfer_response = interlace_client.infinity_card.infinity_card_transfer_in(
                                transfer_payload
                            )
                            logger.info(
                                f"Transfer in response for card_number {matching_deposit['card_number']}, "
                                f"user {matching_deposit['user_id']}, amount {matching_deposit['final_amount']}: "
                                f"{transfer_response}"
                            )
                            # Update combined doc with transfer status
                            await mongo_client_instance.combined_transactions.update_one(
                                {"_id": matching_deposit["_id"]},
                                {
                                    "$set": {
                                        "quantum_transfer_status": "Completed",
                                        "internal_status": "Done",
                                        "status": "Processing",  # Will be updated to Completed by CardTransaction callback
                                    }
                                },
                            )
                        except Exception as e:
                            logger.error(f"Error transferring to card: {e}")
                            await mongo_client_instance.combined_transactions.update_one(
                                {"_id": matching_deposit["_id"]},
                                {
                                    "$set": {
                                        "quantum_transfer_status": "Failed",
                                        "internal_status": "Failed",
                                        "status": "Failed",
                                    }
                                },
                            )

                except Exception as e:
                    logger.error(f"Error processing AssetsDeposit notification: {e}")

            elif business_type == "AssetsWithdrawal":
                logger.info(f"Assets withdrawn: {data.get('id', 'unknown')}")
                # TODO: Implement assets withdrawal handling

            elif business_type == "Payment":
                logger.info(f"Payment: {data.get('id', 'unknown')}")
                # TODO: Implement payment handling

            # 5. Acquiring Notifications
            elif business_type.startswith("Acquiring"):
                logger.info(f"Acquiring order: {data.get('id', 'unknown')}")
                # TODO: Implement acquiring order handling

            else:
                # Handle unknown notification type
                logger.warning(f"Unknown Interlace notification type: {business_type}")

            # Mark as processed in MongoDB
            if MONGODB_AVAILABLE:
                try:
                    await mongo_client_instance.interlace_notifications.update_one(
                        {"notification_id": notification_id},
                        {"$set": {"processed": True}},
                    )
                except Exception as mongo_err:
                    logger.error(
                        f"Error updating Interlace notification in MongoDB: {mongo_err}"
                    )

            # Publish notification to Redis for other services to consume
            if redis_client and REDIS_AVAILABLE:
                channel = f"interlace:{business_type.lower()}"
                await redis_client.publish(
                    channel,
                    json.dumps(
                        {
                            "id": notification_id,
                            "business_type": business_type,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "data": data,
                        }
                    ),
                )

            # Return success response as required by Interlace
            return JSONResponse(content={"received": True})

        elif is_generic_callback:
            # Handle generic callback with event_type
            event_type = payload["event_type"]
            logger.debug(f"Received generic callback event type: {event_type}")

            # Save to MongoDB for record keeping (if available)
            if MONGODB_AVAILABLE:
                try:
                    await mongo_client_instance.api_callbacks.insert_one(
                        {
                            "event_type": event_type,
                            "payload": payload,
                            "received_at": datetime.now(timezone.utc),
                            "ip": request.client.host if request else request,
                        }
                    )
                except Exception as mongo_err:
                    logger.error(f"Error storing callback in MongoDB: {mongo_err}")

            # Publish to Redis if available
            if redis_client and REDIS_AVAILABLE:
                await redis_client.publish(
                    "callbacks",
                    json.dumps(
                        {
                            "event_type": event_type,
                            "received_at": datetime.now(timezone.utc).isoformat(),
                            "payload": payload,
                        }
                    ),
                )

            return JSONResponse(
                status_code=202,
                content={"status": "processed", "event_type": event_type},
            )

        else:
            # Unknown payload format
            logger.warning(f"Unknown callback format received: {payload}")
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Unknown callback format"},
            )

    except Exception as e:
        logger.error(f"Callback processing failed: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Callback processing error: {str(e)}"
        )


@app.post("/api/callback_v1_legacy")  # ancien récepteur Interlace v1 (désactivé, migration v3)
async def handle_api_callback_post(request: Request):
    """API endpoint to handle POST callbacks with JSON data from various sources."""
    client_ip = request.client.host
    logger.info(f"POST /api/callback received from {client_ip}")
    logger.debug(f"Request headers: {dict(request.headers)}")

    try:
        # Read and parse the request body once
        try:
            # Set a timeout for reading the request body
            body = await asyncio.wait_for(request.body(), timeout=30.0)
            if not body:
                logger.warning(f"Empty request body received from {client_ip}")
                return JSONResponse(
                    status_code=400,
                    content={"received": False, "error": "Empty request body"},
                )

            # Parse the JSON data
            try:
                data = json.loads(body)
                logger.debug(f"Received callback data from {client_ip}: {data}")
            except json.JSONDecodeError as json_err:
                logger.error(
                    f"Invalid JSON in callback notification from {client_ip}: {json_err}"
                )
                return JSONResponse(
                    status_code=400,
                    content={"received": False, "error": "Invalid JSON format"},
                )

            # Use the shared notification processing logic
            return await process_notification(request, data, "POST")

        except asyncio.TimeoutError:
            logger.warning(f"Timeout while reading request body from {client_ip}")
            return JSONResponse(
                status_code=408,  # Request Timeout
                content={"received": False, "error": "Request timeout"},
            )
        except ClientDisconnect:
            logger.warning(
                f"Client {client_ip} disconnected while reading request body"
            )
            # Log additional context about the disconnection
            logger.debug(
                f"Request headers at time of disconnection: {dict(request.headers)}"
            )
            logger.debug(
                f"Content-Length header: {request.headers.get('content-length', 'not set')}"
            )

            # Check if we have a content-length header
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    # Try to read the body in chunks to handle disconnections gracefully
                    body_chunks = []
                    total_size = 0
                    chunk_size = 8192  # 8KB chunks

                    while total_size < int(content_length):
                        try:
                            # Use request.stream() directly instead of asyncio.wait_for
                            async for chunk in request.stream():
                                if not chunk:
                                    break
                                body_chunks.append(chunk)
                                total_size += len(chunk)
                                if total_size >= int(content_length):
                                    break
                        except ClientDisconnect:
                            break

                    if body_chunks:
                        # Try to process the partial data we received
                        try:
                            body = b"".join(body_chunks)
                            data = json.loads(body)
                            logger.info(
                                f"Successfully processed partial data from disconnected client {client_ip}"
                            )
                            return await process_notification(request, data, "POST")
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Could not parse partial data from disconnected client {client_ip}"
                            )
                            return JSONResponse(
                                status_code=499,  # Client Closed Request
                                content={
                                    "received": False,
                                    "error": "Client disconnected",
                                },
                            )
                except Exception as e:
                    logger.error(
                        f"Error reading request body from {client_ip}: {e}",
                        exc_info=True,
                    )
                    return JSONResponse(
                        status_code=500,
                        content={
                            "received": False,
                            "error": "Internal server error while reading request",
                        },
                    )
            else:
                # No content-length header, can't attempt partial read
                return JSONResponse(
                    status_code=499,
                    content={"received": False, "error": "Client disconnected"},
                )
    except Exception as e:
        logger.error(
            f"Error processing callback notification from {client_ip}: {e}",
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"received": False, "error": "Internal server error"},
        )


# --- Static Files Setup ---
if os.path.isdir(MINI_APP_ABS_PATH):
    logger.info(f"Mounting static files from: {STATIC_PATH} under /static")
    app.mount("/static", StaticFiles(directory=STATIC_PATH, html=False), name="static")

    # Mount ad page static files
    app.mount(
        "/ad_page",
        StaticFiles(
            directory="miniapp_telegram/static/ad_page",
            html=False),  # Allow serving of all file types
        name="ad_page")

    # Mount ad page static files
    app.mount(
        "/ad_page_2",
        StaticFiles(
            directory="miniapp_telegram/static/ad_page_2",
            html=False),  # Allow serving of all file types
        name="ad_page_2")
    # Serve favicon.ico at root to prevent 404 errors

    @app.get("/favicon.ico", response_class=FileResponse)
    async def get_favicon():
        """Serve favicon.ico from static files"""
        favicon_path = os.path.join(STATIC_PATH, "images/favicons/favicon.ico")
        if os.path.exists(favicon_path):
            return FileResponse(favicon_path)
        raise HTTPException(status_code=404, detail="Favicon not found")

    @app.get("/", response_class=FileResponse)
    async def serve_index_frontend(request: Request):
        """Serves the main index.html file for the root path."""
        index_path = os.path.join(MINI_APP_ABS_PATH, "index.html")

        # Log access to MongoDB
        await mongo_client_instance.log_api_request(
            {
                "ip": request.client.host,
                "endpoint": "/",
                "method": "GET",
                "user_agent": request.headers.get("user-agent", "Unknown"),
            }
        )

        if os.path.exists(index_path):
            logger.debug("Serving index.html for path '/'")
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            # Inject secure token into the HTML
            token_script = f'<script>window.TELEGRAM_MINIAPP_TOKEN = "{config.TELEGRAM_MINIAPP_TOKEN}";</script>'
            if "<head>" in html_content:
                html_content = html_content.replace("<head>", "<head>" + token_script)
            else:
                html_content = token_script + html_content
            return HTMLResponse(content=html_content)
        else:
            logger.error(f"index.html not found at {index_path} for root path")
            raise HTTPException(status_code=404, detail="Index file not found")

    @app.get("/ad", response_class=HTMLResponse)
    async def serve_ad_page():
        """Serve the ad page."""
        with open("miniapp_telegram/static/ad_page/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/ad2", response_class=HTMLResponse)
    async def serve_ad_page_2():
        """Serve the ad page."""
        with open("miniapp_telegram/static/ad_page_2/index.html", "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    @app.get("/")
    async def serve_no_index():
        """Serve a message when no index file is found."""
        return JSONResponse(
            content={"success": False, "message": "Not Found"},
            status_code=404
        )

else:
    logger.warning(
        f"Mini App directory not found ({MINI_APP_ABS_PATH}). "
        f"Static file serving disabled."
    )

    @app.get("/")
    async def serve_no_index():
        """Handles the root path when the Mini App directory is missing."""
        logger.warning("Root path requested but Mini App directory not found.")
        raise HTTPException(status_code=404, detail="Mini App not found")


# --- MongoDB utility functions ---
async def log_api_request(request_data):
    """Log API request to MongoDB with batching for high volume."""
    if not MONGODB_AVAILABLE or mongo_client_instance.api_requests_collection is None:
        return
    try:
        # Convert datetime to ISO format string for JSON serialization
        request_data["timestamp"] = datetime.now().isoformat()
        # For extremely high volume, consider batching with Redis
        if redis_client and REDIS_AVAILABLE:
            # Push to Redis list for batched processing
            await redis_client.lpush("api_request_queue", json.dumps(request_data))
            # If queue is long enough, process a batch
            # This reduces MongoDB write operations
            queue_len = await redis_client.llen("api_request_queue")
            if queue_len >= 50:  # Process in batches of 50
                await process_api_request_batch()
        else:
            # Direct MongoDB insert if Redis not available
            await mongo_client_instance.api_requests_collection.insert_one(request_data)
    except Exception as e:
        logger.error(f"Error logging API request: {e}")


# --- Route handlers ---
@app.get("/miniapp", response_class=HTMLResponse)
async def get_miniapp(request: Request):
    """Serve the miniapp HTML page"""
    try:
        index_path = os.path.join(MINI_APP_ABS_PATH, "index.html")
        with open(index_path, "r", encoding="utf-8") as f:
            html_content = f.read()

        # Log miniapp access
        await mongo_client_instance.log_api_request(
            {
                "ip": request.client.host,
                "user_agent": request.headers.get("user-agent", "Unknown"),
                "endpoint": "/miniapp",
                "method": "GET",
            }
        )

        return HTMLResponse(content=html_content)
    except Exception as e:
        logger.error(f"Error serving miniapp: {e}")
        raise HTTPException(status_code=500, detail="Error serving Mini App")


# Add a health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    health_status = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "mongodb": "connected" if mongo_client_instance else "disconnected",
            "redis": "connected" if redis_client else "disconnected",
            "sheets": "connected" if sheets_service_client else "disconnected",
        },
    }
    return health_status


# ── Webhook Interlace v3 (KYC / cardholder / card) — Notification Address ──────
# Enregistré au dashboard Interlace sur .../api/callback (convention historique).
@app.post("/api/callback")
async def interlace_webhook(request: Request, background_tasks: BackgroundTasks):
    """Notifications Interlace v3 : vérif signature HMAC (si en-tête présent),
    réponse <5s, dispatch en tâche de fond, idempotent."""
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except Exception:
        return JSONResponse({"received": False, "error": "invalid json"}, status_code=400)
    resource = payload.get("resource", "")
    signature = request.headers.get("Signature") or request.headers.get("signature") or ""
    secret = getattr(config, "INTERLACE_WEBHOOK_SECRET", None)
    # Vérif seulement si Interlace envoie une Signature (pas de webhook_secret
    # dédié côté dashboard -> on utilise le client_secret en repli).
    if signature and secret and "<A_REMPLIR" not in str(secret):
        try:
            from interlace_v3 import InterlaceV3
            if not InterlaceV3.verify_webhook_signature(resource, signature, secret):
                logger.warning("[interlace-webhook] signature invalide — rejet")
                return JSONResponse({"received": False, "error": "bad signature"},
                                    status_code=401)
        except Exception as e:
            logger.error(f"[interlace-webhook] erreur vérif signature: {e}")
    elif not signature:
        logger.info("[interlace-webhook] pas d'en-tête Signature — vérif ignorée")
    event = payload.get("eventType")
    event_id = payload.get("id")
    logger.info(f"[interlace-webhook] event={event} id={event_id}")
    background_tasks.add_task(_dispatch_interlace_webhook, event, resource, event_id)
    return {"received": True}


async def _dispatch_interlace_webhook(event, resource, event_id):
    # idempotence best-effort (Redis 24h) ; la garde data-level (carte déjà créée)
    # reste la vraie sécurité anti-double-création.
    try:
        if redis_client and event_id:
            key = f"il:wh:{event_id}"
            if await redis_client.get(key):
                logger.info(f"[interlace-webhook] doublon ignoré id={event_id}")
                return
            await redis_client.set(key, "1", ex=86400)
    except Exception:
        pass
    try:
        data = json.loads(resource) if isinstance(resource, str) else (resource or {})
    except Exception:
        data = {}
    kyc = data.get("kyc") if isinstance(data.get("kyc"), dict) else {}
    # MoR : le KYC est porté par le CARDHOLDER -> on route par cardholder_id.
    cardholder_id = (data.get("cardholderId") or data.get("cardHolderId")
                     or kyc.get("cardholderId") or data.get("id"))
    status = str(data.get("status") or kyc.get("status") or "").upper()
    try:
        from services.interlace_kyc import (complete_after_kyc_passed,
                                            handle_kyc_rejected)
        # Statut KYC porté soit par KYC.UPDATED, soit par CARDHOLDER.UPDATED.
        if event in ("KYC.UPDATED", "KYC.UPDATE", "CARDHOLDER.UPDATED"):
            if status in ("PASSED", "APPROVED", "SUCCESS"):
                await complete_after_kyc_passed(
                    cardholder_id, case_id=data.get("caseId") or kyc.get("caseId"))
            elif status in ("REJECTED", "FAILED", "DECLINED"):
                await handle_kyc_rejected(
                    cardholder_id, reason=data.get("reason") or data.get("rejectReason"))
            else:
                logger.info(f"[interlace-webhook] {event} statut={status} cardholder={cardholder_id}")
        elif event in ("CARD.CREATED", "CARD.UPDATED", "CARDHOLDER.CREATED"):
            logger.info(f"[interlace-webhook] {event}: {data}")
        else:
            logger.info(f"[interlace-webhook] event non géré: {event}")
    except Exception as e:
        logger.error(f"[interlace-webhook] dispatch {event} échec: {e}")


# ── Formulaire KYC mini app (collecte infos + pièce + selfie) ──────────────────
@app.get("/kyc", response_class=HTMLResponse)
async def kyc_form_page():
    """Sert le formulaire KYC ouvert par le bouton web_app du bot."""
    path = os.path.join(MINI_APP_ABS_PATH, "kyc.html")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return HTMLResponse(content=fh.read())
    raise HTTPException(status_code=404, detail="KYC form not found")


@app.post("/api/kyc_submit")
async def kyc_submit(request: Request):
    """Réception du formulaire KYC (multipart : champs + pièce + selfie) ->
    orchestration Interlace v3 (register -> upload -> submit_kyc)."""
    form = await request.form()
    try:
        user_id = int(form.get("uid"))
    except (TypeError, ValueError):
        return JSONResponse({"success": False, "message": "uid manquant/invalide"},
                            status_code=400)

    profile = {
        "firstName": (form.get("firstName") or "").strip(),
        "lastName": (form.get("lastName") or "").strip(),
        "email": (form.get("email") or "").strip(),
        "dateOfBirth": form.get("dateOfBirth") or "",
        "gender": form.get("gender") or "",
        "nationality": (form.get("nationality") or "").upper(),
        "nationalId": form.get("nationalId") or "",
        "idType": form.get("idType") or "",
        "issueDate": form.get("issueDate") or "",
        "expiryDate": form.get("expiryDate") or "",
        "phoneNumber": form.get("phoneNumber") or "",
        "phoneCountryCode": form.get("phoneCountryCode") or "",
        "address": {
            "line1": form.get("addr_line1") or "",
            "line2": form.get("addr_line2") or "",
            "city": form.get("addr_city") or "",
            "state": form.get("addr_state") or "",
            "country": (form.get("addr_country") or "").upper(),
            "postalCode": form.get("addr_postal") or "",
        },
        "bin": None,
    }

    async def _read(field):
        f = form.get(field)
        if f is None or not hasattr(f, "read"):
            return None
        content = await f.read()
        if not content:
            return None
        return (getattr(f, "filename", field) or field, content,
                getattr(f, "content_type", None) or "image/jpeg")

    id_front = await _read("idFront")
    selfie = await _read("selfie")
    id_back = await _read("idBack")
    if not id_front or not selfie:
        return JSONResponse({"success": False, "message": "Pièce (recto) et selfie requis"},
                            status_code=400)

    try:
        from services.interlace_kyc import submit_enrollment_kyc
        result = await submit_enrollment_kyc(user_id, profile, id_front, selfie, id_back)
    except Exception as e:
        logger.error(f"[kyc_submit] user={form.get('uid')} échec: {e}")
        return JSONResponse({"success": False, "message": str(e)}, status_code=500)
    return JSONResponse(result, status_code=200 if result.get("success") else 502)


# API background task to process queued requests
async def background_log_processor():
    """Background task to process log queue"""
    while True:
        try:
            # Check if MongoDB client and collection are available
            if not MONGODB_AVAILABLE or mongo_client_instance is None:
                logger.warning(
                    "MongoDB client not available for background log processor"
                )
                await asyncio.sleep(5)
                continue

            # Process API request batch if Redis is available
            if (
                redis_client
                and mongo_client_instance.api_requests_collection is not None
            ):
                queue_len = await redis_client.llen("api_request_queue")
                if queue_len > 0:
                    await process_api_request_batch()
            else:
                logger.warning("Redis client or API requests collection not available")
        except Exception as e:
            logger.error(f"Error in background log processor: {e}")

        # Run every 5 seconds
        await asyncio.sleep(5)


def fix_mongo_ids(doc):
    if isinstance(doc, list):
        return [fix_mongo_ids(item) for item in doc]
    elif isinstance(doc, dict):
        return {k: fix_mongo_ids(v) for k, v in doc.items()}
    elif isinstance(doc, ObjectId):
        return str(doc)
    else:
        return doc

# @app.get("/api/gets/asdfdd2343fsafsfapW/{userId}", dependencies=[Depends(
#     verify_telegram_miniapp), Depends(verify_telegram_init_data)])


@app.get("/api/gets/asdfdd2343fsafsfapW/{userId}",
         dependencies=[Depends(verify_telegram_init_data)])
#  Depends(verify_telegram_init_data)])
async def get_user_data_combined(userId: str, request: Request):
    """Unified API endpoint to retrieve user data, card details, and transactions."""
    logger.info(f"API Request: /api/gets/{userId}")

    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # Log request to MongoDB
    await mongo_client_instance.log_api_request(
        {
            "ip": request.client.host,
            "endpoint": f"/api/gets/asdfdd2343fsafsfapW/{userId}",
            "method": "GET",
            "user_agent": request.headers.get("user-agent", "Unknown"),
        }
    )

    try:
        # Prepare result object
        result = {"success": True, "user": None, "card": None, "transactions": []}

        # 1. Get user data
        user_found = False
        try:
            user_result = await mysql_client.get_user_from_db(user_id=userId)
            if user_result.get("success"):
                result["user"] = user_result.get("user", {})
                user_found = True
            else:
                result["error"] = "User not found"
                return JSONResponse(content=result, status_code=404)
        except Exception as e:
            logger.warning(f"Error retrieving user data: {e}")
            # Add specific error handling for MySQL connection issues
            if "Connection refused" in str(e) or "Can't connect to MySQL server" in str(
                e
            ):
                logger.error(
                    "MySQL connection failed. Please check if the MySQL service is running."
                )
                raise HTTPException(
                    status_code=503, detail="Database service temporarily unavailable."
                )
            user_found = False
            # Continue processing with user_found = False

        # 2. Get card details - base behavior on user status and card number
        try:
            if not user_found:
                # Condition 1: User not found - return null card data
                result["card"] = None
            else:
                # User found, check if they have a card number
                user_has_card = result["user"]["cardNumber"] != ""

                if not user_has_card:
                    # Condition 2: User found but no card number
                    result["card"] = {
                        "cardNumber": "",
                        "cvv": "",
                        "validDate": "",
                        "balance": "",
                        "cardStatus": "creating",
                    }
                else:
                    # Condition 3: User found with card number - get real data from
                    # Interlace
                    try:
                        # Get all cards for the user
                        cards = interlace_client.infinity_card.list_all_infinity_cards()

                        # Find the card matching the user's card number
                        user_card = None
                        for card in cards:

                            if (
                                card.card_no_last_four
                                == str(result["user"]["cardNumber"])[-4:]
                            ):
                                card_details = interlace_client.infinity_card.get_infinity_card_details(
                                    card.id)
                                if (card_details.card_no == str(
                                        result["user"]["cardNumber"])):
                                    user_card = card
                                    break

                        if user_card:
                            # # Get detailed card information
                            # card_details = interlace_client.infinity_card.get_infinity_card_details(
                            #     user_card.id
                            # )

                            # Format card number for display
                            # Convert to string if it's an integer
                            card_no = str(card_details.card_no)
                            formatted_card_number = " ".join(
                                [
                                    card_no[0:4],
                                    card_no[4:8],
                                    card_no[8:12],
                                    card_no[12:16],
                                ]
                            )

                            # Get the balance using the balance_id from user_card
                            balance_obj = None
                            if user_card and user_card.balance_id:
                                balance_data = (
                                    interlace_client.funding.list_all_balances(
                                        params={"id": user_card.balance_id}
                                    )
                                )
                                # Defensive: check for the correct structure (list)
                                if (
                                    balance_data
                                    and isinstance(balance_data, list)
                                    and len(balance_data) > 0
                                ):
                                    balance_obj = Balance.from_dict(balance_data[0])

                            # Format balance string
                            if balance_obj:
                                balance_str = f"{float(balance_obj.available):.2f} {balance_obj.currency}"
                            else:
                                balance_str = "0.00"

                            # Return active card data
                            result["card"] = {
                                "cardNumber": formatted_card_number,
                                "cvv": card_details.cvv,
                                "validDate": card_details.expiry_date,
                                "balance": balance_str,
                                "cardStatus": user_card.status.lower(),  # Use status from Card model
                            }
                        else:
                            # Card not found in Interlace
                            result["card"] = {
                                "cardNumber": "",
                                "cvv": "",
                                "validDate": "",
                                "balance": "",
                                "cardStatus": "creating",
                            }
                    except Exception as e:
                        logger.error(f"Error fetching card details from Interlace: {e}")
                        # If error, set card to creating state
                        result["card"] = {
                            "cardNumber": "",
                            "cvv": "",
                            "validDate": "",
                            "balance": "",
                            "cardStatus": "creating",
                        }
        except Exception as e:
            logger.warning(f"Error processing card data: {e}")
            # If error, set card to null
            result["card"] = None

        # 3. Get transactions - only if user exists and has active card
        try:
            if user_found and user_card:
                # Get transactions from MongoDB instead of Interlace API
                transactions = await mongo_client_instance.get_card_transactions(
                    user_card.id
                )
                result["transactions"] = transactions
            else:
                result["transactions"] = []

        except Exception as e:
            logger.warning(f"Error retrieving transaction data: {e}")
            result["transactions"] = []

        # Cache the combined result in Redis
        if redis_client and REDIS_AVAILABLE:
            try:
                cache_key = f"userdata:{userId}"
                await redis_client.set(
                    cache_key,
                    json.dumps(result, cls=DateTimeEncoder),
                    ex=60,  # Cache for 1 minute
                )
            except Exception as e:
                logger.error(f"Error caching combined user data: {e}")

        logger.info(f"Successfully retrieved combined data for user {userId}")
        return fix_mongo_ids(result)

    except Exception as e:
        logger.error(
            f"Error in combined data endpoint for {userId}: {e}", exc_info=True
        )
        raise HTTPException(status_code=500, detail="Server error fetching user data.")


@app.post("/api/block_card/{user_id}", dependencies=[Depends(
    verify_telegram_miniapp)])
async def block_card(user_id: str):
    """Block a user's card."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # 1. Block the card in MongoDB (if you store status there)
    if mongo_client_instance is not None:
        await mongo_client_instance.users.update_one(
            {"USER_ID": user_id}, {"$set": {"cardStatus": "blocked"}}
        )
    # 2. Freeze the card using Interlace
    try:
        # Find the user's card_id
        cards = interlace_client.infinity_card.list_all_infinity_cards()
        user_card = None
        for card in cards:
            if hasattr(card, "user_name") and str(card.user_name) == str(user_id):
                user_card = card
                break
            # Fallback: match by last four if user_id is not user_name
        if not user_card:
            # Try to get user card number from MySQL
            user_result = await mysql_client.get_user_from_db(user_id=user_id)
            if user_result.get("success"):
                card_number = user_result["user"].get("cardNumber", "")
                if card_number:
                    for card in cards:
                        if (
                            hasattr(card, "card_no_last_four")
                            and card.card_no_last_four == str(card_number)[-4:]
                        ):
                            card_details = interlace_client.infinity_card.get_infinity_card_details(
                                card.id)
                            if (card_details.card_no == str(card_number)):
                                user_card = card
                                break
        if user_card:
            interlace_client.infinity_card.freeze_infinity_card(user_card.id)
        else:
            logger.warning(f"No card found for user {user_id} to freeze in Interlace.")
    except Exception as e:
        logger.error(f"Error freezing card for user {user_id} in Interlace: {e}")
    # 3. Cancel any active deposit timer
    await mongo_client_instance.clear_deposit_timer(user_id)
    # 4. Mark any pending deposit as blocked
    if mongo_client_instance is not None:
        await mongo_client_instance.combined_transactions.update_many(
            {"user_id": user_id, "internal_status": {"$ne": "Done"}, "type": "deposit"},
            {"$set": {"internal_status": "Blocked"}},
        )
    return {
        "success": True,
        "message": "Card blocked, frozen, and deposit timer cleared.",
    }


@app.post("/api/unblock_card/{user_id}", dependencies=[Depends(
    verify_telegram_miniapp)])
async def unblock_card(user_id: str):
    """Unblock a user's card."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # 1. Unblock the card in MongoDB (if you store status there)
    if mongo_client_instance is not None:
        await mongo_client_instance.users.update_one(
            {"USER_ID": user_id}, {"$set": {"cardStatus": "active"}}
        )
    # 2. Unfreeze the card using Interlace
    try:
        # Find the user's card_id
        cards = interlace_client.infinity_card.list_all_infinity_cards()
        user_card = None
        for card in cards:
            if hasattr(card, "user_name") and str(card.user_name) == str(user_id):
                user_card = card
                break
        if not user_card:
            # Try to get user card number from MySQL
            user_result = await mysql_client.get_user_from_db(user_id=user_id)
            if user_result.get("success"):
                card_number = user_result["user"].get("cardNumber", "")
                if card_number:
                    for card in cards:
                        if (
                            hasattr(card, "card_no_last_four")
                            and card.card_no_last_four == str(card_number)[-4:]
                        ):
                            card_details = interlace_client.infinity_card.get_infinity_card_details(
                                card.id)
                            if (card_details.card_no == str(card_number)):
                                user_card = card
                                break
        if user_card:
            interlace_client.infinity_card.unfreeze_infinity_card(user_card.id)
        else:
            logger.warning(
                f"No card found for user {user_id} to unfreeze in Interlace."
            )
    except Exception as e:
        logger.error(f"Error unfreezing card for user {user_id} in Interlace: {e}")

    return {
        "success": True,
        "message": "Card unblocked, unfrozen, and deposits allowed.",
    }


# Remove in-memory timer/counter logic
def get_active_deposit_timer(user_id):
    return None


def start_deposit_timer(user_id, address, mode, timer_minutes):
    """Start a deposit timer for a user."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=timer_minutes)
    return expires_at


def clear_deposit_timer(user_id):
    """Clear a deposit timer for a user."""
    pass

# Start the background task at startup


@app.get("/config.json")
async def serve_config_json():
    """Serve the real miniapp/config.json as /config.json for the frontend."""
    config_path = os.path.join(
        os.path.dirname(__file__),
        "miniapp_telegram",
        "config.json")
    return FileResponse(config_path, media_type="application/json")


async def process_expired_deposit_timers():
    """
    Checks for expired deposit timers in MongoDB and handles expiry logic.
    Only marks timers as inactive when they are actually expired.
    """
    logger.info("Starting deposit timer check at %s", datetime.now(timezone.utc))
    now = datetime.now(timezone.utc)
    active_timers = await mongo_client_instance.get_all_active_deposit_timers()
    logger.info("Found %d active deposit timers", len(active_timers))

    for timer in active_timers:
        user_id = timer["user_id"]
        address = timer["address"]
        mode = timer["mode"]
        index = timer.get("index")
        expires_at = timer.get("expires_at")
        expiry_notified = timer.get("expiry_notified", False)

        # Ensure expires_at is timezone-aware
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        logger.info(
            "Processing timer for user %s: address=%s, mode=%s, index=%s, expires_at=%s, expiry_notified=%s",
            user_id, address, mode, index, expires_at, expiry_notified
        )

        # Skip if timer is not expired yet
        if expires_at and expires_at > now:
            logger.info(
                "Timer for user %s not expired yet (expires at %s)",
                user_id,
                expires_at)
            continue

        # Check if deposit was made
        deposit_found = False
        if mongo_client_instance is not None:
            deposit = await mongo_client_instance.combined_transactions.find_one(
                {"user_id": user_id, "address": address, "internal_status": "Done"}
            )
            if deposit:
                deposit_found = True
                logger.info(
                    "Found completed deposit for user %s with address %s",
                    user_id,
                    address)

        if deposit_found:
            # If deposit was made, clear the timer
            logger.info("Clearing timer for user %s due to completed deposit", user_id)
            await mongo_client_instance.clear_deposit_timer(user_id)
            continue

        # No deposit found and timer is expired
        if not expiry_notified:
            # Send expiry notification if not already sent
            try:
                message = (
                    f"⚠️ Your deposit address {address} has expired.\n\n"
                    "Please press the Deposit button again to get a new address."
                )
                logger.info(
                    "Sending expiry notification to user %s for address %s",
                    user_id,
                    address)
                await telegram_messaging.send_deposit_expiry(user_id, message)
            except Exception as e:
                logger.error(
                    "Error sending Telegram message to user %s: %s", user_id, e)

            # Mark as notified and inactive
            logger.info("Marking timer as notified and inactive for user %s", user_id)
            await mongo_client_instance.deposit_timers.update_one(
                {"user_id": user_id},
                {"$set": {"active": False, "reserved": False, "expiry_notified": True}},
            )

        # Handle address cleanup based on mode
        if mode == "single":
            try:
                nova_client = NovaClient(
                    access_key=NOVA_API_ACCESS_KEY,
                    secret_key=NOVA_API_SECRET_KEY,
                    mongo_client_instance=mongo_client_instance,
                )
                logger.info(
                    "Deleting expired deposit address %s for user %s (single mode)",
                    address,
                    user_id)
                nova_client.delete_deposit_address(address)
            except Exception as e:
                logger.error(
                    "Error deleting deposit address %s for user %s: %s",
                    address,
                    user_id,
                    e)

    logger.info("Completed deposit timer check at %s", datetime.now(timezone.utc))


async def deposit_timer_background_task():
    """Background task to process expired deposit timers"""
    while True:
        try:
            # Check if MongoDB client is available
            if not MONGODB_AVAILABLE or mongo_client_instance is None:
                logger.warning("MongoDB client not available for deposit timer task")
                await asyncio.sleep(60)
                continue

            # Process expired timers
            await process_expired_deposit_timers()
        except Exception as e:
            logger.error(f"Error in deposit timer background task: {e}")

        # Run every 60 seconds
        await asyncio.sleep(60)


@app.get("/api/deposit_page/{user_id}", dependencies=[Depends(
    verify_telegram_miniapp)])
async def get_deposit_page(user_id: str):
    """Get deposit page for a user."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # Load config
    with open("miniapp_telegram/config.json", "r", encoding="utf-8") as f:
        config_data = json.load(f)

    pool_mode = config_data.get("POOL", True)
    timer_minutes = config_data.get("deposit_address_valid_minutes", 30)

    # Check if card is blocked
    card_blocked = False
    user_result = await mysql_client.get_user_from_db(user_id=user_id)
    if user_result.get("success"):
        user_result = user_result.get("user", {})

    try:
        cards = interlace_client.infinity_card.list_all_infinity_cards()
        user_card = None
        for card in cards:
            if str(card.card_no_last_four) == str(user_result["cardNumber"])[-4:]:
                card_details = interlace_client.infinity_card.get_infinity_card_details(
                    card.id)
                if (card_details.card_no == str(user_result["cardNumber"])):
                    user_card = card
                    break
        if user_card and getattr(user_card, "status", "").lower() == "frozen":
            card_blocked = True
    except Exception as e:
        logger.error(f"Error checking card status in Interlace: {e}")

    if card_blocked:
        return {"success": False, "message": "Card is blocked. Unblock to deposit."}

    # Use MongoDB for persistent timer state
    timer_doc = await mongo_client_instance.get_deposit_timer(user_id)
    now = datetime.now(timezone.utc)

    # Ensure expires_at is timezone-aware before comparison
    if timer_doc and timer_doc.get("expires_at"):
        expires_at = timer_doc["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at > now:
            # Timer is active and not expired
            remaining_seconds = int((expires_at - now).total_seconds())

            if pool_mode:
                return {
                    "success": True,
                    "mode": timer_doc["mode"],
                    "address": timer_doc["address"],
                    "timer_minutes": remaining_seconds // 60,
                    "timer_seconds": remaining_seconds % 60,
                    "index": timer_doc.get("index"),
                }
            else:
                return {
                    "success": True,
                    "mode": timer_doc["mode"],
                    "address": user_result.get("novaAddress", ""),
                    "timer_minutes": remaining_seconds // 60,
                    "timer_seconds": remaining_seconds % 60,
                    "index": timer_doc.get("index"),
                }

    # Timer expired or doesn't exist, create new one
    if pool_mode:
        # --- POOL MODE ---
        # Get all addresses from pool
        addresses = nova_client.list_deposit_addresses()
        pool_size = len(addresses.get("items", []))

        if pool_size == 0:
            return {"success": False, "message": "No addresses available in pool"}

        # Get next available index using the new method
        next_index = await mongo_client_instance.get_next_available_pool_index(
            pool_size, user_id
        )

        if next_index == -1:
            try:
                await telegram_messaging.send_deposit_not_available(user_id)
            except Exception as e:
                logger.error(f"Error sending Telegram message: {e}")
            return {
                "success": False,
                "message": "No addresses available. Try again in a few minutes.",
            }

        # Get the address at the calculated index
        address = addresses["items"][next_index].get("address")
        if not address:
            return {"success": False, "message": "No valid address found in pool"}

        expires_at = now + timedelta(minutes=timer_minutes)
        try:
            await mongo_client_instance.set_deposit_timer(
                user_id, address, "pool", expires_at, index=next_index
            )
        except Exception as e:
            logger.error(f"Error setting deposit timer: {e}")
            return {"success": False, "message": "Error setting deposit timer"}

        # Always send Telegram message when new address is assigned
        try:
            await telegram_messaging.send_deposit_address(
                user_id, address, timer_minutes
            )
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")

        return {
            "success": True,
            "mode": "pool",
            "address": address,
            "timer_minutes": timer_minutes,
            "timer_seconds": 0,
            "index": next_index,
        }
    else:
        # --- SINGLE MODE ---
        try:
            # new_addr_obj = nova_client.create_deposit_address("trc20usdt")
            # address = new_addr_obj.get("address")
            address = user_result.get("novaAddress", "")
            if not address:
                return {"success": False, "message": "Failed to create new address"}
        except Exception as e:
            return {"success": False, "message": f"Failed to create address: {e}"}
            # address = user_result.get("novaAddress", "")
        expires_at = now + timedelta(minutes=timer_minutes)
        await mongo_client_instance.set_deposit_timer(
            user_id, address, "single", expires_at, reserved=True
        )
        # Send Telegram message
        try:
            await telegram_messaging.send_deposit_address(
                user_id, address, timer_minutes
            )
        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
        return {
            "success": True,
            "mode": "single",
            "address": address,
            "timer_minutes": timer_minutes,
            "timer_seconds": 0,
            "index": -1
        }


@app.post("/api/sheet_snapshot")
async def sheet_snapshot(request: Request):
    data = await request.json()
    secure_token = data.get("secure_token")
    if secure_token != config.GOOGLE_SHEETS_CONFIG.get("secure_token", ""):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: Unauthorized miniapp request")
    sheet_name = data.get("sheet")
    headers = data.get("headers", [])
    rows = data.get("rows", [])

    if not sheet_name:
        return {"success": False, "message": "Missing sheet name"}

    # if we got no rows, but we do have headers → build empty DF with columns
    if not rows:
        if not headers:
            return {
                "success": False,
                "message": "No data rows and no headers provided"
            }
        df = pd.DataFrame(columns=headers)
    else:
        df = pd.DataFrame(rows, columns=headers)

    table_name = sheet_name.lower()
    try:
        mysql_client.to_sql(
            df,
            table_name,
            if_exists="replace",
            index=False
        )
        return {
            "success": True,
            "message": f"Table {table_name} updated"
        }
    except Exception as e:
        return {
            "success": False,
            "message": str(e)
        }


@app.get("/api/sheet_snapshot_deposit/{secure_token}")
async def sheet_snapshot_deposit(request: Request):
    """Handle Google Sheets trigger for deposit data updates.

    This endpoint processes deposit data from combined_transactions and updates
    the Google Sheet with card details, referral codes, and deposit information.
    """
    try:
        secure_token = request.path_params.get("secure_token")
        if secure_token != config.GOOGLE_SHEETS_CONFIG.get("secure_token", ""):
            raise HTTPException(
                status_code=403,
                detail="Access forbidden: Unauthorized miniapp request")
        # Get all completed deposits from MongoDB
        deposits = await mongo_client_instance.combined_transactions.find({
            'type': 'deposit',
            'status': 'Done'
        }).to_list(length=None)

        # Initialize result list to store updated data
        updated_rows = []
        interlace_client = InterlaceClient()
        # Process each deposit
        for deposit in deposits:
            card_number = deposit.get('card_number')
            if not card_number:
                continue

            user_card = interlace_client.infinity_card.list_all_infinity_cards(
                params={"id": deposit["cardId"]})[0]

            if user_card and user_card.balance_id:
                balance_data = interlace_client.funding.list_all_balances(
                    params={"id": user_card.balance_id}
                )[0]

                current_balance = float(balance_data["available"])
            else:
                current_balance = 0

            try:
                # Get user details from MySQL to get referral code
                user_result = await mysql_client.get_user_from_db(card_number=card_number)
                referral_code = user_result.get('user', {}).get(
                    'referralCode', '') if user_result.get('success') else ''

                # Create updated row
                updated_row = {
                    'card': card_number,
                    'referral': referral_code,
                    'deposit': deposit["amount"],
                    'current balance': current_balance,
                    'fee deposit': deposit["fee_percent_nova"] * deposit["amount"],
                }

                updated_rows.append(updated_row)

            except Exception as e:
                logger.error(f"Error processing card {card_number}: {e}")
                continue

        # Create DataFrame from updated rows
        updated_df = pd.DataFrame(updated_rows)

        try:
            updated_df["card"] = updated_df["card"].astype(str)
            sum_row = pd.DataFrame([{
                'card': 'TOTAL',
                'referral': '',
                'deposit': updated_df['deposit'].sum(),
                'current balance': '',
                'fee deposit': updated_df['fee deposit'].sum()
            }])
        except Exception as e:
            sum_row = pd.DataFrame([{
                'card': 'TOTAL',
                'referral': '',
                'deposit': '',
                'current balance': '',
                'fee deposit': ''}])
            logger.error(f"Error processing card: {e}")
            # continue

        # Add sum row for deposit column
        updated_df = pd.concat([updated_df, sum_row], ignore_index=True)

    # Save to MySQL
        try:
            mysql_client.to_sql(
                updated_df,
                'deposits',
                if_exists="replace",
                index=False)

            # Update Google Sheet
            sheets_service = initialize_sheets_service()
            if sheets_service:
                try:
                    # Convert DataFrame to list of lists for Google Sheets
                    values = [updated_df.columns.tolist()] + updated_df.values.tolist()

                    # Update the deposits sheet
                    range_name = "deposits!A1:E10000"
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
                    logger.info("Successfully updated deposits sheet")
                except Exception as sheet_err:
                    logger.error(f"Error updating Google Sheet: {sheet_err}")

            return {
                "success": True,
                "message": f"Deposits sheet updated with {len(updated_rows)} records"
            }

        except Exception as e:
            logger.error(f"Error saving to MySQL: {e}")
            return {"success": False, "message": str(e)}

    except Exception as e:
        logger.error(f"Error in sheet_snapshot_deposit: {e}")
        return {"success": False, "message": str(e)}

if TESTING_MODE:

    @app.post("/api/test/simulate_deposit")
    async def simulate_deposit(request: Request):
        """
        Simulate a deposit event for testing. This endpoint mimics the Nova WebSocket
        receiving a deposit event and triggers the deposit_callback in nova_api/client.py.
        """
        try:
            payload = await request.json()

            # Ensure we have the required fields
            if not (
                isinstance(payload, dict)
                and "object" in payload
                and "action" in payload
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Payload must include 'action' and 'object' fields.",
                )

            # Initialize NovaClient with MongoDB instance
            nova_client = NovaClient(
                access_key=NOVA_API_ACCESS_KEY,
                secret_key=NOVA_API_SECRET_KEY,
                mongo_client_instance=mongo_client_instance,
            )

            # Call the deposit_callback method on the NovaClient instance
            if not hasattr(nova_client, "deposit_callback"):
                raise HTTPException(
                    status_code=500,
                    detail="NovaClient not initialized or missing deposit_callback.",
                )
            await nova_client.deposit_callback(payload)
            return {"success": True, "message": "Simulated deposit event processed."}

        except Exception as e:
            logger.error(f"Error in simulate_deposit: {e}")
            raise HTTPException(
                status_code=500, detail=f"Error processing test deposit: {str(e)}"
            )


# --- Helper Functions for CardTransaction Handling ---


def extract_transaction_details(data: dict) -> dict:
    """Extract and format transaction details from the callback data."""
    transaction_id = data.get("id")
    card_id = data.get("cardId")
    amount = float(data.get("amount", 0))
    fee = float(data.get("fee", 0))
    currency = data.get("currency")
    transaction_type = data.get("type")
    status = data.get("status")
    client_transaction_id = data.get("clientTransactionId", "")
    transaction_amount = float(data.get("transactionAmount", 0))
    transaction_currency = data.get("transactionCurrency")
    remark = data.get("remark", "")
    detail = data.get("detail", "")

    # Extract tid from clientTransactionId
    tid = (
        client_transaction_id.split("_")[1]
        if "tid_" in client_transaction_id
        else client_transaction_id
    )
    is_fee_callback = client_transaction_id.endswith("_Fee_Consumption")

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
        "remark": remark,
        "detail": detail,
        "tid": tid,
        "is_fee_callback": is_fee_callback,
    }


def consumption_fee_foreign(
    update_fields: dict, transaction_details: dict, latest_combined: dict
):
    """Calculate foreign currency consumption fees.

    Args:
        update_fields: Dictionary to store the calculated fees
        transaction_details: Current transaction details
        latest_combined: Latest combined document if it exists
    """
    logger.info(
        f"Calculating foreign consumption fee for transaction {transaction_details.get('tid')}"
    )

    # Calculate foreign fee if possible
    if (
        transaction_details["transaction_currency"]
        and transaction_details["transaction_currency"]
        != transaction_details["currency"]
        and transaction_details["transaction_amount"] > 0
        and transaction_details["amount"] > 0
    ):
        conversion_rate = (
            transaction_details["transaction_amount"] / transaction_details["amount"]
            if transaction_details["amount"] != 0
            else 0
        )
        foreign_fee = transaction_details["fee"] * conversion_rate
        update_fields["consumption_fee"]["foreign"] = foreign_fee
        logger.info(
            f"Calculated foreign fee: {foreign_fee} {transaction_details['transaction_currency']} "
            f"(conversion rate: {conversion_rate})"
        )

    if latest_combined and (
        latest_combined["transaction_currency"]
        and latest_combined["transaction_currency"] != latest_combined["currency"]
        and latest_combined["transaction_amount"] > 0
        and latest_combined["amount"] > 0
    ):
        conversion_rate = (
            latest_combined["transaction_amount"] / latest_combined["amount"]
            if latest_combined["amount"] != 0
            else 0
        )
        foreign_fee = latest_combined["fee"] * conversion_rate
        update_fields["consumption_fee"]["foreign"] = foreign_fee
        logger.info(
            f"Updated foreign fee from latest combined: {foreign_fee} {latest_combined['transaction_currency']} "
            f"(conversion rate: {conversion_rate})"
        )

    return update_fields


async def handle_fee_callback(transaction_details: dict, latest_combined: dict):
    """Handle fee callback for a transaction."""
    logger.info(
        f"Processing fee callback for transaction {transaction_details.get('tid')}"
    )

    if not (
        transaction_details["is_fee_callback"]
        and transaction_details["amount"] == 0
        and transaction_details["fee"] > 0
    ):
        logger.info("Not a valid fee callback - skipping")
        return

    logger.info(
        f"Valid fee callback detected - fee amount: {transaction_details['fee']} {transaction_details['currency']}"
    )

    update_fields = {
        "consumption_fee": {"usd": transaction_details["fee"], "foreign": None}
    }

    update_fields = consumption_fee_foreign(
        update_fields, transaction_details, latest_combined
    )

    # Update or create stub
    if latest_combined:
        logger.info(
            f"Updating existing fee document for tid {transaction_details['tid']}"
        )
        await update_existing_fee_doc(
            latest_combined, update_fields, transaction_details
        )
    else:
        logger.info(f"Creating new fee document for tid {transaction_details['tid']}")
        await create_new_fee_doc(transaction_details, update_fields)


async def update_existing_fee_doc(
    latest_combined: dict, update_fields: dict, transaction_details: dict
):
    """Update an existing fee document with new fee information."""
    if (
        "consumption_fee" in latest_combined
        and latest_combined["consumption_fee"].get("foreign") is None
        and transaction_details["transaction_currency"]
        and transaction_details["transaction_currency"]
        != transaction_details["currency"]
        and transaction_details["transaction_amount"] > 0
        and transaction_details["amount"] > 0
    ):

        conversion_rate = (
            transaction_details["transaction_amount"] / transaction_details["amount"]
            if transaction_details["amount"] != 0
            else 0
        )
        update_fields["consumption_fee"]["foreign"] = (
            latest_combined["consumption_fee"]["usd"] * conversion_rate
        )

    # Update the document with new fee information
    await mongo_client_instance.combined_transactions.update_one(
        {"_id": latest_combined["_id"]},
        {
            "$set": {
                "consumption_fee": update_fields["consumption_fee"],
                # 'status': transaction_details['status'],
                "timestamp": datetime.now(timezone.utc),
            }
        },
    )


async def create_new_fee_doc(transaction_details: dict, update_fields: dict):
    """Create a new fee document."""
    combined_doc = {
        "tid": transaction_details["tid"],
        "cardId": transaction_details["cardId"],
        "status": transaction_details["status"],
        "timestamp": datetime.now(timezone.utc),
        "consumption_fee": update_fields["consumption_fee"],
        "detail": transaction_details["detail"],
        "remark": transaction_details["remark"],
    }
    await mongo_client_instance.combined_transactions.insert_one(combined_doc)


async def handle_main_transaction(transaction_details: dict, latest_combined: dict):
    """Handle main transaction callback."""
    try:
        interlace_client = InterlaceClient()
        # Calculate fees for foreign transactions
        fee_details = await calculate_transaction_fees(transaction_details)

        # Handle failed/reversed transactions
        if should_reverse_fees(transaction_details, latest_combined):
            await reverse_transaction_fees(transaction_details, fee_details)
            # fee_details = {
            #     "nova_fee_usd": 0,
            #     "nova_fee_foreign": 0,
            #     "conversion_rate": 0,
            # }

        user_card = interlace_client.infinity_card.get_infinity_card_details(
            transaction_details["cardId"]
        )
        card_number = str(user_card.card_no)

        user = await mysql_client.get_user_from_db(card_number=card_number)
        if not user.get("success") or not user.get("user"):
            logger.error(f"No user found for card number {card_number}")
            return

        user_id = user["user"].get("userId") or user["user"].get("USER_ID")
        if not user_id:
            logger.error(f"No user ID found for card number {card_number}")
            return

        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")
        status = transaction_details["status"]
        # Format the transaction amount with 2 decimal places
        if transaction_details["transaction_type"] in ["Reversal", "Credit"]:
            transaction_details["amount"] = - \
                np.abs(float(transaction_details["amount"]))
            transaction_details["transaction_amount"] = - \
                np.abs(float(transaction_details["transaction_amount"]))

        transaction_amount = (
            f"{float(transaction_details['amount']):.2f} {transaction_details['currency']}"
            if "transaction_amount" not in transaction_details.keys()
            else f"{float(transaction_details['transaction_amount']):.2f} {transaction_details['transaction_currency']}"
        )

        # Get the card number and mask it
        masked_card = f"{str(card_number)[:4]}***{str(card_number)[-4:]}"

        # Get the merchant name from transaction details
        merchant = transaction_details.get('detail', 'Unknown Merchant')

        balance_obj = None
        user_card = interlace_client.infinity_card.list_all_infinity_cards(
            params={"id": transaction_details["cardId"]})[0]

        if user_card and user_card.balance_id:
            balance_data = interlace_client.funding.list_all_balances(
                params={"id": user_card.balance_id}
            )
            # Defensive: check for the correct structure (list)
            if (
                balance_data
                and isinstance(balance_data, list)
                and len(balance_data) > 0
            ):
                balance_obj = Balance.from_dict(balance_data[0])

        # Format balance string
        if balance_obj:
            balance_str = f"{float(balance_obj.available):.2f} {balance_obj.currency}"
        else:
            balance_str = "0.00"

        message = f"{current_time} PURCHASE: {transaction_amount}, card: {masked_card}, terminal: {merchant}, AVAILABLE: {balance_str}."

        old_exists = False
        transactions = interlace_client.infinity_card.list_all_infinity_card_transactions(
            params={
                "cardId": transaction_details["cardId"],
                "type": "Consumption"}
        )

        if transactions:
            for transaction in transactions:
                if f"{transaction_details['tid']}" in transaction.client_transaction_id:
                    logger.info(
                        f"Skipping telegram pending transaction: {transaction}")
                    old_exists = True
                    break

        if transaction_details["status"] != "Closed" and not old_exists:
            await telegram_messaging.send_message(
                user_id,
                f"Transaction {status}: {message}",
            )

        # Prepare and save transaction document
        combined_doc = prepare_transaction_doc(
            transaction_details, fee_details, latest_combined
        )

        # If we have a latest combined doc, update it
        if latest_combined:
            await mongo_client_instance.combined_transactions.update_one(
                {"_id": latest_combined["_id"]}, {"$set": combined_doc}
            )
            logger.info(
                f"Updated existing document for tid {transaction_details['tid']}"
            )
        else:
            # Create new document
            await mongo_client_instance.combined_transactions.insert_one(combined_doc)
            logger.info(f"Created new document for tid {transaction_details['tid']}")

    except Exception as e:
        logger.error(
            f"Error handling main transaction for tid {transaction_details['tid']}: {e}"
        )
        raise


async def calculate_transaction_fees(transaction_details: dict) -> dict:
    """Calculate fees for a transaction."""
    nova_fee_usd = 0
    nova_fee_foreign = 0
    conversion_rate = 0

    is_foreign = (
        transaction_details["transaction_amount"] != 0
        and transaction_details["transaction_currency"]
        and transaction_details["transaction_currency"]
        != transaction_details["currency"]
    )

    if is_foreign:
        try:
            interlace_client = InterlaceClient()
            card_info = interlace_client.infinity_card.get_infinity_card_details(
                transaction_details["cardId"]
            )
            user_info = await get_user_info(card_info.card_no)
            if not user_info:
                return {"nova_fee_usd": 0, "nova_fee_foreign": 0, "conversion_rate": 0}

            fees = await get_user_fees(user_info["user_id"])
            nova_fee_usd = (
                transaction_details["amount"] - transaction_details["fee"]
            ) * (fees["foreign_fee"] / 100.0)
            conversion_rate = (
                transaction_details["transaction_amount"]
                / transaction_details["amount"]
                if transaction_details["amount"] != 0
                else 0
            )
            try:
                nova_fee_usd = round(float(nova_fee_usd), 2)
            except Exception as e:
                logger.error(f"Error rounding nova fee: {e}: {transaction_details}")
                nova_fee_usd = 0

            # Only attempt to transfer out fee if it's greater than 0
            if nova_fee_usd > 0:
                nova_fee_foreign = nova_fee_usd * conversion_rate
                try:
                    if transaction_details["status"].lower() == "pending":
                        old_transferouts = interlace_client.infinity_card.list_all_infinity_card_transactions(
                            params={
                                "cardId": transaction_details["cardId"],
                                "type": "TransferOut"}
                        )
                        old_exists = False
                        if old_transferouts:
                            for transferout in old_transferouts:
                                if f"NovaFee_{transaction_details['tid']}" in transferout.client_transaction_id:
                                    logger.info(
                                        f"Skipping transfer out for pending transaction: {transferout}")
                                    old_exists = True
                                    break
                        if not old_exists:
                            nova_fee_transfer_out = (
                                interlace_client.infinity_card.infinity_card_transfer_out(
                                    {
                                        "cardId": transaction_details["cardId"],
                                        "cost": nova_fee_usd,
                                        "clientTransactionId": f"NovaFee_{transaction_details['tid']}_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}",
                                    }
                                )
                            )
                            logger.info(
                                f"Nova fee transfer out: {nova_fee_transfer_out}")
                        else:
                            logger.info("Skipping novafee already exists")
                    else:
                        logger.info("Skipping transfer out for non-pending transaction")
                except Exception as e:
                    error_msg = str(e)
                    if "金额必须大于0" in error_msg:
                        logger.warning("Nova fee amount too small to transfer out")
                        # nova_fee_usd = 0
                        # nova_fee_foreign = 0
                    else:
                        logger.error(f"Error calculating nova fee: {e}")
            else:
                logger.info("Nova fee amount is 0, skipping transfer out")

        except Exception as e:
            logger.error(f"Error calculating nova fee: {e}")

    return {
        "nova_fee_usd": nova_fee_usd,
        "nova_fee_foreign": nova_fee_foreign,
        "conversion_rate": conversion_rate,
    }


async def get_user_info(card_id: str) -> dict:
    """Get user information from MySQL."""
    user_result = await mysql_client.get_user_from_db(card_number=card_id)
    if not user_result.get("success"):
        logger.error(f"No user found for card_id {card_id}")
        return None

    user = user_result.get("user", {})
    user_id = user.get("userId")
    card_number = user.get("cardNumber")

    if not user_id or not card_number:
        logger.error(f"Missing user_id or card_number for card_id {card_id}")
        return None

    return {"user_id": user_id, "card_number": card_number}


async def get_user_fees(user_id: str) -> dict:
    """Get user fees from MySQL."""
    deposit_fee, foreign_fee = await mysql_client.get_fees_for_user_mysql(
        user_id=user_id
    )
    return {"deposit_fee": deposit_fee, "foreign_fee": foreign_fee}


def should_reverse_fees(transaction_details: dict, latest_combined: dict) -> bool:
    """Determine if fees should be reversed."""

    if latest_combined:
        if latest_combined["status"].lower() != "pending":
            return False
        else:
            return (
                transaction_details["status"]
                and transaction_details["status"].lower() == "fail"
            ) or (transaction_details["transaction_type"].lower() in ["reversal", "credit"])
    else:
        return False


async def reverse_transaction_fees(transaction_details: dict, fee_details: dict):
    """Reverse fees for a failed or reversed transaction."""
    if fee_details["nova_fee_usd"] > 0:
        try:
            interlace_client = InterlaceClient()
            old_transferouts = interlace_client.infinity_card.list_all_infinity_card_transactions(
                params={
                    "cardId": transaction_details["cardId"],
                    "type": "TransferIn"}
            )
            old_exists = False
            took_nova_fee = False
            if old_transferouts:
                for transferout in old_transferouts:
                    if f"NovafeeReversal_{transaction_details['tid']}" in transferout.client_transaction_id:
                        logger.info(
                            f"Skipping transfer out for pending transaction: {transferout}")
                        old_exists = True
                    elif f"NovaFee_{transaction_details['tid']}" in transferout.client_transaction_id:
                        took_nova_fee = True

            if not old_exists and took_nova_fee:
                transfer_payload = {
                    "cardId": transaction_details["cardId"],
                    "cost": fee_details["nova_fee_usd"],
                    "clientTransactionId": f"NovafeeReversal_{transaction_details['tid']}_{int(datetime.now().timestamp())}_{random.randint(1000, 9999)}",
                }
                transfer_response = (
                    interlace_client.infinity_card.infinity_card_transfer_in(
                        transfer_payload
                    )
                )
                logger.info(f"Transferred nova fee back to card: {transfer_response}")
            else:
                logger.info("Skipping novafee reversal already exists")
        except Exception as e:
            logger.error(f"Error transferring nova fee back to card: {e}")


def prepare_transaction_doc(
    transaction_details: dict, fee_details: dict, latest_combined: dict
) -> dict:
    """Prepare the transaction document for saving."""
    # Start with the latest combined document if it exists
    combined_doc = latest_combined.copy() if latest_combined else {}

    # Update with new transaction details
    combined_doc.update(
        {
            "tid": transaction_details["tid"],
            "transaction_id": transaction_details["transaction_id"],
            "cardId": transaction_details["cardId"],
            "amount": transaction_details["amount"],
            "fee": transaction_details["fee"],
            "currency": transaction_details["currency"],
            "transaction_type": transaction_details["transaction_type"],
            "status": transaction_details["status"],
            "client_transaction_id": transaction_details["client_transaction_id"],
            "transaction_amount": transaction_details["transaction_amount"],
            "transaction_currency": transaction_details["transaction_currency"],
            "remark": transaction_details["remark"],
            "detail": transaction_details["detail"],
            "nova_fee_usd": fee_details["nova_fee_usd"],
            "nova_fee_foreign": fee_details["nova_fee_foreign"],
            "conversion_rate": fee_details["conversion_rate"],
            "consumption_fee": {"usd": 0.5 if transaction_details["amount"] < NOVA_CONSUMPTION_FEE_T else 0, "foreign": 0},
            "timestamp": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    )

    # Log status and type changes if they occurred
    if latest_combined:
        if latest_combined.get("status") != transaction_details["status"]:
            logger.info(
                f"Status change for tid {transaction_details['tid']}: {latest_combined.get('status')} -> {transaction_details['status']}"
            )
        if (
            latest_combined.get("transaction_type")
            != transaction_details["transaction_type"]
        ):
            logger.info(
                f"Type change for tid {transaction_details['tid']}: {latest_combined.get('transaction_type')} -> {transaction_details['transaction_type']}"
            )

    return combined_doc


async def save_transaction_doc(combined_doc: dict, latest_combined: dict):
    """Save the transaction document to MongoDB."""
    if latest_combined and latest_combined.get("status") != combined_doc["status"]:
        # Insert new doc if status changed
        for k, v in latest_combined.items():
            if k not in combined_doc:
                combined_doc[k] = v
        await mongo_client_instance.combined_transactions.insert_one(combined_doc)
    else:
        # Update existing doc
        if latest_combined:
            await mongo_client_instance.combined_transactions.update_one(
                {"_id": latest_combined["_id"]}, {"$set": combined_doc}
            )
        else:
            await mongo_client_instance.combined_transactions.insert_one(combined_doc)


async def handle_transfer_in(transaction_details: dict):
    """Handle transfer in transaction."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    if transaction_details["is_fee_callback"]:
        logger.info(
            f"Ignoring fee callback for TransferIn transaction {transaction_details['transaction_id']}"
        )
        return

    # Handle initial card creation deposit
    if await handle_initial_card_creation(transaction_details):
        return

    # Handle regular deposit
    await handle_regular_deposit(transaction_details)


async def handle_initial_card_creation(transaction_details: dict) -> bool:
    """Handle initial card creation."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    if transaction_details["amount"] != 10:
        return False

    existing_deposits = await mongo_client_instance.combined_transactions.find(
        {
            "cardId": transaction_details["cardId"],
            "type": "deposit",
            "internal_status": "Done",
        }
    ).to_list(length=1)

    if not existing_deposits:
        logger.info(
            f"Detected initial card creation deposit for card_id {transaction_details['cardId']}"
        )
        await mongo_client_instance.combined_transactions.insert_one(
            {
                "cardId": transaction_details["cardId"],
                "type": "deposit",
                "internal_status": "Done",
                "amount": transaction_details["amount"],
                "card_transaction_id": transaction_details["transaction_id"],
                "card_transaction_time": transaction_details.get("transaction_time"),
                "is_initial_card_creation": True,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
        return True

    return False


async def handle_regular_deposit(transaction_details: dict):
    """Handle regular deposit."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    # Find latest pending deposit
    latest_pending = await mongo_client_instance.combined_transactions.find_one(
        {
            "cardId": transaction_details["cardId"],
            "type": "deposit",
            "nova_status": "Done",
            "status": "Processing",
        },
        sort=[("timestamp", -1)],
    )

    if not latest_pending:
        logger.warning(
            f"No pending deposit found for card_id {transaction_details['cardId']}"
        )
        return

    # Check if this is first real deposit
    is_first_real = await check_first_real_deposit(transaction_details["cardId"])

    # Update pending deposit if amounts match
    await update_pending_deposit(latest_pending, transaction_details, is_first_real)


async def check_first_real_deposit(card_id: str) -> bool:
    """Check if this is the first real deposit."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()

    completed_deposits = await mongo_client_instance.combined_transactions.find(
        {
            "cardId": card_id,
            "type": "deposit",
            "internal_status": "Done",
        }
    ).to_list(length=100)

    if not completed_deposits:
        return True
    if len(completed_deposits) == 1 and completed_deposits[0].get(
        "is_initial_card_creation"
    ):
        return True
    return False


async def update_pending_deposit(
    latest_pending: dict, transaction_details: dict, is_first_real: bool
):
    """Update pending deposit."""
    # Initialize clients
    nova_client = NovaClient(
        access_key=NOVA_API_ACCESS_KEY,
        secret_key=NOVA_API_SECRET_KEY,
        mongo_client_instance=mongo_client_instance,
    )
    interlace_client = InterlaceClient()
    balances = interlace_client.funding.list_all_balances()
    for bal in balances:
        if bal["walletType"] == "QuantumAccount" and bal["currency"] == "USD":
            quantum_balance = float(bal["available"])
            break

    expected_final = latest_pending.get("final_amount", 0)

    # Use a small tolerance for floating point comparison
    if abs(transaction_details["amount"] - expected_final) < 0.01:
        update_fields = {"internal_status": "Done", "status": "Done"}

        await mongo_client_instance.combined_transactions.update_one(
            {"_id": latest_pending["_id"]}, {"$set": update_fields}
        )

        logger.info(
            f"Updated deposit {latest_pending['tid']} to done status. "
            f"First real deposit: {is_first_real}, "
            f"Amount: {transaction_details['amount']}, Expected: {expected_final}"
        )
        # Get all cards for the user
        cards = interlace_client.infinity_card.list_all_infinity_cards()

        # Find the card matching the user's card number
        user_card = None
        for card in cards:
            if card.card_no_last_four == str(latest_pending["card_number"])[-4:]:
                card_details = interlace_client.infinity_card.get_infinity_card_details(
                    card.id)
                if (card_details.card_no == str(latest_pending["card_number"])):
                    user_card = card
                    break

        # user_card = interlace_client.infinity_card.get_infinity_card_details(
        #     user_card.id
        # )

        balance_obj = None

        if user_card and user_card.balance_id:
            balance_data = interlace_client.funding.list_all_balances(
                params={"id": user_card.balance_id}
            )
            # Defensive: check for the correct structure (list)
            if (
                balance_data
                and isinstance(balance_data, list)
                and len(balance_data) > 0
            ):
                balance_obj = Balance.from_dict(balance_data[0])

        logger.info(f"Balance object: {balance_obj}")
        logger.info(f"Card object: {user_card}")
        # Format balance string
        if balance_obj:
            balance_str = f"{float(balance_obj.available):.2f} {balance_obj.currency}"
        else:
            balance_str = "0.00"

        await telegram_messaging.send_message(
            latest_pending["user_id"],
            f"Deposit completed: {transaction_details['amount']} {transaction_details['currency']}\nAvailable Balance: {balance_str}",
        )
        user_result = await mysql_client.get_user_from_db(
            card_number=str(latest_pending["card_number"])
        )
        if user_result.get("success"):
            user_result = user_result.get("user", {})
            try:
                user_id = user_result.get("userId")
                referal_code = user_result.get("referralCode")
            except Exception as e:
                user_id = user_result.get("USER_ID")
                referal_code = user_result.get("REFERAL_CODE")

        await telegram_messaging.send_admin_alert(
            f"Deposit completed: user_id: {user_id}, referal_code: {referal_code}, amount: {transaction_details['amount']} {transaction_details['currency']}\nAvailable Balance: {balance_str}"
        )

    else:
        logger.warning(
            f"Amount mismatch for deposit {latest_pending['tid']}: "
            f"expected {expected_final}, got {transaction_details['amount']}"
        )


class LoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        logger.info(f"Method: {request.method}")
        logger.info(f"Path: {request.url.path}")
        logger.info(f"Headers: {dict(request.headers)}")
        logger.info(f"Query params: {dict(request.query_params)}")
        response = await call_next(request)
        return response


# Register the middleware with the app
app.add_middleware(LoggingMiddleware)


async def check_and_handle_quantum_balance(interlace_client, nova_client):
    """
    Check quantum account balance and trigger withdrawal if below threshold.
    Uses Redis locking to prevent race conditions when multiple requests try to
    trigger withdrawals simultaneously.

    Args:
        interlace_client: The Interlace API client instance
        nova_client: The Nova API client instance
    """
    if not redis_client or not REDIS_AVAILABLE:
        logger.error("Redis not available for quantum balance check locking")
        return

    lock_key = "quantum_balance_check_lock"
    lock_timeout = 30  # Lock timeout in seconds

    try:
        # Try to acquire the lock by checking if it exists first
        lock_exists = await redis_client.get(lock_key)
        if lock_exists:
            logger.info("Another quantum balance check is in progress")
            return

        # Set the lock with expiration
        await redis_client.set(lock_key, "1", ex=lock_timeout)

        try:
            # Get quantum account balance
            balances = interlace_client.funding.list_all_balances()
            quantum_balance = 0
            for bal in balances:
                if bal["walletType"] == "QuantumAccount" and bal["currency"] == "USD":
                    quantum_balance = float(bal["available"])
                    break

            # Get threshold and max pool from config
            threshold = INTERLACE_POOL_THRESHOLD
            max_pool = INTERLACE_POOL_MAX
            fee_percent_interlace = NOVA_DEPOSITS_CONFIG.get("fee_percent_interlace", 0)

            # If balance is below threshold, trigger withdrawal
            if quantum_balance < threshold:
                # Calculate withdrawal amount (up to max_pool)
                withdrawal_amount = int(min(max_pool - quantum_balance, max_pool) / (
                    1 - fee_percent_interlace
                ))

                # Get destination address from config
                destination = INTERLACE_ADDRESS
                if not destination:
                    logger.error(
                        "No destination address configured for quantum withdrawals"
                    )
                    return

                try:
                    # Create pool_refill document
                    pool_refill_doc = {
                        "amount": withdrawal_amount,
                        "status": "Processing",
                        "created_at": datetime.now(timezone.utc),
                        "quantum_balance_before": quantum_balance,
                        "threshold": threshold,
                        "max_pool": max_pool,
                    }

                    # Insert pool_refill document
                    pool_refill_id = (
                        await mongo_client_instance.pool_refills.insert_one(
                            pool_refill_doc
                        )
                    )
                    logger.info(
                        f"Created pool refill document with ID: {pool_refill_id.inserted_id}"
                    )

                    # In testing mode, simulate AssetsDeposit notification
                    if TESTING_MODE:
                        # Create simulated AssetsDeposit notification
                        simulated_notification = {
                            "id": f"sim_{datetime.now(timezone.utc).timestamp()}",
                            "businessType": "AssetsDeposit",
                            "data": {
                                "amount": str(withdrawal_amount),
                                "createTime": datetime.now(timezone.utc).isoformat(),
                                "currency": "USD",
                                "type": "quantum_pool_refill",
                            },
                            "sign": "simulated_signature",
                        }

                        # Process the simulated notification
                        withdrawal_response = await process_notification(
                            request=None, payload=simulated_notification, method="POST"
                        )

                    else:
                        # try:
                        # # Create withdrawal from Nova
                        # withdrawal_response = nova_client.create_withdrawal(
                        #     dchain="trc20usdt",
                        #     destination=destination,
                        #     amount=withdrawal_amount,
                        # )
                        # except Exception as e:
                        e = "error"
                        await telegram_messaging.send_admin_alert(
                            f"Error initiating quantum pool withdrawal: {e}\n"
                            f"Withdrawal amount: *{withdrawal_amount}*\n"
                            f"Destination: {destination}\n"
                        )
                        await telegram_messaging.send_admin_alert(
                            f"{withdrawal_amount}"
                        )
                        logger.error(
                            f"Error initiating quantum pool withdrawal: {e}"
                        )
                    logger.info(
                        f"Initiated quantum pool withdrawal: {withdrawal_response}"
                    )

                except Exception as e:
                    logger.error(f"Error initiating quantum pool withdrawal: {e}")

        finally:
            # Always release the lock when done
            await redis_client.delete(lock_key)

    except Exception as e:
        logger.error(f"Error in quantum balance check: {e}")
        # Try to release the lock in case of error
        try:
            await redis_client.delete(lock_key)
        except Exception as lock_err:
            logger.error(f"Error releasing quantum balance check lock: {lock_err}")


async def check_quantum_balances(interlace_client):
    """
    Check quantum account balances for both USDT and USD.

    Args:
        interlace_client: The Interlace API client instance

    Returns:
        tuple: (usdt_balance, usd_balance) - The available balances for USDT and USD
    """
    try:
        balances = interlace_client.funding.list_all_balances()
        usdt_balance = 0
        usd_balance = 0

        for bal in balances:
            if bal["walletType"] == "QuantumAccount":
                if bal["currency"] == "USDT":
                    usdt_balance = float(bal["available"])
                elif bal["currency"] == "USD":
                    usd_balance = float(bal["available"])

        logger.info(
            f"Quantum account balances - USDT: {usdt_balance}, USD: {usd_balance}"
        )
        return usdt_balance, usd_balance

    except Exception as e:
        logger.error(f"Error checking quantum account balances: {e}")
        return 0, 0


@app.post("/telegram-webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram webhook updates."""
    try:
        # Verify webhook secret token
        secret_token = request.headers.get("x-telegram-bot-api-secret-token")
        if secret_token != config.WEBHOOK_SECRET:
            logger.warning("Invalid webhook secret token")
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid webhook secret token"}
            )

        # Get update data
        update_data = await request.json()
        logger.info(f"Received webhook update: {update_data.get('update_id')}")

        # Ensure bot application is initialized
        if not hasattr(app.state, "bot_application"):
            logger.info("Initializing bot application for webhook")
            application = setup_application()
            if application:
                try:
                    # Initialize the application
                    await application.initialize()

                    # Admin-only command handlers
                    admin_filter = filters.Chat(chat_id=config.ADMIN_CHAT_ID)

                    # Register handlers
                    application.add_handler(CommandHandler("start", start))
                    application.add_handler(
                        CommandHandler("send", send_command, filters=admin_filter)
                    )
                    application.add_handler(
                        CommandHandler(
                            "send_all", send_all_command, filters=admin_filter)
                    )
                    application.add_handler(
                        CommandHandler("cancel", cancel_command, filters=admin_filter)
                    )
                    application.add_handler(
                        CallbackQueryHandler(language_selection, pattern="^lang_")
                    )
                    application.add_handler(
                        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
                    )
                    application.add_error_handler(error_handler)

                    # Set up menu commands
                    asyncio.create_task(setup_menu_commands(application))

                    app.state.bot_application = application
                    logger.info("Bot application initialized successfully")
                except Exception as e:
                    logger.error(
                        f"Error initializing bot application: {e}",
                        exc_info=True)
                    return JSONResponse(
                        status_code=500,
                        content={"error": "Failed to initialize bot application"}
                    )
            else:
                logger.error("Failed to create bot application")
                return JSONResponse(
                    status_code=500,
                    content={"error": "Bot application not initialized"}
                )

        # Process the update
        try:
            update = Update.de_json(update_data, app.state.bot_application.bot)
            await app.state.bot_application.process_update(update)
            logger.info(f"Successfully processed update: {update.update_id}")
            return JSONResponse(content={"status": "ok"})
        except Exception as e:
            logger.error(f"Error processing update: {e}", exc_info=True)
            return JSONResponse(
                status_code=500,
                content={"error": "Error processing update"}
            )

    except Exception as e:
        logger.error(f"Error in webhook handler: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error"}
        )


# --- Main execution block ---
if __name__ == "__main__":
    # Configure logging basics if running directly
    logger.info(f"Starting FastAPI server directly on port {config.API_PORT}...")

    # Development mode - DO NOT USE IN PRODUCTION
    uvicorn.run(
        "app:app",
        host="0.0.0.0",  # Listen on all interfaces
        port=config.API_PORT,
        log_level="info",
        reload=False,  # Disable reload for production
        workers=1,  # Start with single worker
        limit_concurrency=1000,  # Limit concurrent connections
        backlog=2048,  # Increase backlog for better connection handling
    )

    # FOR PRODUCTION, comment out the above and run with:
    # gunicorn app:app -k uvicorn.workers.UvicornWorker -w 4 -b
    # 0.0.0.0:{config.API_PORT} --max-requests 1000 --max-requests-jitter 50
    # --worker-connections 1000

    # --- TEST ENDPOINTS: Only available in TESTING_MODE ---
    # --- TEST ENDPOINTS: Only available in TESTING_MODE ---
