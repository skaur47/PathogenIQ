"""
GraphSyncAgent — syncs pathogen profiles from PostgreSQL into Neo4j.

Graph schema
────────────
Nodes:
  (:Pathogen)          — one per species_name; carries all scalar fields
  (:Category)          — one per category value (virus, bacterium, …)
  (:TransmissionRoute) — one per route string (airborne, droplet, …)
  (:ReservoirHost)     — one per host string (bats, rodents, …)

Relationships:
  (:Pathogen)-[:IN_CATEGORY]->(:Category)
  (:Pathogen)-[:SPREADS_VIA]->(:TransmissionRoute)
  (:Pathogen)-[:HOSTED_BY]->(:ReservoirHost)

All writes use MERGE so the sync is fully idempotent — running it twice
produces no duplicates.  Stale relationships are removed before rebuilding:
if a pathogen's transmission routes change, old edges are detached before
the new ones are created.

Runs automatically after deduplication via the ARQ task chain:
  task_run_scholar → task_run_dedup → task_sync_graph
"""

import structlog
from sqlalchemy import select

from app.db.models.pathogen import Pathogen
from app.db.session import AsyncSessionLocal
from app.graph.neo4j_client import get_neo4j_driver

logger = structlog.get_logger(__name__)

# Cypher: ensure unique constraints exist (CREATE IF NOT EXISTS is idempotent)
_CONSTRAINTS = [
    "CREATE CONSTRAINT pathogen_name IF NOT EXISTS FOR (p:Pathogen) REQUIRE p.species_name IS UNIQUE",
    "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
    "CREATE CONSTRAINT route_name IF NOT EXISTS FOR (r:TransmissionRoute) REQUIRE r.name IS UNIQUE",
    "CREATE CONSTRAINT host_name IF NOT EXISTS FOR (h:ReservoirHost) REQUIRE h.name IS UNIQUE",
]

_UPSERT_PATHOGEN = """\
MERGE (p:Pathogen {species_name: $species_name})
SET p.common_name     = $common_name,
    p.genome_type     = $genome_type,
    p.who_priority    = $who_priority,
    p.ncbi_taxonomy_id = $ncbi_taxonomy_id,
    p.description     = $description
"""

# Remove all existing typed edges for this pathogen before rebuilding —
# handles the case where routes/hosts were removed during dedup.
_CLEAR_EDGES = """\
MATCH (p:Pathogen {species_name: $species_name})
OPTIONAL MATCH (p)-[r:IN_CATEGORY|SPREADS_VIA|HOSTED_BY]->()
DELETE r
"""

_LINK_CATEGORY = """\
MATCH (p:Pathogen {species_name: $species_name})
MERGE (c:Category {name: $category})
MERGE (p)-[:IN_CATEGORY]->(c)
"""

_LINK_ROUTE = """\
MATCH (p:Pathogen {species_name: $species_name})
MERGE (r:TransmissionRoute {name: $route})
MERGE (p)-[:SPREADS_VIA]->(r)
"""

_LINK_HOST = """\
MATCH (p:Pathogen {species_name: $species_name})
MERGE (h:ReservoirHost {name: $host})
MERGE (p)-[:HOSTED_BY]->(h)
"""


async def run_graph_sync() -> dict:
    """
    Read all pathogens from PostgreSQL and sync them into Neo4j.

    Returns {"agent", "pathogens_synced", "errors"}.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Pathogen))
        pathogens = list(result.scalars().all())

    driver = get_neo4j_driver()
    synced = 0
    errors: list[str] = []

    try:
        async with driver.session() as neo:
            # Ensure constraints (idempotent)
            for cypher in _CONSTRAINTS:
                try:
                    await neo.run(cypher)
                except Exception as exc:
                    # Older Neo4j community editions may not support named constraints.
                    # Log and continue — MERGE still works without the constraint.
                    logger.warning("graph_constraint_warning", cypher=cypher[:60], error=str(exc))

            # Vague host terms that add no signal to the graph
            _VAGUE_HOSTS = frozenset({"animals", "unknown", "various"})

            for p in pathogens:
                try:
                    name = p.species_name

                    # Skip unclassified pathogens — they pollute the graph with "unknown" nodes
                    if not p.category or p.category.value == "unknown":
                        logger.warning("graph_sync_skip_unknown_category", pathogen=name)
                        continue

                    # Upsert node
                    await neo.run(
                        _UPSERT_PATHOGEN,
                        species_name=name,
                        common_name=p.common_name,
                        genome_type=p.genome_type,
                        who_priority=p.who_priority,
                        ncbi_taxonomy_id=p.ncbi_taxonomy_id,
                        description=p.description,
                    )

                    # Clear stale edges, then rebuild
                    await neo.run(_CLEAR_EDGES, species_name=name)

                    await neo.run(_LINK_CATEGORY, species_name=name, category=p.category.value)

                    for route in (p.transmission_routes or []):
                        await neo.run(_LINK_ROUTE, species_name=name, route=str(route))

                    for host in (p.reservoir_hosts or []):
                        if str(host).lower() not in _VAGUE_HOSTS:
                            await neo.run(_LINK_HOST, species_name=name, host=str(host))

                    synced += 1

                except Exception as exc:
                    msg = f"{p.species_name}: {exc}"
                    logger.warning("graph_sync_error", pathogen=p.species_name, error=str(exc))
                    errors.append(msg)

    finally:
        await driver.close()

    logger.info("graph_sync_complete", pathogens_synced=synced, errors=len(errors))
    return {
        "agent": "graph_sync",
        "pathogens_synced": synced,
        "errors": errors,
    }
