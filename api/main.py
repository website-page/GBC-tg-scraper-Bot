import os
import asyncio
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest, InviteToChannelRequest
from telethon.tl.types import ChannelParticipantsSearch

# Store these in Vercel Environment Variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
SESSION_STRING = os.environ.get("SESSION_STRING", "") # Generated beforehand locally

async def scrape_usernames(client, group_username):
    group_entity = await client.get_entity(group_username)
    participants = await client(GetParticipantsRequest(
        group_entity,
        filter=ChannelParticipantsSearch(''),
        offset=0,
        limit=100,
        hash=0
    ))
    return [user.username for user in participants.users if user.username]

async def add_to_group(client, target_group_username, usernames):
    target_entity = await client.get_entity(target_group_username)
    for username in usernames:
        try:
            await client(InviteToChannelRequest(target_entity, [username]))
            # Verify if user was processed without crashing
            print(f"Successfully processed invitation attempt for: {username}")
        except Exception as e:
            print(f"Failed to add {username}: {e}")

# Entry point for Vercel HTTP Handler
async def handler(request):
    client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        return {"statusCode": 401, "body": "Session expired or invalid."}

    group_username = 'group_username'
    target_group_username = 'target_group_username'

    scraped_usernames = await scrape_usernames(client, group_username)
    await add_to_group(client, target_group_username, scraped_usernames)

    await client.disconnect()
    return {"statusCode": 200, "body": "Operation completed."}
