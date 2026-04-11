import logging

from neo4j import AsyncGraphDatabase
from app.core.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

driver = None


async def init_neo4j():
    global driver
    driver = AsyncGraphDatabase.driver(
        settings.NEO4J_URL,
        auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD)
    )
    # 创建索引以加速查询
    try:
        async with driver.session() as session:
            await session.run("CREATE INDEX entity_name_index IF NOT EXISTS FOR (e:Entity) ON (e.name)")
            await session.run("CREATE INDEX document_id_index IF NOT EXISTS FOR (d:Document) ON (d.id)")
    except Exception as e:
        logger.warning("Failed to create Neo4j index: %s", e)


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
