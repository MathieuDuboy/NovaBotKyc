import logging
import time
from typing import Any, Dict, Optional

from telegram import Bot
from telegram.error import TelegramError

import config
from utils.logger import logger


class TelegramMessaging:
    """Centralized service for sending Telegram messages with retry logic."""

    def __init__(self):
        self.bot_token = config.BOT_TOKEN
        if not self.bot_token:
            logger.error("Telegram bot token not configured")
            raise ValueError("Telegram bot token not configured")

        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.bot = Bot(token=self.bot_token)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        parse_mode: str = "HTML",
        max_retries: int = 3,
        retry_delay: int = 1,
    ) -> bool:
        """
        Send a Telegram message with retry logic.

        Args:
            chat_id: The Telegram chat ID to send to
            text: The message text
            parse_mode: Message parse mode (HTML/Markdown)
            max_retries: Maximum number of retry attempts
            retry_delay: Initial delay between retries in seconds

        Returns:
            bool: True if message was sent successfully, False otherwise
        """
        if not self.bot_token:
            logger.error("Cannot send message - bot token not configured")
            return False

        url = f"{self.base_url}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

        retry_count = 0
        current_delay = retry_delay

        while retry_count <= max_retries:
            try:
                await self.bot.send_message(chat_id=chat_id, text=text)
                logger.info(f"Successfully sent message to chat {chat_id}")
                return True
            except TelegramError as e:
                logger.error(f"Error sending message to chat {chat_id}: {e}")

                if retry_count == max_retries:
                    logger.error(
                        f"Failed to send message after {max_retries+1} attempts: {e}"
                    )
                    return False

            if retry_count < max_retries:
                current_delay *= 2  # Exponential backoff
                logger.info(f"Retrying in {current_delay} seconds...")
                time.sleep(current_delay)
                retry_count += 1
            else:
                break

        return False

    async def send_card_notification(self, user_id: str, message: str) -> bool:
        """Send a card-related notification to a user."""
        return await self.send_message(user_id, message)

    async def send_3ds_otp(
        self, user_id: str, otp: str, amount: float, currency: str, merchant: str
    ) -> bool:
        """Send a 3DS OTP notification to a user."""
        message = (
            f"🔐 3DS Verification Required\n\n"
            f"Amount: {amount} {currency}\n"
            f"Merchant: {merchant}\n"
            f"OTP: {otp}\n\n"
            f"Please enter this OTP to complete your transaction."
        )
        return await self.send_message(user_id, message)

    async def send_deposit_address(
        self, user_id: str, address: str, validity_minutes: int
    ) -> bool:
        """Send a deposit address notification to a user."""
        message = (
            f"Your deposit address is:\n"
            f"{address}\n\n"
            f"It is valid for {validity_minutes} minutes. After the validity "
            "expires, please press the Deposit button again to get a "
            "new address."
        )
        return await self.send_message(user_id, message)

    async def send_admin_alert(self, message: str) -> bool:
        """Send an alert to the admin channel."""
        if not config.ID_CHANNEL:
            logger.error("Admin channel ID not configured")
            return False

        try:
            admin_chat_id = int(config.ID_CHANNEL)
            return await self.send_message(admin_chat_id, message)
        except ValueError:
            logger.error(f"Invalid admin channel ID: {config.ID_CHANNEL}")
            return False

    async def send_deposit_expiry(self, user_id: str, message: str = None) -> bool:
        """Send a deposit address expiry notification."""
        if message is None:
            message = (
                "⚠️ Your deposit address has expired.\n\n"
                "Please press the Deposit button again to get a new address."
            )
        return await self.send_message(user_id, message)

    async def send_photo(self, chat_id: int, photo_path: str, caption: str = None):
        try:
            with open(photo_path, "rb") as photo:
                await self.bot.send_photo(chat_id=chat_id, photo=photo, caption=caption)
            logger.info(f"Successfully sent photo to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending photo to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Photo file not found: {e}")

    async def send_document(
        self, chat_id: int, document_path: str, caption: str = None
    ):
        try:
            with open(document_path, "rb") as document:
                await self.bot.send_document(
                    chat_id=chat_id, document=document, caption=caption
                )
            logger.info(f"Successfully sent document to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending document to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Document file not found: {e}")

    async def send_location(self, chat_id: int, latitude: float, longitude: float):
        try:
            await self.bot.send_location(
                chat_id=chat_id, latitude=latitude, longitude=longitude
            )
            logger.info(f"Successfully sent location to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending location to chat {chat_id}: {e}")

    async def send_contact(self, chat_id: int, phone_number: str, first_name: str):
        try:
            await self.bot.send_contact(
                chat_id=chat_id, phone_number=phone_number, first_name=first_name
            )
            logger.info(f"Successfully sent contact to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending contact to chat {chat_id}: {e}")

    async def send_venue(
        self, chat_id: int, latitude: float, longitude: float, title: str, address: str
    ):
        try:
            await self.bot.send_venue(
                chat_id=chat_id,
                latitude=latitude,
                longitude=longitude,
                title=title,
                address=address,
            )
            logger.info(f"Successfully sent venue to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending venue to chat {chat_id}: {e}")

    async def send_animation(
        self, chat_id: int, animation_path: str, caption: str = None
    ):
        try:
            with open(animation_path, "rb") as animation:
                await self.bot.send_animation(
                    chat_id=chat_id, animation=animation, caption=caption
                )
            logger.info(f"Successfully sent animation to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending animation to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Animation file not found: {e}")

    async def send_sticker(self, chat_id: int, sticker_path: str):
        try:
            with open(sticker_path, "rb") as sticker:
                await self.bot.send_sticker(chat_id=chat_id, sticker=sticker)
            logger.info(f"Successfully sent sticker to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending sticker to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Sticker file not found: {e}")

    async def send_video(self, chat_id: int, video_path: str, caption: str = None):
        try:
            with open(video_path, "rb") as video:
                await self.bot.send_video(chat_id=chat_id, video=video, caption=caption)
            logger.info(f"Successfully sent video to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending video to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Video file not found: {e}")

    async def send_voice(self, chat_id: int, voice_path: str, caption: str = None):
        try:
            with open(voice_path, "rb") as voice:
                await self.bot.send_voice(chat_id=chat_id, voice=voice, caption=caption)
            logger.info(f"Successfully sent voice message to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending voice message to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Voice file not found: {e}")

    async def send_audio(self, chat_id: int, audio_path: str, caption: str = None):
        try:
            with open(audio_path, "rb") as audio:
                await self.bot.send_audio(chat_id=chat_id, audio=audio, caption=caption)
            logger.info(f"Successfully sent audio to chat {chat_id}")
        except TelegramError as e:
            logger.error(f"Error sending audio to chat {chat_id}: {e}")
        except FileNotFoundError as e:
            logger.error(f"Audio file not found: {e}")


# Create a singleton instance
telegram_messaging = TelegramMessaging()
