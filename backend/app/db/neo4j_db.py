from neo4j import AsyncGraphDatabase
from app.core.config import get_settings

settings = get_settings()

driver = None


async def init_neo4j():
    global driver
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URL,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )


async def close_neo4j():
    global driver
    if driver:
        await driver.close()


def get_neo4j_driver():
    return driver


async def run_cypher(query: str, parameters: dict = None):
    async with driver.session() as session:
        result = await session.run(query, parameters or {})
        return [record async for record in result]
