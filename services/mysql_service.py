import asyncio  # Added for the example code at the bottom
import socket
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

# Import config to access MySQL settings
import config
from config import FIELD_MAPPING, REVERSE_FIELD_MAPPING
from utils.logger import logger

# Try to import pandas (optional dependency)
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    logger.warning(
        "Pandas not found. DataFrame operations will be unavailable. "
        "Install with: pip install pandas"
    )

# Try to import MySQL modules
try:
    import aiomysql
    import mysql.connector
    from mysql.connector import pooling

    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    logger.warning(
        "MySQL driver not found. Install with: "
        "pip install mysql-connector-python aiomysql"
    )

# Connection retry settings
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds
CONNECTION_TIMEOUT = 30  # seconds


class MySQLClient:
    """Client for interacting with MySQL database.
    Supports both synchronous and asynchronous operations.
    """

    _instance = None  # Singleton instance
    _sync_pool = None  # Synchronous connection pool
    _async_pool = None  # Asynchronous connection pool

    def __new__(cls):
        """Implement the Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(MySQLClient, cls).__new__(cls)
            # Initialize the connection pools if MySQL is available
            if MYSQL_AVAILABLE:
                cls._instance._init_sync_pool()
        return cls._instance

    def _init_sync_pool(self):
        """Initialize the synchronous connection pool."""
        if not MYSQL_AVAILABLE:
            logger.warning("MySQL module not available, sync pool not initialized")
            return

        try:
            if self._sync_pool is None:
                # MySQL connector pool size must be between 1 and 32
                pool_size = min(32, max(1, config.MYSQL_POOL_SIZE))
                if pool_size != config.MYSQL_POOL_SIZE:
                    logger.warning(
                        f"Adjusted MySQL pool size from {config.MYSQL_POOL_SIZE} "
                        f"to {pool_size} (must be between 1 and 32)"
                    )

                self._sync_pool = pooling.MySQLConnectionPool(
                    pool_name="mysql_pool",
                    pool_size=pool_size,
                    host=config.MYSQL_HOST,
                    port=config.MYSQL_PORT,
                    user=config.MYSQL_USER,
                    password=config.MYSQL_PASSWORD,
                    database=config.MYSQL_DATABASE,
                    charset=config.MYSQL_CHARSET,
                    connection_timeout=CONNECTION_TIMEOUT,
                    use_pure=True,  # Use pure Python implementation
                    get_warnings=True,
                    raise_on_warnings=True,
                    autocommit=True,
                    pool_reset_session=True,
                )
                logger.info(
                    f"MySQL sync pool initialized: "
                    f"host={config.MYSQL_HOST}, "
                    f"database={config.MYSQL_DATABASE}"
                )
        except Exception as e:
            logger.error(f"Error initializing MySQL sync pool: {e}")
            self._sync_pool = None

    async def _init_async_pool(self):
        """Initialize the asynchronous connection pool."""
        if not MYSQL_AVAILABLE:
            logger.warning("MySQL module not available, async pool not initialized")
            return

        try:
            if self._async_pool is None:
                # aiomysql pool size constraint
                pool_size = min(32, max(1, config.MYSQL_POOL_SIZE))
                if pool_size != config.MYSQL_POOL_SIZE:
                    logger.warning(
                        f"Adjusted MySQL async pool size from "
                        f"{config.MYSQL_POOL_SIZE} to {pool_size} "
                        f"(must be between 1 and 32)"
                    )

                self._async_pool = await aiomysql.create_pool(
                    host=config.MYSQL_HOST,
                    port=config.MYSQL_PORT,
                    user=config.MYSQL_USER,
                    password=config.MYSQL_PASSWORD,
                    db=config.MYSQL_DATABASE,
                    charset=config.MYSQL_CHARSET,
                    autocommit=True,
                    maxsize=pool_size,
                    minsize=1,
                    connect_timeout=CONNECTION_TIMEOUT,
                    echo=False,
                    pool_recycle=3600,  # Recycle connections after 1 hour
                    ssl=None,
                )
                logger.info(
                    f"MySQL async pool initialized: "
                    f"host={config.MYSQL_HOST}, "
                    f"database={config.MYSQL_DATABASE}"
                )
        except Exception as e:
            logger.error(f"Error initializing MySQL async pool: {e}")
            self._async_pool = None

    async def _execute_with_retry(self, query_func, *args, **kwargs):
        """Execute a query with retry logic."""
        last_error = None
        for attempt in range(MAX_RETRIES):
            try:
                return await query_func(*args, **kwargs)
            except (ConnectionResetError, socket.error) as e:
                last_error = e
                if attempt < MAX_RETRIES - 1:
                    logger.warning(
                        f"Connection reset, retrying in {RETRY_DELAY} seconds "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    await asyncio.sleep(RETRY_DELAY)
                    # Reinitialize pool if needed
                    if self._async_pool is None:
                        await self._init_async_pool()
                else:
                    logger.error(
                        f"Max retries ({MAX_RETRIES}) reached. Last error: {e}"
                    )
                    raise
            except Exception as e:
                logger.error(f"Unexpected error during query execution: {e}")
                raise
        raise last_error

    @contextmanager
    def get_connection(self):
        """Get a synchronous connection from the pool.

        Usage:
            with mysql_client.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM users")
                results = cursor.fetchall()
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if self._sync_pool is None:
            self._init_sync_pool()
            if self._sync_pool is None:
                raise ConnectionError("Failed to initialize MySQL connection pool")

        conn = None
        try:
            conn = self._sync_pool.get_connection()
            yield conn
        except Exception as e:
            logger.error(f"Error getting MySQL connection: {e}")
            raise
        finally:
            if conn:
                conn.close()

    async def get_async_connection(self):
        """Get an asynchronous connection from the pool.

        Note: This doesn't use a context manager since it's intended
        to be used with async/await syntax.

        Usage:
            conn = await mysql_client.get_async_connection()
            try:
                async with conn.cursor() as cursor:
                    await cursor.execute("SELECT * FROM users")
                    results = await cursor.fetchall()
            finally:
                conn.close()
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if self._async_pool is None:
            await self._init_async_pool()
            if self._async_pool is None:
                raise ConnectionError(
                    "Failed to initialize MySQL async connection pool"
                )

        try:
            return await self._async_pool.acquire()
        except Exception as e:
            logger.error(f"Error getting MySQL async connection: {e}")
            raise

    def release_async_connection(self, conn):
        """Release an asynchronous connection back to the pool."""
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if self._async_pool is not None and conn:
            self._async_pool.release(conn)

    def execute_query(
        self,
        query: str,
        params: Optional[Union[Dict, List, Tuple]] = None,
        fetch: bool = True,
    ) -> Union[List[Dict[str, Any]], int]:
        """Execute a synchronous SQL query and return the results.

        Args:
            query: SQL query to execute
            params: Query parameters (for parameterized queries)
            fetch: Whether to fetch and return results (True) or
                   just return row count for updates/inserts (False)

        Returns:
            If fetch=True, returns list of dictionaries (rows)
            If fetch=False, returns affected row count
        """
        with self.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute(query, params or ())

                if fetch:
                    result = cursor.fetchall()
                    return result
                else:
                    conn.commit()
                    return cursor.rowcount
            except Exception as e:
                logger.error(f"SQL error: {e}, Query: {query}, Params: {params}")
                conn.rollback()
                raise
            finally:
                cursor.close()

    async def execute_query_async(
        self,
        query: str,
        params: Optional[Union[Dict, List, Tuple]] = None,
        fetch: bool = True,
    ) -> Union[List[Dict[str, Any]], int]:
        """Execute an asynchronous SQL query with retry logic."""

        async def _execute():
            conn = await self.get_async_connection()
            try:
                async with conn.cursor(aiomysql.DictCursor) as cursor:
                    await cursor.execute(query, params or ())
                    if fetch:
                        result = await cursor.fetchall()
                        return result
                    else:
                        await conn.commit()
                        return cursor.rowcount
            except Exception as e:
                await conn.rollback()
                raise
            finally:
                self.release_async_connection(conn)

        return await self._execute_with_retry(_execute)

    def read_sql(
        self,
        query: str,
        params: Optional[Union[Dict, List, Tuple]] = None,
    ):
        """Execute a query and return the results as a pandas DataFrame.

        This is a wrapper around pandas.read_sql that uses our connection pool.

        Args:
            query: SQL query to execute
            params: Query parameters (for parameterized queries)

        Returns:
            pandas DataFrame with query results or list of dicts if pandas not available
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if not PANDAS_AVAILABLE:
            logger.warning(
                "Pandas not available, returning list of dictionaries instead of DataFrame"
            )
            return self.execute_query(query, params)

        with self.get_connection() as conn:
            try:
                return pd.read_sql(query, conn, params=params)
            except Exception as e:
                logger.error(f"Error reading SQL into DataFrame: {e}")
                raise

    async def read_sql_async(
        self,
        query: str,
        params: Optional[Union[Dict, List, Tuple]] = None,
    ):
        """Execute a query asynchronously and return results as a pandas DataFrame.

        Args:
            query: SQL query to execute
            params: Query parameters (for parameterized queries)

        Returns:
            pandas DataFrame with query results or list of dicts if pandas not available
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        results = await self.execute_query_async(query, params)

        if not PANDAS_AVAILABLE:
            logger.warning(
                "Pandas not available, returning list of dictionaries instead of DataFrame"
            )
            return results

        # Convert the list of dictionaries to a pandas DataFrame
        return pd.DataFrame(results) if results else pd.DataFrame()

    def to_sql(
        self,
        df,
        table_name: str,
        if_exists: str = "append",
        index: bool = False,
        chunksize: Optional[int] = None,
    ) -> int:
        """Write records stored in a DataFrame to a SQL database.

        This is a wrapper around pandas.DataFrame.to_sql that uses our connection pool.

        Args:
            df: pandas DataFrame to write to the database
            table_name: Name of SQL table
            if_exists: How to behave if the table already exists:
                       'fail', 'replace', or 'append' (default)
            index: Write DataFrame index as a column
            chunksize: Rows to write at once

        Returns:
            Number of rows affected
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if not PANDAS_AVAILABLE:
            raise ImportError(
                "Pandas not available, to_sql operation cannot be performed"
            )

        try:
            # Create SQLAlchemy engine
            from sqlalchemy import create_engine

            engine = create_engine(
                f"mysql+pymysql://{config.MYSQL_USER}:{config.MYSQL_PASSWORD}@"
                f"{config.MYSQL_HOST}:{config.MYSQL_PORT}/{config.MYSQL_DATABASE}"
            )

            # Use pandas to_sql with SQLAlchemy engine
            return df.to_sql(
                name=table_name,
                con=engine,
                if_exists=if_exists,
                index=index,
                chunksize=chunksize,
            )
        except Exception as e:
            logger.error(f"Error writing DataFrame to SQL: {e}")
            raise

    async def to_sql_async(
        self,
        df,
        table_name: str,
        if_exists: str = "append",
        index: bool = False,
        chunksize: Optional[int] = 1000,
    ) -> int:
        """Write records from a DataFrame to SQL database asynchronously.

        Args:
            df: pandas DataFrame to write to the database
            table_name: Name of SQL table
            if_exists: How to behave if the table already exists:
                       'fail', 'replace', or 'append' (default)
            index: Write DataFrame index as a column
            chunksize: Rows to write at once

        Returns:
            Number of rows affected
        """
        if not MYSQL_AVAILABLE:
            raise ImportError("MySQL module not available")

        if not PANDAS_AVAILABLE:
            raise ImportError(
                "Pandas not available, to_sql_async operation cannot be performed"
            )

        # This is a basic implementation that will generate and execute SQL statements
        # The approach is simplistic compared to pandas.to_sql but works for basic cases

        if if_exists not in ("fail", "replace", "append"):
            raise ValueError("if_exists must be 'fail', 'replace', or 'append'")

        # Check if table exists
        table_exists = await self.execute_query_async(
            "SELECT COUNT(*) as count FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name = %s",
            (config.MYSQL_DATABASE, table_name),
        )
        table_exists = table_exists[0]["count"] > 0 if table_exists else False

        if table_exists and if_exists == "fail":
            raise ValueError(f"Table '{table_name}' already exists")

        if table_exists and if_exists == "replace":
            await self.execute_query_async(f"DROP TABLE {table_name}", fetch=False)
            table_exists = False

        # Create table if it doesn't exist
        if not table_exists:
            # Generate CREATE TABLE SQL based on DataFrame dtypes
            columns = []
            for col, dtype in df.dtypes.items():
                sql_type = "VARCHAR(255)"  # Default
                if pd.api.types.is_integer_dtype(dtype):
                    sql_type = "INT"
                elif pd.api.types.is_float_dtype(dtype):
                    sql_type = "FLOAT"
                elif pd.api.types.is_datetime64_dtype(dtype):
                    sql_type = "DATETIME"
                elif pd.api.types.is_bool_dtype(dtype):
                    sql_type = "BOOLEAN"
                columns.append(f"`{col}` {sql_type}")

            create_sql = f"CREATE TABLE {table_name} ({', '.join(columns)})"
            await self.execute_query_async(create_sql, fetch=False)

        # Insert data
        total_rows = 0

        # If DataFrame is empty, return 0
        if df.empty:
            return 0

        # Process in chunks
        for chunk_start in range(0, len(df), chunksize or len(df)):
            chunk = df.iloc[chunk_start: chunk_start + (chunksize or len(df))]

            # Build the INSERT SQL
            columns = [f"`{col}`" for col in df.columns]
            values = [f"%({col})s" for col in df.columns]
            insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({', '.join(values)})"

            # Execute the INSERT statement
            await self.execute_query_async(
                insert_sql, params=chunk.to_dict(orient="records"), fetch=False
            )

            # Update total_rows
            total_rows += len(chunk)

        return total_rows

    def row_to_api_dict(self, row: dict) -> dict:
        return {REVERSE_FIELD_MAPPING.get(k, k): v for k, v in row.items()}

    def api_dict_to_row(self, api_dict: dict) -> dict:
        return {FIELD_MAPPING.get(k, k): v for k, v in api_dict.items()}

    async def get_user_from_db(
        self, user_id=None, nova_address=None, card_number=None, get_all=False
    ):
        """
        Retrieves user data row from MySQL based on user_id, nova_address, or card_number. If get_all is True, returns all users.
        Returns a dict with 'success', 'user' or 'users', and 'status_code'.
        """
        try:
            if get_all:
                query = "SELECT * FROM users"
                users = await self.execute_query_async(query)
                api_users = [self.row_to_api_dict(u) for u in users]
                return {"success": True, "users": api_users, "status_code": 200}
            # Single user lookup
            query = "SELECT * FROM users WHERE 1=1"
            params = []
            if user_id:
                query += f" AND {FIELD_MAPPING['userId']} = %s"
                params.append(user_id)
            if nova_address:
                query += f" AND {FIELD_MAPPING['novaAddress']} = %s"
                params.append(nova_address)
            if card_number:
                query += f" AND `{FIELD_MAPPING['cardNumber']}` = %s"
                params.append(card_number)
            query += " LIMIT 1"
            users = await self.execute_query_async(query, params)
            if users:
                return {
                    "success": True,
                    "user": self.row_to_api_dict(users[0]),
                    "status_code": 200,
                }
            else:
                return {
                    "success": False,
                    "message": "User not found.",
                    "status_code": 404,
                }
        except Exception as e:
            logger.error(f"Error fetching user from DB: {e}", exc_info=True)
            return {
                "success": False,
                "message": "Server error during DB lookup.",
                "status_code": 500,
            }

    async def get_all_users_from_db(self):
        """
        Returns a list of all users as dicts.
        """
        return await self.get_user_from_db(get_all=True)

    async def check_referral_code_valid_mysql(self, referral_code):
        """Check if a referral code exists and is valid in the referralcodes table."""
        try:
            query = "SELECT * FROM referralcodes WHERE `referal code` = %s AND valid = 1 LIMIT 1"
            result = await self.execute_query_async(query, (referral_code,))
            if result and len(result) > 0:
                row = result[0]
                deposit_fee = float(row.get("deposit fee", 2.5))
                foreign_fee = float(row.get("foregin fee", 2.5))
                return True, deposit_fee, foreign_fee
            return False, None, None
        except Exception as e:
            logger.error(f"Error checking referral code in MySQL: {e}")
            return False, None, None

    async def get_fees_for_user_mysql(self, user_id=None):
        """Get deposit/foreign fees for a user by looking up their referral code in the users table, then fetching fees from referralcodes table (use direct column names for referralcodes)."""
        try:
            user_result = await self.get_user_from_db(user_id=user_id)
            if not user_result or not user_result.get("success"):
                return 2.5, 2.5  # fallback
            user = user_result.get("user", {})
            referral_code = user.get("referralCode") or user.get("referal code")
            if not referral_code:
                return 2.5, 2.5  # fallback
            # Use direct column names for referralcodes
            query = "SELECT * FROM referralcodes WHERE `referal code` = %s AND valid = 1 LIMIT 1"
            result = await self.execute_query_async(query, (referral_code,))
            if result and len(result) > 0:
                row = result[0]
                deposit_fee = float(row.get("deposit fee", 2.5))
                foreign_fee = float(row.get("foregin fee", 2.5))
                return deposit_fee, foreign_fee
            return 2.5, 2.5  # fallback
        except Exception as e:
            logger.error(f"Error fetching fees for user in MySQL: {e}")
            return 2.5, 2.5  # fallback

    async def update_user_field_in_db(self, user_id, field_name, new_value):
        """Update a specific field for a user in the MySQL users table by user_id."""
        try:
            column_name = FIELD_MAPPING.get(field_name, field_name)
            query = f"UPDATE users SET `{column_name}` = %s WHERE {FIELD_MAPPING['userId']} = %s"
            result = await self.execute_query_async(
                query, (new_value, user_id), fetch=False
            )
            return result > 0
        except Exception as e:
            logger.error(
                f"Error updating {field_name} for user {user_id} in MySQL: {e}"
            )
            return False

    async def get_user_row_number(self, user_id):
        """Get the row number (1-based) of a user in the users table."""
        try:
            user_id_col = FIELD_MAPPING["userId"]
            query = f"SELECT ROW_NUMBER() OVER (ORDER BY {user_id_col}) as row_num FROM users WHERE {user_id_col} = %s"
            result = await self.execute_query_async(query, (user_id,))
            if result and len(result) > 0:
                return result[0]["row_num"]
            return None
        except Exception as e:
            logger.error(f"Error getting user row number: {e}")
            return None

    async def get_pool_addresses(self):
        """Get all pool addresses from the users table."""
        try:
            query = "SELECT DISTINCT `nova_address` FROM pool WHERE `nova_address` IS NOT NULL"
            result = await self.execute_query_async(query)
            return [row["nova_address"] for row in result]
        except Exception as e:
            logger.error(f"Error getting pool addresses: {e}")
            return []

    async def add_user_to_db(self, user_data: dict) -> dict:
        """
        Add a new user to the users table.

        Args:
            user_data: Dictionary containing user data with API field names from Telegram bot
                     Expected fields: chatId, username, firstName, lastName, email, phone,
                     referralCode, firstNameChat, lastNameChat, language, CARD ID, nova_address

        Returns:
            dict: {
                'success': bool,
                'message': str,
                'status_code': int
            }
        """
        try:
            logger.info(f"Starting add_user_to_db with data: {user_data}")

            # Map API fields to MySQL columns
            mysql_data = {
                "USER_ID": user_data.get("chatId"),
                "USERNAME": user_data.get("username"),
                "CREATION DATE": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "CARD NAME": user_data.get("firstName"),
                "CARD SURNAME": user_data.get("lastName"),
                "EMAIL": user_data.get("email"),
                "TELEPHONE": user_data.get("phone"),
                "REFERRAL CODE": user_data.get("referralCode"),
                "Telegram FirstName": user_data.get("firstNameChat"),
                "Telegram LastName": user_data.get("lastNameChat"),
                "Telegram LANGUAGE_CODE": user_data.get("language"),
                "CARD ID": user_data.get("CARD ID"),
                "nova_address": user_data.get("nova_address"),
            }

            logger.info(f"Converted data for MySQL: {mysql_data}")

            # Validate required fields
            missing_fields = []
            required_fields = ["USER_ID", "CARD NAME", "CARD SURNAME"]
            for field in required_fields:
                if not mysql_data.get(field):
                    missing_fields.append(field)
                    logger.warning(f"Missing required field: {field}")

            if missing_fields:
                error_msg = f"Missing required fields: {', '.join(missing_fields)}"
                logger.error(error_msg)
                return {"success": False, "message": error_msg, "status_code": 400}

            # Build the INSERT query
            columns = [f"`{col}`" for col in mysql_data.keys()]
            placeholders = ["%s"] * len(columns)
            query = f"INSERT INTO users ({', '.join(columns)}) VALUES ({', '.join(placeholders)})"
            logger.debug(f"Generated SQL query: {query}")
            logger.debug(f"Query parameters: {list(mysql_data.values())}")

            # Execute the INSERT query
            result = await self.execute_query_async(
                query, params=list(mysql_data.values()), fetch=False
            )

            if result > 0:
                success_msg = f"Successfully added new user to database: {user_data.get('chatId')}"
                logger.info(success_msg)
                return {
                    "success": True,
                    "message": "User added successfully",
                    "status_code": 200,
                }
            else:
                error_msg = f"Failed to add user to database: {user_data.get('chatId')}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "message": "Failed to add user",
                    "status_code": 500,
                }

        except Exception as e:
            error_msg = f"Error adding user to database: {e}"
            logger.error(error_msg, exc_info=True)
            return {
                "success": False,
                "message": f"Server error: {str(e)}",
                "status_code": 500,
            }

    # ── interlace_accounts : sous-compte Interlace (sub-merchant) + état KYC ───
    async def upsert_interlace_account(self, user_id: int, **fields) -> int:
        """Crée ou met à jour la ligne interlace_accounts d'un user (clé unique
        USER_ID). Ne touche que les champs fournis (non-None)."""
        allowed = ("account_id", "cardholder_id", "card_id", "card_number",
                   "bin", "kyc_status", "kyc_case_id", "profile_json", "handoff_token")
        sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cols = ["`USER_ID`"] + [f"`{k}`" for k in sets] + ["`created_at`", "`updated_at`"]
        vals = [user_id] + list(sets.values()) + [now, now]
        placeholders = ", ".join(["%s"] * len(vals))
        updates = ", ".join([f"`{k}`=VALUES(`{k}`)" for k in sets]
                            + ["`updated_at`=VALUES(`updated_at`)"])
        query = (f"INSERT INTO interlace_accounts ({', '.join(cols)}) "
                 f"VALUES ({placeholders}) ON DUPLICATE KEY UPDATE {updates}")
        return await self.execute_query_async(query, tuple(vals), fetch=False)

    async def get_interlace_account(self, user_id: int) -> Optional[dict]:
        rows = await self.execute_query_async(
            "SELECT * FROM interlace_accounts WHERE `USER_ID`=%s LIMIT 1", (user_id,))
        return rows[0] if rows else None

    async def get_user_id_by_account_id(self, account_id: str) -> Optional[int]:
        """Reverse lookup pour router un webhook : account_id -> user Telegram."""
        rows = await self.execute_query_async(
            "SELECT `USER_ID` FROM interlace_accounts WHERE `account_id`=%s LIMIT 1",
            (account_id,))
        return rows[0]["USER_ID"] if rows else None

    async def get_user_id_by_cardholder_id(self, cardholder_id: str) -> Optional[int]:
        """Reverse lookup MoR : cardholder_id -> user Telegram (routing webhook KYC)."""
        rows = await self.execute_query_async(
            "SELECT `USER_ID` FROM interlace_accounts WHERE `cardholder_id`=%s LIMIT 1",
            (cardholder_id,))
        return rows[0]["USER_ID"] if rows else None

    async def set_kyc_status(self, account_id: str, status: str,
                             case_id: Optional[str] = None) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if case_id:
            return await self.execute_query_async(
                "UPDATE interlace_accounts SET `kyc_status`=%s, `kyc_case_id`=%s, "
                "`updated_at`=%s WHERE `account_id`=%s",
                (status, case_id, now, account_id), fetch=False)
        return await self.execute_query_async(
            "UPDATE interlace_accounts SET `kyc_status`=%s, `updated_at`=%s "
            "WHERE `account_id`=%s", (status, now, account_id), fetch=False)


# Create a singleton instance to be imported by other modules
mysql_client = MySQLClient()
