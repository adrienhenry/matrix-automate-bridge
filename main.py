import asyncio
import os
import io
import mimetypes
from dotenv import load_dotenv
# Added imports for handling encrypted files
from nio import AsyncClient, AsyncClientConfig, MatrixRoom, RoomMessageText, RoomMessageImage
from nio.crypto.attachments import decrypt_attachment
import aiohttp
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

MATRIX_CONFIG = {
    "homeserver": os.getenv("MATRIX_HOMESERVER", "https://matrix.org").strip(),
    "user_id": os.getenv("MATRIX_USER_ID").strip(),
    "access_token": os.getenv("MATRIX_ACCESS_TOKEN").strip(),
    "device_id": os.getenv("MATRIX_DEVICE_ID", "ACTIVEPIECES_BRIDGE").strip(),
    "store_path": os.getenv("MATRIX_STORE_PATH", "./store").strip(),
    "bot_room": os.getenv("MATRIX_BOT_ROOM", "./store").strip(),
}   
print(MATRIX_CONFIG)
ACTIVEPIECES_CONFIG = {
    "webhook_url": os.getenv("ACTIVEPIECES_WEBHOOK_URL").strip(),
}

cache_file = None
if not ACTIVEPIECES_CONFIG["webhook_url"]:
    raise ValueError("Missing Activepieces webhook URL in .env file")

async def send_to_activepieces_json(data):
    """Send text messages (JSON)"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(ACTIVEPIECES_CONFIG["webhook_url"], json=data) as response:
                logger.info(f"✅ Text sent to Webhook. Status: {response.status}")
    except Exception as e:
        logger.error(f"❌ Error sending text: {e}")

async def send_to_activepieces_file(metadata, filename, file_bytes, mime_type):
    """Send files (Multipart)"""
    try:
        data = aiohttp.FormData()
        # Add JSON metadata fields
        for key, value in metadata.items():
            data.add_field(key, str(value))
        
        # Add the file binary
        data.add_field('file', file_bytes, filename=filename, content_type=mime_type)
        print("command: ",metadata["command"])
        params = {"command": metadata["command"]}
        async with aiohttp.ClientSession() as session:
            async with session.post(ACTIVEPIECES_CONFIG["webhook_url"], data=data,params=params) as response:
                logger.info(f"✅ Image sent to Webhook. Status: {response.status}")
    except Exception as e:
        logger.error(f"❌ Error sending file: {e}")

async def message_callback(room: MatrixRoom, event):
    global cache_file

    if event.sender == MATRIX_CONFIG["user_id"]:
        return

    # Base Metadata
    message_data = {
        "room_id": room.room_id,
        "room_name": room.display_name,
        "sender": event.sender,
        "timestamp": event.server_timestamp,
        "event_id": event.event_id,
    }
    if message_data["room_name"]!=MATRIX_CONFIG["bot_room"]:
        return
    # --- HANDLE TEXT ---
    if isinstance(event, RoomMessageText):
        message_data["type"] = "text"
        message_data["body"] = event.body
        logger.info(f"📨 Text: {event.body}")

        if "!dictee" in message_data["body"]:
            if cache_file is not None:
                cache_file["metadata"].update({"command":"dictee"})
                await send_to_activepieces_file(**cache_file)
            cache_file=None

    # --- HANDLE IMAGES ---
    elif isinstance(event, RoomMessageImage):
        
        logger.info(f"📸 Processing image: {event.body}")
        message_data["type"] = "image"
        message_data["body"] = event.body # Filename

        # 1. Determine download URL and keys
        mxc_url = None
        encryption_info = None

        # Check if encrypted (nio puts encrypted details in 'file', plain in 'url')
        if event.source.get('content', {}).get('file'):
            # Encrypted Image
            file_info = event.source['content']['file']
            mxc_url = file_info['url']
            encryption_info = file_info # Contains key, iv, hashes
        else:
            # Unencrypted Image
            mxc_url = event.url

        if not mxc_url:
            logger.error("❌ Could not find media URL in event")
            return

        # 2. Download the Media (Bytes)
        # client is passed via closure context or we need to pass it. 
        # For simplicity, we assume client is available or we pass it in callback.
        # FIX: We need access to 'client' here. 
        # We will attach client to the room object or use a global wrapper in a real app.
        # For this script, we will use the global 'client_instance' hack or update main to pass it.
        try:
            response = await client_instance.download(mxc_url)
            
            if isinstance(response, bytes):
                media_bytes = response
            elif hasattr(response, 'body'):
                media_bytes = response.body
            else:
                logger.error("❌ Failed to download media")
                return

            # 3. Decrypt if necessary
            if encryption_info:
                logger.info("🔐 Decrypting image...")
                media_bytes = decrypt_attachment(
                    media_bytes,
                    encryption_info['key']['k'],
                    encryption_info['hashes']['sha256'],
                    encryption_info['iv']
                )

            # 4. Guess Mime Type
            mime_type = mimetypes.guess_type(event.body)[0] or "application/octet-stream"

            # 5. Send File to n8n
            cache_file = {"metadata":message_data, "filename":event.body, "file_bytes":media_bytes, "mime_type":mime_type}

        except Exception as e:
            logger.error(f"❌ Error processing image: {e}")

# Global client variable for the callback to use
client_instance = None

async def main():
    global client_instance
    
    # ... (Same Config Setup as before) ...
    store_path = MATRIX_CONFIG["store_path"]
    os.makedirs(store_path, exist_ok=True)
    
    config = AsyncClientConfig(
        store_sync_tokens=True,
        encryption_enabled=True,
        pickle_key="YOUR_SECURE_PICKLE_KEY", 
    )

    client = AsyncClient(
        MATRIX_CONFIG["homeserver"],
        MATRIX_CONFIG["user_id"],
        device_id=MATRIX_CONFIG["device_id"],
        store_path=store_path,  
        config=config,
    )
    
    # Assign to global so callback can use it for downloads
    client_instance = client

    client.access_token = MATRIX_CONFIG["access_token"]
    
    # ... (Same Load Store / Sync Logic) ...
    try:
        client.load_store()
    except:
        pass
        
    logger.info("🔄 Syncing...")
    await client.sync(timeout=30000) 

    # Callbacks
    client.add_event_callback(message_callback, RoomMessageText)
    client.add_event_callback(message_callback, RoomMessageImage)

    logger.info("🚀 Bot ready. Forwarding decrypted files to n8n.")
    await client.sync_forever(timeout=30000)

if __name__ == "__main__":
    asyncio.run(main())
