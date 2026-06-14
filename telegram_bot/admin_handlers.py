import logging
from typing import List

from telegram import Update
from telegram.ext import (CommandHandler, ContextTypes, ConversationHandler,
                          MessageHandler, filters)

from services.mysql_service import mysql_client
from utils.logger import logger

# States for conversation
WAITING_FOR_USER_ID = 1
WAITING_FOR_MESSAGE = 2
WAITING_FOR_BROADCAST_MESSAGE = 3


async def start_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command for admin bot."""
    await update.message.reply_text(
        "Welcome to Nova Admin Bot!\n\n"
        "Available commands:\n"
        "/send - Send a message to a specific user\n"
        "/send_all - Broadcast a message to all users\n"
        "/cancel - Cancel the current operation"
    )
    return ConversationHandler.END


async def send_message_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the send message conversation."""
    await update.message.reply_text(
        "Please enter the user ID to send the message to:"
    )
    return WAITING_FOR_USER_ID


async def send_message_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user ID input for sending message."""
    user_id = update.message.text.strip()
    context.user_data['target_user_id'] = user_id

    await update.message.reply_text(
        "Please enter the message to send:"
    )
    return WAITING_FOR_MESSAGE


async def send_message_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle message content and send it to the user."""
    message = update.message.text
    user_id = context.user_data.get('target_user_id')

    try:
        # Send message using telegram_messaging service
        from telegram_bot.messaging import telegram_messaging
        success = await telegram_messaging.send_message(user_id, message)

        if success:
            await update.message.reply_text(
                f"Message sent successfully to user {user_id}"
            )
        else:
            await update.message.reply_text(
                f"Failed to send message to user {user_id}"
            )
    except Exception as e:
        logger.error(
            f"Error sending message to user {user_id}: {e}"
        )
        await update.message.reply_text(
            f"Error sending message: {str(e)}"
        )

    return ConversationHandler.END


async def send_all_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start the broadcast message conversation."""
    await update.message.reply_text(
        "Please enter the message to broadcast to all users:"
    )
    return WAITING_FOR_BROADCAST_MESSAGE


async def send_all_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle broadcast message content and send to all users."""
    message = update.message.text

    try:
        # Get all users from MySQL
        users = await mysql_client.get_all_users()
        success_count = 0
        fail_count = 0

        # Send message to each user
        from telegram_bot.messaging import telegram_messaging
        for user in users:
            try:
                user_id = user.get('userId') or user.get('USER_ID')
                if user_id:
                    success = await telegram_messaging.send_message(
                        user_id, message
                    )
                    if success:
                        success_count += 1
                    else:
                        fail_count += 1
            except Exception as e:
                logger.error(
                    f"Error sending broadcast to user {user_id}: {e}"
                )
                fail_count += 1

        await update.message.reply_text(
            f"Broadcast completed:\n"
            f"Successfully sent: {success_count}\n"
            f"Failed: {fail_count}"
        )
    except Exception as e:
        logger.error(f"Error in broadcast: {e}")
        await update.message.reply_text(
            f"Error during broadcast: {str(e)}"
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the current conversation."""
    await update.message.reply_text(
        "Operation cancelled."
    )
    return ConversationHandler.END


def get_admin_handlers() -> List[ConversationHandler]:
    """Get all admin bot handlers."""
    send_message_handler = ConversationHandler(
        entry_points=[CommandHandler('send', send_message_start)],
        states={
            WAITING_FOR_USER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_message_user_id)
            ],
            WAITING_FOR_MESSAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, send_message_content)
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    send_all_handler = ConversationHandler(
        entry_points=[CommandHandler('send_all', send_all_start)],
        states={
            WAITING_FOR_BROADCAST_MESSAGE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, send_all_content
                )
            ],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    return [
        CommandHandler('start', start_admin),
        send_message_handler,
        send_all_handler,
        CommandHandler('cancel', cancel)
    ]
