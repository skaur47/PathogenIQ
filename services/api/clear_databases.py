"""
PathogenIQ — wipe all data across every database.

Preserves schema (tables, indexes, constraints, alembic version).
Safe to re-run — all operations are idempotent.

Usage (inside Docker):
    docker compose exec api python clear_databases.py
"""

import asyncio
import sys

from app.core.logging import configure_logging
configure_logging()

_R = "\033[0m"
_BOLD = "\033[1m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_CYAN = "\033[36m"
_DIM = "\033[2m"


def _hdr(t): print(f"\n{_CYAN}{_BOLD}{'─'*52}{_R}\n{_CYAN}{_BOLD}  {t}{_R}\n{_CYAN}{_BOLD}{'─'*52}{_R}")
def _ok(m):  print(f"  {_GREEN}✓{_R}  {m}")
def _skip(m): print(f"  {_DIM}–  {m}{_R}")
def _err(m): print(f"  {_RED}✗{_R}  {m}")


# ── PostgreSQL ────────────────────────────────────────────────────────────────

async def clear_postgres() -> None:
    _hdr("PostgreSQL — truncate all data tables")
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

    # Ordered children-first to satisfy FK constraints; CASCADE handles the rest.
    # Each table runs in its own transaction so one missing table doesn't abort the rest.
    tables = [
        "pathogen_hypotheses",
        "pathogen_research_summaries",
        "research_articles",
        "pathogen_mentions",
        "citations",
        "outbreaks",
        "pathogens",
        "documents",
    ]

    for table in tables:
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await session.execute(
                        text(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE")
                    )
            _ok(f"Truncated  {table}")
        except Exception as exc:
            _err(f"{table}: {exc}")


# ── Neo4j ─────────────────────────────────────────────────────────────────────

async def clear_neo4j() -> None:
    _hdr("Neo4j — delete all nodes and relationships")
    from app.graph.neo4j_client import get_neo4j_driver

    driver = get_neo4j_driver()
    try:
        async with driver.session() as neo:
            # Count first so we can report what was removed
            result = await neo.run("MATCH (n) RETURN count(n) AS n")
            record = await result.single()
            count = record["n"] if record else 0

            await neo.run("MATCH (n) DETACH DELETE n")

            if count:
                _ok(f"Deleted {count} node(s) and all their relationships")
            else:
                _skip("Graph was already empty")
    except Exception as exc:
        _err(f"Neo4j clear failed: {exc}")
    finally:
        await driver.close()


# ── Redis ──────────────────────────────────────────────────────────────────────

async def clear_redis() -> None:
    _hdr("Redis — flush all keys")
    import redis.asyncio as aioredis
    from app.config import get_settings

    settings = get_settings()
    try:
        r = aioredis.from_url(settings.redis_url)
        count = await r.dbsize()
        await r.flushall()
        await r.aclose()
        if count:
            _ok(f"FLUSHALL — removed {count} key(s)")
        else:
            _skip("Redis was already empty")
    except Exception as exc:
        _err(f"Redis flush failed: {exc}")


# ── Qdrant ────────────────────────────────────────────────────────────────────

async def clear_qdrant() -> None:
    _hdr("Qdrant — delete all collections")
    import httpx
    from app.config import get_settings

    settings = get_settings()
    base = settings.qdrant_url.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/collections")
            resp.raise_for_status()
            collections = resp.json().get("result", {}).get("collections", [])

            if not collections:
                _skip("No Qdrant collections found — nothing to clear")
                return

            for col in collections:
                name = col["name"]
                await client.delete(f"{base}/collections/{name}")
                _ok(f"Deleted collection: {name}")
    except Exception as exc:
        _err(f"Qdrant clear failed: {exc}")


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    print(f"\n{_BOLD}PathogenIQ — Clear All Databases{_R}")
    print(f"{_DIM}Schema, indexes, constraints, and alembic_version are preserved.{_R}")

    await clear_postgres()
    await clear_neo4j()
    await clear_redis()
    await clear_qdrant()

    bar = "═" * 52
    print(f"\n{_GREEN}{_BOLD}{bar}{_R}")
    print(f"{_GREEN}{_BOLD}  All databases cleared. Ready for a fresh pipeline run.{_R}")
    print(f"{_GREEN}{_BOLD}{bar}{_R}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{_YELLOW}Interrupted.{_R}\n")
        sys.exit(1)
