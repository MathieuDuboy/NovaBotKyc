import json
import logging
import os

from utils.logger import logger

# Determine the script directory (assuming config.py is in the root)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# === Internal Logging Configuration for Nova ===

# Define log directory relative to the config.py location (assumes running
# # from /home/Nova)
# LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
# if not os.path.exists(LOG_DIR):
#     os.makedirs(LOG_DIR)

# # Log file path (ensuring logs remain internal)
# LOG_FILE = os.path.join(LOG_DIR, 'nova.log')

# # Configure logging: Only internal handlers are added (file and console)
# # with appropriate formatting.
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
#     handlers=[
#         logging.FileHandler(LOG_FILE),
#         logging.StreamHandler()
#     ]
# )

# # Ensure that log propagation is disabled for our root logger to avoid
# # accidental external log forwarding.
# logging.getLogger().propagate = False

# === End of Internal Logging Configuration ===

# --- Configuration Loading ---
params = {}
try:
    # Load params relative to the script directory
    config_path = os.path.join(SCRIPT_DIR, 'params.json')
    if not os.path.exists(config_path):
        # Fallback: try loading from CWD if not found next to script
        # This might be less reliable depending on execution context
        config_path = 'params.json'
        if not os.path.exists(config_path):
            raise FileNotFoundError(
                "params.json not found near script or in CWD."
            )

    with open(config_path, 'r') as f:
        params = json.load(f)
    logger.info(f"Configuration loaded successfully from {config_path}")

except FileNotFoundError:
    logger.critical(
        f"CRITICAL: params.json not found near {SCRIPT_DIR} "
        f"or current directory. Please create it."
    )
    exit(1)  # Exit if config is essential
except json.JSONDecodeError:
    logger.critical("CRITICAL: params.json is not valid JSON.")
    exit(1)  # Exit if config is corrupted
except Exception as e:
    logger.critical(f"CRITICAL: Unexpected error loading params.json: {e}")
    exit(1)


# --- Extract Specific Config Sections ---
TELEGRAM_CONFIG = params.get('telegram', {})
BOT_ID = TELEGRAM_CONFIG.get('bot_id', {}).get(TELEGRAM_CONFIG.get('env', 'prod'), 0)
PUBLIC_KEY_HEX = TELEGRAM_CONFIG.get(
    'public_key_hex',
    "e7bf03a2fa4602af4580703d88dda5bb59f32ed8b02a56c187fe7d34caed242d")
TELEGRAM_MINIAPP_TOKEN = TELEGRAM_CONFIG.get('miniapp_token', '')
ADMIN_CHAT_ID = TELEGRAM_CONFIG.get('admin_chat_id', 0)
# Admins autorisés au multi-enrollment (création de N KYC + liens). Liste
# `telegram.admin_chat_ids` (+ admin_chat_id pour rétro-compat).
ADMIN_CHAT_IDS = set()
for _x in ([ADMIN_CHAT_ID] + list(TELEGRAM_CONFIG.get('admin_chat_ids') or [])):
    try:
        if int(_x):
            ADMIN_CHAT_IDS.add(int(_x))
    except (TypeError, ValueError):
        pass
GOOGLE_SHEETS_CONFIG = params.get('google_sheets', {})
API_CONFIG = params.get('api', {})
PATHS_CONFIG = params.get('paths', {})
MONGODB_CONFIG = params.get('mongodb', {})
REDIS_CONFIG = params.get('redis', {})
WEBHOOK_CONFIG = TELEGRAM_CONFIG.get('webhook', {})
CONCURRENCY_CONFIG = params.get('concurrency', {})
MYSQL_CONFIG = params.get('mysql', {})
INTERLACE_CONFIG = params.get('interlace', {})
NOVA_API_CONFIG = params.get('nova_api', {})
NOVA_DEPOSITS_CONFIG = params.get('nova_deposits', {})
NOVA_CONSUMPTION_FEE_T = params.get('interlace_fees', {}).get('consumption_t', 50)
# --- Field Mapping from google_sheets.field_names ---
FIELD_MAPPING = {entry["api"]: entry["sheet"]
                 for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])}
REVERSE_FIELD_MAPPING = {
    entry["sheet"]: entry["api"]
    for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])
}
INTERNAL_TO_SHEET_MAPPING = {
    entry["internal"]: entry["sheet"]
    for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])
}
INTERNAL_TO_API_MAPPING = {
    entry["internal"]: entry["api"]
    for entry in GOOGLE_SHEETS_CONFIG.get("field_names", [])
}

# --- Resolve Paths and Constants ---
BOT_TOKEN = TELEGRAM_CONFIG.get('bot_token')
ID_CHANNEL = TELEGRAM_CONFIG.get('id_channel')
PHONE_NUMBER = TELEGRAM_CONFIG.get('phone_number')
EMAIL = TELEGRAM_CONFIG.get('email')
SPREADSHEET_ID = GOOGLE_SHEETS_CONFIG.get('spreadsheet_id')
# Onglet du Google Sheet pour les users (distinct par bot, classeur partagé).
USERS_SHEET = GOOGLE_SHEETS_CONFIG.get('users_sheet', 'users')
CREDENTIALS_PATH_REL = GOOGLE_SHEETS_CONFIG.get('credentials_path')
SCOPES = GOOGLE_SHEETS_CONFIG.get(
    'scopes',
    ['https://www.googleapis.com/auth/spreadsheets']
)
API_PORT = API_CONFIG.get('port', 3001)
ALLOWED_ORIGINS = API_CONFIG.get('allowed_origins', '*')
# Token admin pour les endpoints sensibles (ex: finalize_kyc). Si vide/placeholder
# -> endpoint refusé (prod-safe). En sandbox : régler api.admin_token dans params.
ADMIN_API_TOKEN = API_CONFIG.get('admin_token')
MINIAPP_URL = API_CONFIG.get(
    'miniapp_url',
    'http://localhost:3001'
)
API_VERSION = API_CONFIG.get(
    'version',
    '1.0.0'
)
API_ENV = API_CONFIG.get(
    'env',
    'production'
)
API_BASE = API_CONFIG.get(
    'api_base',
    '/api'
)
MINI_APP_DIR_REL = PATHS_CONFIG.get(
    'mini_app_dir',
    './miniapp'
)
LANG_DIR_REL = PATHS_CONFIG.get(
    'lang_dir',
    './telegram_bot/languages'
)

# MongoDB Configuration
MONGODB_URI = MONGODB_CONFIG.get('uri', 'mongodb://localhost:27017')
MONGODB_DB_NAME = MONGODB_CONFIG.get('db_name', 'nova')
MAX_MONGODB_POOL_SIZE = MONGODB_CONFIG.get('pool_size', 50)
MONGODB_COLLECTIONS = MONGODB_CONFIG.get('collections', {})

# Ensure MongoDB URI is properly formatted
if not MONGODB_URI.startswith('mongodb://'):
    MONGODB_URI = f'mongodb://{MONGODB_URI}'

# Add MongoDB URI to environment variables for compatibility
os.environ['MONGODB_URI'] = MONGODB_URI
os.environ['MONGODB_DB_NAME'] = MONGODB_DB_NAME

# Redis Configuration (with defaults)
REDIS_HOST = REDIS_CONFIG.get('host', 'localhost')
REDIS_PORT = REDIS_CONFIG.get('port', 6379)
REDIS_DB = REDIS_CONFIG.get('db', 0)
REDIS_URI = (
    f"redis://{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"
)
REDIS_USERNAME = REDIS_CONFIG.get('username', 'nova_user')
REDIS_PASSWORD = REDIS_CONFIG.get('password', '')

# Webhook Configuration (with defaults)
USE_WEBHOOK = WEBHOOK_CONFIG.get('enabled', False)
WEBHOOK_URL = WEBHOOK_CONFIG.get(
    'url', 'https://yourdomain.com/telegram-webhook'
)
WEBHOOK_PATH = WEBHOOK_CONFIG.get('path', '/telegram-webhook')
WEBHOOK_LISTEN = WEBHOOK_CONFIG.get('listen', '0.0.0.0')
WEBHOOK_PORT = WEBHOOK_CONFIG.get('port', 8443)
WEBHOOK_SECRET = WEBHOOK_CONFIG.get('secret', 'your_secret_token')

# Concurrency and Performance Configuration (with production defaults)
MAX_REDIS_CONNECTIONS = CONCURRENCY_CONFIG.get('redis_connections', 300)
CONCURRENT_UPDATES = CONCURRENCY_CONFIG.get('concurrent_updates', 50)
RATE_LIMIT_WINDOW_SIZE = CONCURRENCY_CONFIG.get('rate_limit_window', 60)  # seconds
WORKER_COUNT = CONCURRENCY_CONFIG.get('worker_count', 4)  # For Gunicorn
MAX_REQUESTS_PER_WORKER = CONCURRENCY_CONFIG.get('max_requests_per_worker', 1000)
WORKER_CONNECTIONS = CONCURRENCY_CONFIG.get('worker_connections', 1000)

# Resolve absolute paths safely
MINI_APP_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, MINI_APP_DIR_REL))
LANG_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, LANG_DIR_REL))
ABS_CREDENTIALS_PATH = os.path.abspath(
    os.path.join(SCRIPT_DIR, CREDENTIALS_PATH_REL)
) if CREDENTIALS_PATH_REL else None

# Tronscan settings
TRONSCAN_API_KEY = params.get("tronscan", {}).get("api_key", "")
TRONSCAN_BASE_URL = params.get("tronscan", {}).get(
    "base_url", "https://apilist.tronscan.org/api/")

# MySQL settings
MYSQL_HOST = MYSQL_CONFIG.get('host', 'localhost')
MYSQL_PORT = MYSQL_CONFIG.get('port', 3306)
MYSQL_USER = MYSQL_CONFIG.get('user', 'root')
MYSQL_PASSWORD = MYSQL_CONFIG.get('password', '')
MYSQL_DATABASE = MYSQL_CONFIG.get('database', 'nova')
MYSQL_CHARSET = MYSQL_CONFIG.get('charset', 'utf8mb4')
MYSQL_POOL_SIZE = MYSQL_CONFIG.get(
    'pool_size', CONCURRENCY_CONFIG.get(
        'mysql_connections', 50))
MYSQL_POOL_RECYCLE = MYSQL_CONFIG.get('pool_recycle', 3600)
MYSQL_CONNECT_TIMEOUT = MYSQL_CONFIG.get('connect_timeout', 10)

# Interlace API settings
INTERLACE_MODE = INTERLACE_CONFIG.get('mode', 'dev')
INTERLACE_DEV = INTERLACE_CONFIG.get('dev', {})
INTERLACE_PROD = INTERLACE_CONFIG.get('prod', {})

# Interlace API Configuration
INTERLACE_API_KEY = INTERLACE_DEV.get(
    'client_id') if INTERLACE_MODE == 'dev' else INTERLACE_PROD.get('client_id')
INTERLACE_API_SECRET = INTERLACE_DEV.get(
    'client_secret') if INTERLACE_MODE == 'dev' else INTERLACE_PROD.get('client_secret')
# Secret de vérification de signature des webhooks (Dashboard > Integration
# Settings). À défaut, on retombe sur le client_secret API (souvent identique).
_IL_ACTIVE = INTERLACE_DEV if INTERLACE_MODE == 'dev' else INTERLACE_PROD
INTERLACE_WEBHOOK_SECRET = _IL_ACTIVE.get('webhook_secret') or INTERLACE_API_SECRET

# Nova API settings
NOVA_API_ACCESS_KEY = NOVA_API_CONFIG.get('access_key', '')
NOVA_API_SECRET_KEY = NOVA_API_CONFIG.get('secret_key', '')
NOVA_API_BASE_URL = NOVA_API_CONFIG.get('base_url', 'https://api.novaexchange.com')
NOVA_API_WS_URL = NOVA_API_CONFIG.get('ws_url', 'wss://ws.novaexchange.com')
NOVA_API_WS_PATH = NOVA_API_CONFIG.get('ws_path', '/zsu/ws/v1')

# Interlace pool configuration
INTERLACE_POOL_CONFIG = params.get('interlace_pool', {})
INTERLACE_POOL_THRESHOLD = INTERLACE_POOL_CONFIG.get('threshold', 5000)
INTERLACE_POOL_MAX = INTERLACE_POOL_CONFIG.get('max_pool', 30000)
INTERLACE_ADDRESS = params.get('interlace_address', {}).get('destination')

# Testing configuration
TESTING_MODE = params.get('testing', False)
TESTING_URL = params.get('testing_url', '')

# Helper function to get config values with defaults


def get(param_path, default=None):
    """
    Get a configuration parameter by dot notation path.
    Example: get('telegram.bot_token')

    Args:
        param_path (str): Dot notation path to parameter
        default: Default value if parameter not found

    Returns:
        Parameter value or default if not found
    """
    keys = param_path.split('.')
    value = params
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


# --- Pre-run Checks (moved here for early exit) ---
if not BOT_TOKEN:
    logger.warning(
        "Telegram BOT_TOKEN is missing in params.json. "
        "Bot features will be disabled."
    )

if not SPREADSHEET_ID or not ABS_CREDENTIALS_PATH:
    logger.warning(
        "Google Sheets SPREADSHEET_ID or CREDENTIALS_PATH is missing "
        "or invalid in params.json. Sheets features disabled."
    )

if not os.path.isdir(MINI_APP_DIR):
    logger.warning(
        f"Mini App directory not found at resolved path: {MINI_APP_DIR}. "
        f"Static file serving might fail."
    )

if not os.path.isdir(LANG_DIR):
    logger.warning(
        f"Language directory not found at resolved path: {LANG_DIR}. "
        f"Language features might fail."
    )

# Check for MongoDB configuration
if not MONGODB_CONFIG:
    logger.warning(
        "MongoDB configuration section missing in params.json. "
        "Using defaults (localhost:27017, db 'telegram_bot')."
    )

# Set to True to run the Telegram bot as a background task with FastAPI
RUN_TELEGRAM_BOT = True
