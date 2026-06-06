"""
Neo4j async driver factory.

Usage:
    driver = get_neo4j_driver()
    async with driver.session() as session:
        await session.run("MATCH (n) RETURN n LIMIT 1")
    await driver.close()

The driver is intentionally not a module-level singleton — each task call
creates and closes its own driver to avoid stale connections after worker
restarts.
"""

from neo4j import AsyncGraphDatabase, AsyncDriver
from app.config import get_settings


def get_neo4j_driver() -> AsyncDriver:
    settings = get_settings()
    return AsyncGraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
