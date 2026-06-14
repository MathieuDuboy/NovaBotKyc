import json
import logging
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
import numpy as np
import config
from utils.logger import logger


def convert_objectid(obj):
    if isinstance(obj, dict):
        return {k: convert_objectid(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_objectid(i) for i in obj]
    elif isinstance(obj, ObjectId):
        return str(obj)
    else:
        return obj


class MongoClientWrapper:
    _instance = None
    _initialized = False
    _client = None
    _db = None
    _api_requests_collection = None
    _interlace_notifications = None
    _interlace_transactions = None
    _combined_transactions = None
    _invalid_notifications = None
    _pool_refills = None
    _users = None
    _deposit_timers = None
    _deposit_events = None
    _withdrawal_events = None

    def __new__(cls):
        """Implement the Singleton pattern."""
        if cls._instance is None:
            cls._instance = super(MongoClientWrapper, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the MongoDB client if not already initialized."""
        if self._initialized:
            return

        try:
            # Initialize MongoDB connection
            self._client = AsyncIOMotorClient(
                config.MONGODB_URI,
                maxPoolSize=config.MAX_MONGODB_POOL_SIZE,
                minPoolSize=1,
                maxIdleTimeMS=30000,
                waitQueueTimeoutMS=10000,
                connectTimeoutMS=10000,
                serverSelectionTimeoutMS=5000,
            )

            # Initialize collections
            self._db = self._client[config.MONGODB_DB_NAME]

            # Initialize collection references
            self._api_requests_collection = self._db[
                config.MONGODB_COLLECTIONS["api_requests"]
            ]
            self._interlace_notifications = self._db[
                config.MONGODB_COLLECTIONS["interlace_notifications"]
            ]
            self._interlace_transactions = self._db[
                config.MONGODB_COLLECTIONS["interlace_transactions"]
            ]
            self._combined_transactions = self._db[
                config.MONGODB_COLLECTIONS["combined_transactions"]
            ]
            self._invalid_notifications = self._db[
                config.MONGODB_COLLECTIONS["invalid_notifications"]
            ]
            self._pool_refills = self._db[config.MONGODB_COLLECTIONS["pool_refills"]]
            self._users = self._db[config.MONGODB_COLLECTIONS["users"]]
            self._deposit_timers = self._db[
                config.MONGODB_COLLECTIONS["deposit_timers"]
            ]
            self._deposit_events = self._db[
                config.MONGODB_COLLECTIONS["deposit_events"]
            ]
            self._withdrawal_events = self._db[
                config.MONGODB_COLLECTIONS["withdrawal_events"]
            ]

            self._initialized = True
            logger.info("MongoDB connection and collections initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize MongoDB: {e}")
            raise

    async def initialize(self):
        """Async initialization of MongoDB collections and indexes."""
        if not self._initialized:
            try:
                # Create collections if they don't exist
                existing_collections = await self._db.list_collection_names()
                collections = config.MONGODB_COLLECTIONS

                for collection_name in collections.values():
                    if collection_name not in existing_collections:
                        try:
                            await self._db.create_collection(collection_name)
                            logger.info(f"Created collection: {collection_name}")
                        except Exception as e:
                            logger.error(
                                f"Error creating collection {collection_name}: {e}"
                            )

                # Create indexes
                await self._create_indexes()
                logger.info("MongoDB indexes created successfully")
            except Exception as e:
                logger.error(f"Failed to initialize MongoDB collections: {e}")
                raise

    async def _create_indexes(self):
        """Create necessary indexes for collections"""
        try:
            await self._users.create_index("chat_id", unique=True)
            await self._api_requests_collection.create_index("timestamp")
            await self._api_requests_collection.create_index("ip")
            await self._interlace_transactions.create_index(
                [("transaction_id", 1), ("timestamp", -1)]
            )
            await self._interlace_notifications.create_index("timestamp")
            await self._interlace_notifications.create_index("type")
            await self._interlace_notifications.create_index("chat_id")
            await self._combined_transactions.create_index(
                [("transaction_id", 1), ("timestamp", -1)]
            )
            await self._combined_transactions.create_index("card_id")
            await self._invalid_notifications.create_index("timestamp")
            await self._pool_refills.create_index("timestamp")
        except Exception as e:
            logger.error(f"Error creating MongoDB indexes: {e}")
            raise

    async def close(self):
        """Close the MongoDB connection"""
        if self._client:
            self._client.close()
            logger.info("MongoDB connection closed")

    @property
    def client(self):
        """Get the MongoDB client instance"""
        return self._client

    @property
    def db(self):
        """Get the MongoDB database instance"""
        return self._db

    @property
    def api_requests_collection(self):
        """Get the API requests collection reference"""
        return self._api_requests_collection

    @property
    def interlace_notifications(self):
        """Get the interlace notifications collection reference"""
        return self._interlace_notifications

    @property
    def interlace_transactions(self):
        """Get the interlace transactions collection reference"""
        return self._interlace_transactions

    @property
    def combined_transactions(self):
        """Get the combined transactions collection reference"""
        return self._combined_transactions

    @property
    def invalid_notifications(self):
        """Get the invalid notifications collection reference"""
        return self._invalid_notifications

    @property
    def pool_refills(self):
        """Get the pool refills collection reference"""
        return self._pool_refills

    @property
    def users(self):
        """Get the users collection reference"""
        return self._users

    @property
    def deposit_timers(self):
        """Get the deposit timers collection reference"""
        return self._deposit_timers

    @property
    def deposit_events(self):
        """Get the deposit events collection reference"""
        return self._deposit_events

    @property
    def withdrawal_events(self):
        """Get the withdrawal events collection reference"""
        return self._withdrawal_events

    async def get_card_transactions(self, card_id: str):
        """
        Fetches the most recent transactions for a given card_id from the
        combined_transactions collection, grouped by tid (latest per tid).
        Excludes transactions where createCard is in the clientTransactionId.
        """
        if self.combined_transactions is None:
            return []
        pipeline = [
            {
                "$match": {
                    "cardId": card_id,
                    "clientTransactionId": {
                        "$not": {"$regex": "createCard"}
                    },
                    "$or": [
                        {"type": "deposit"},
                        {"transaction_type": {"$in": [
                            "Consumption",
                            "Reversal",
                            "Credit"
                        ]}}
                    ]
                }
            },
            {"$sort": {"tid": 1, "timestamp": -1}},
            {"$group": {"_id": "$tid", "doc": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$doc"}},
            {"$sort": {"timestamp": -1}}
        ]
        cursor = self.combined_transactions.aggregate(pipeline)
        transactions = [tx async for tx in cursor]
        for tx in transactions:
            if "transaction_type" in tx.keys():
                tx["type"] = tx["transaction_type"]
            if tx["type"].lower() in ["reversal", "credit"]:
                tx["amount"] = np.abs(tx["amount"]) * -1
                tx["transaction_amount"] = np.abs(tx["transaction_amount"]) * -1

        return convert_objectid(transactions)

    async def log_api_request(self, request_data):
        """
        Log API request to MongoDB.
        """
        if self.api_requests_collection is None:
            return
        try:
            request_data["timestamp"] = datetime.now().isoformat()
            await self.api_requests_collection.insert_one(request_data)
        except Exception as e:
            logger.error(f"Error logging API request: {e}")

    async def process_api_request_batch(self, redis_client=None):
        """
        Process a batch of API requests from Redis queue.
        """
        if redis_client is None or self.api_requests_collection is None:
            return
        try:
            pipe = await redis_client.pipeline()
            pipe.lrange("api_request_queue", 0, 49)
            pipe.ltrim("api_request_queue", 50, -1)
            results = await pipe.execute()
            items = results[0]
            if not items:
                return
            docs = []
            for item in items:
                try:
                    doc = json.loads(item)
                    if isinstance(doc, dict):
                        docs.append(doc)
                except BaseException:
                    continue
            if docs:
                await self.api_requests_collection.insert_many(docs)
        except Exception as e:
            logger.error(f"Error processing API request batch: {e}")

    # --- Deposit Timers (Persistent Address Pool/Single Tracking) ---
    async def get_deposit_timer(self, user_id):
        if not self._initialized:
            return None
        query = {"user_id": user_id, "active": True}
        return await self.deposit_timers.find_one(query)

    async def is_address_reserved(self, address):
        if not self._initialized:
            return False
        query = {"address": address, "active": True, "reserved": True}
        doc = await self.deposit_timers.find_one(query)
        return doc is not None

    async def set_deposit_timer(
        self, user_id, address, mode, expires_at, index=None, reserved=False
    ):
        if not self._initialized:
            return
        # Ensure expires_at is timezone-aware
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        doc = {
            "user_id": user_id,
            "address": address,
            "mode": mode,
            "expires_at": expires_at,
            "active": True,
            "reserved": reserved,
            "expiry_notified": False,
            "updated_at": datetime.now(timezone.utc),
        }
        if index is not None:
            doc["index"] = index
        query = {"user_id": user_id}
        update = {"$set": doc}
        await self.deposit_timers.update_one(query, update, upsert=True)

    async def clear_deposit_timer(self, user_id):
        if not self._initialized:
            return
        # Find the timer to get the address
        timer = await self.deposit_timers.find_one({"user_id": user_id, "active": True})
        if timer:
            address = timer.get("address")
            # Mark the timer as inactive and release the address
            query = {"user_id": user_id}
            update = {
                "$set": {
                    "active": False,
                    "reserved": False,
                    "expiry_notified": True,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
            await self.deposit_timers.update_one(query, update)
        else:
            # Fallback: just mark inactive
            query = {"user_id": user_id}
            update = {"$set": {"active": False, "reserved": False}}
            await self.deposit_timers.update_one(query, update)

    async def get_all_active_deposit_timers(self):
        if not self._initialized:
            return []
        now = datetime.now(timezone.utc)
        query = {"active": True}  # Get all active timers, not just expired ones
        cursor = self.deposit_timers.find(query)
        timers = [doc async for doc in cursor]

        # Ensure all expires_at fields are timezone-aware
        for timer in timers:
            if timer.get("expires_at") and timer["expires_at"].tzinfo is None:
                timer["expires_at"] = timer["expires_at"].replace(tzinfo=timezone.utc)

        return timers

    async def get_next_index_for_user(self, user_id):
        """Get the next available index for a given user."""
        if not self._initialized:
            return 0
        try:
            # Find the highest index for this user
            cursor = (
                self.deposit_timers.find({"user_id": user_id})
                .sort("index", -1)
                .limit(1)
            )
            highest_timer = await cursor.to_list(length=1)
            if highest_timer:
                return highest_timer[0].get("index", 0) + 1
            return 0
        except Exception as e:
            logger.error(f"Error getting next index for user {user_id}: {e}")
            return 0

    async def insert_deposit_event(self, event):
        await self.deposit_events.insert_one(
            {"event": event, "received_at": datetime.now(timezone.utc)}
        )

    async def insert_withdrawal_event(self, event):
        await self.withdrawal_events.insert_one(
            {"event": event, "received_at": datetime.now(timezone.utc)}
        )

    async def insert_account_event(self, event):
        await self.account_events.insert_one(
            {"event": event, "received_at": datetime.now(timezone.utc)}
        )

    async def insert_raw_event(self, event, event_type):
        await self.raw_events.insert_one(
            {"event": event, "event_type": event_type,
                "received_at": datetime.now(timezone.utc)}
        )

    async def get_next_available_pool_index(self, pool_size: int, user_id: str) -> int:
        """
        Get the next available index in the pool for a user.
        Returns -1 if no indices are available.
        """
        if not self._initialized:
            return -1

        try:
            # Get user's last used index
            last_timer = await self.deposit_timers.find_one(
                {"user_id": user_id}, sort=[("index", -1)]
            )
            last_index = last_timer.get("index", 0) if last_timer else 0

            # Get all currently reserved indices
            active_timers = await self.deposit_timers.find(
                {"active": True, "reserved": True, "mode": "pool"}
            ).to_list(length=pool_size)

            reserved_indices = {
                timer.get("index")
                for timer in active_timers
                if timer.get("index") is not None
            }

            # Try to find next available index
            next_index = (last_index + 1) % pool_size
            attempts = 0

            while next_index in reserved_indices and attempts < pool_size:
                next_index = (next_index + 1) % pool_size
                attempts += 1

            # If we've tried all indices and none are available
            if attempts >= pool_size:
                return -1

            return next_index

        except Exception as e:
            logger.error(f"Error getting next available pool index: {e}")
            return -1
