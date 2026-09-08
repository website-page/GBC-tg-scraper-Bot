import os
import asyncio
from flask import Flask, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import FloodWaitError, UserPrivacyRestrictedError, UserAlreadyParticipantError, ChatAdminRequiredError, UserNotMutualContactError

app = Flask(__name__)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "")
CONSENTED_USER_IDS = os.environ.get("CONSENTED_USER_IDS", "")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "5"))
BATCH_DELAY_SECONDS = int(os.environ.get("BATCH_DELAY_SECONDS", "600"))
MIGRATION_SECRET = os.environ.get("MIGRATION_SECRET", "")


def parse_ids(value):
    return [int(x.strip()) for x in value.split(",") if x.strip()]


async def migrate_consented_users():
    if not all([API_ID, API_HASH, SESSION_STRING, TARGET_CHANNEL, CONSENTED_USER_IDS]):
        return {"ok": False, "error": "Missing required environment variables."}

    user_ids = parse_ids(CONSENTED_USER_IDS)
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()

    try:
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Telegram session is not authorized."}

        target = await client.get_entity(TARGET_CHANNEL)
        processed = []
        failed = []

        # Only process the explicitly supplied, consented user IDs.
        for user_id in user_ids[:BATCH_SIZE]:
            try:
                await client(InviteToChannelRequest(target, [user_id]))
                processed.append(user_id)
            except UserAlreadyParticipantError:
                processed.append(user_id)
            except (UserPrivacyRestrictedError, UserNotMutualContactError) as exc:
                failed.append({"user_id": user_id, "error": type(exc).__name__})
            except FloodWaitError as exc:
                failed.append({"user_id": user_id, "error": "FloodWait", "seconds": exc.seconds})
                break
            except ChatAdminRequiredError as exc:
                failed.append({"user_id": user_id, "error": type(exc).__name__})
                break
            except Exception as exc:
                failed.append({"user_id": user_id, "error": type(exc).__name__})

            # Small pause between individual invitations.
            await asyncio.sleep(min(10, max(1, BATCH_DELAY_SECONDS // max(BATCH_SIZE, 1))))

        return {
            "ok": True,
            "processed": processed,
            "failed": failed,
            "batch_size": BATCH_SIZE,
            "note": "Only explicitly consented user IDs are processed. Telegram privacy/permission rules still apply."
        }
    finally:
        await client.disconnect()


@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Telegram channel migration worker"})


@app.get("/api/migrate")
def migrate():
    supplied_secret = os.environ.get("VERCEL_AUTOMATION_SECRET", "")
    # Vercel Cron can call this endpoint; a secret is optional for local testing.
    if MIGRATION_SECRET and supplied_secret != MIGRATION_SECRET:
        return jsonify({"ok": False, "error": "Unauthorized"}), 401

    result = asyncio.run(migrate_consented_users())
    return jsonify(result)
