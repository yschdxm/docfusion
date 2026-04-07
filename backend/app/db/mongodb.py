from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import get_settings

settings = get_settings()

client: AsyncIOMotorClient = None
db = None


async def init_mongodb():
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    db = client.get_default_database()


async def close_mongodb():
    global client
    if client:
        client.close()


def get_mongodb():
    return db


def get_collection(name: str):
    return db[name]
