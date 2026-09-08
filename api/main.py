import os
import asyncio
from flask import Flask, jsonify, request
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    UserAlreadyParticipantError,
    UserNotParticipantError,
    ChatAdminRequiredError,
    UserNotMutualContactError,
)

app = Flask(__name__)

API_ID = int(os.environ.get("API_ID", "0"))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "")
SOURCE_CHANNEL = os.environ.get("SOURCE_CHANNEL", "")
TARGET_CHANNEL = os.environ.get("TARGET_CHANNEL", "")
BATCH_SIZE = max(1, min(int(os.environ.get("BATCH_SIZE", "5")), 5))
MIGRATION_SECRET = os.environ.get("MIGRATION_SECRET", "")
CRON_SECRET = os.environ.get("CRON_SECRET", "")

async def already_in_target(client, target, user):
    try:
        await client.get_permissions(target, user)
        return True
    except UserNotParticipantError:
        return False
    except Exception:
        return False

async def migrate_next_batch():
    required = [API_ID, API_HASH, SESSION_STRING, SOURCE_CHANNEL, TARGET_CHANNEL]
    if not all(required):
        return {"ok": False, "error": "Missing API_ID, API_HASH, SESSION_STRING, SOURCE_CHANNEL or TARGET_CHANNEL."}

    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return {"ok": False, "error": "Telegram session is not authorized."}

        source = await client.get_entity(SOURCE_CHANNEL)
        target = await client.get_entity(TARGET_CHANNEL)
        moved, skipped, failed = [], [], []

        async for user in client.iter_participants(source):
            if len(moved) >= BATCH_SIZE:
                break
            if getattr(user, "deleted", False) or getattr(user, "bot", False):
                continue

            if await already_in_target(client, target, user):
                skipped.append(user.id)
                continue

            try:
                await client(InviteToChannelRequest(target, [user]))
                moved.append({"id": user.id, "username": user.username})
            except UserAlreadyParticipantError:
                skipped.append(user.id)
            except (UserPrivacyRestrictedError, UserNotMutualContactError) as exc:
                failed.append({"id": user.id, "error": type(exc).__name__})
            except FloodWaitError as exc:
                failed.append({"id": user.id, "error": "FloodWait", "seconds": exc.seconds})
                break
            except ChatAdminRequiredError as exc:
                failed.append({"id": user.id, "error": type(exc).__name__})
                break
            except Exception as exc:
                failed.append({"id": user.id, "error": type(exc).__name__})
            await asyncio.sleep(2)

        return {
            "ok": True,
            "moved_this_run": moved,
            "already_in_target": skipped,
            "failed": failed,
            "batch_size": BATCH_SIZE,
            "note": "Telegram privacy, invitation, permission and anti-spam limits still apply."
        }
    finally:
        await client.disconnect()

def authorized(req):
    auth = req.headers.get("Authorization", "")
    if CRON_SECRET and auth == f"Bearer {CRON_SECRET}":
        return True
    if MIGRATION_SECRET and auth == f"Bearer {MIGRATION_SECRET}":
        return True
    return False

@app.get("/")
def health():
    return jsonify({"ok": True, "service": "Telegram channel migration worker"})

@app.get("/api/migrate")
def migrate():
    if not authorized(request):
        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    try:
        return jsonify(asyncio.run(migrate_next_batch()))
    except Exception as exc:
        return jsonify({"ok": False, "error": type(exc).__name__, "message": str(exc)}), 500
