"""
Deduplicator — post-Scholar cleanup agent.

Finds and merges pathogen records that refer to the same organism under
different names:
  - Case variants:   "hantavirus"  /  "Hantavirus"
  - Partial names:   "Ebola"  /  "Ebola virus"  /  "Ebola virus disease"

MERGE STRATEGY:
  1. Group pathogens whose names match by case-insensitive equality OR
     word-prefix containment ("ebola" is a prefix word of "ebola virus").
  2. Within each group, elect the winner: record with the most non-null fields;
     tie-break by longer species_name (more specific wins).
  3. Merge array fields (transmission_routes, reservoir_hosts) — union,
     preserving order, deduplicating.
  4. Fill null scalar fields in the winner from the loser.
  5. Reroute pathogen_mentions: if winner already has a mention for the same
     document, add the counts; otherwise reassign the row.
  6. Reroute outbreak FK references from loser → winner.
  7. Delete loser records.

Runs automatically after Scholar via the ARQ task chain:
  task_run_scholar → task_run_dedup → task_sync_graph
"""

import structlog
from sqlalchemy import select, update

from app.db.models.outbreak import Outbreak
from app.db.models.pathogen import Pathogen
from app.db.models.pathogen_mention import PathogenMention
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


# ── Grouping helpers ──────────────────────────────────────────────────────────

# English function words that appear in natural-language descriptions but not in scientific names
_NL_INDICATORS = frozenset({
    "for", "which", "that", "we", "no", "have", "and", "with", "our", "it", "not",
    "strain", "type", "variant", "species", "without",
})


def _is_descriptive_phrase(words: list[str]) -> bool:
    """True when a name looks like a natural-language description rather than a scientific name.

    Catches LLM outputs like "Ebola strain for which we have no vaccine and no treatment"
    that should be collapsed into the canonical short name ("Ebola virus").
    """
    return len(words) >= 7 or sum(1 for w in words if w in _NL_INDICATORS) >= 2


def _names_match(a: str, b: str) -> bool:
    al, bl = a.lower().strip(), b.lower().strip()
    if al == bl:
        return True
    # Word-prefix: "ebola" vs "ebola virus" — al is a full-word prefix of bl or vice versa
    if bl.startswith(al + " ") or al.startswith(bl + " "):
        return True
    # Descriptive-phrase alias: first word matches AND one name is clearly a description.
    # e.g. "Ebola virus" ↔ "Ebola strain for which we have no vaccine and no treatment"
    a_words, b_words = al.split(), bl.split()
    if a_words and b_words and a_words[0] == b_words[0]:
        if _is_descriptive_phrase(a_words) or _is_descriptive_phrase(b_words):
            return True
    return False


def _find_groups(pathogens: list[Pathogen]) -> list[list[Pathogen]]:
    """Union-find grouping of pathogens whose names match."""
    parent = list(range(len(pathogens)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(len(pathogens)):
        for j in range(i + 1, len(pathogens)):
            if _names_match(pathogens[i].species_name, pathogens[j].species_name):
                union(i, j)

    buckets: dict[int, list[Pathogen]] = {}
    for i, p in enumerate(pathogens):
        root = find(i)
        buckets.setdefault(root, []).append(p)

    return [group for group in buckets.values() if len(group) > 1]


def _non_null_count(p: Pathogen) -> int:
    fields = [
        p.common_name, p.genome_type, p.transmission_routes, p.reservoir_hosts,
        p.description, p.ncbi_taxonomy_id, p.ictv_id,
    ]
    return sum(1 for f in fields if f is not None)


def _pick_winner(group: list[Pathogen]) -> tuple[Pathogen, list[Pathogen]]:
    """Most complete data wins; tie-break by longer (more specific) species_name."""
    ranked = sorted(
        group,
        key=lambda p: (_non_null_count(p), len(p.species_name)),
        reverse=True,
    )
    return ranked[0], ranked[1:]


def _merge_updates(winner: Pathogen, losers: list[Pathogen]) -> dict:
    """Compute field updates to apply to the winner from all losers."""
    updates: dict = {}

    for loser in losers:
        # Array fields: union, deduplicated, preserving order
        for field in ("transmission_routes", "reservoir_hosts"):
            w_val: list = getattr(winner, field) or []
            l_val: list = getattr(loser, field) or []
            merged = list(dict.fromkeys(w_val + l_val))
            if merged and merged != w_val:
                updates[field] = merged
                # Update winner reference so subsequent losers see the merged list
                setattr(winner, field, merged)

        # Scalar nulls: fill from loser
        for field in (
            "common_name", "genome_type", "description", "ncbi_taxonomy_id", "ictv_id",
        ):
            if getattr(winner, field) is None and getattr(loser, field) is not None:
                updates[field] = getattr(loser, field)
                setattr(winner, field, getattr(loser, field))

        # Boolean OR for who_priority
        if loser.who_priority and not winner.who_priority:
            updates["who_priority"] = True
            winner.who_priority = True

    return updates


# ── Mention-level dedup (run BEFORE Scholar) ──────────────────────────────────

async def run_mention_deduplication() -> dict:
    """
    Consolidate pathogen_mentions names before Scholar profiles anything.

    Groups distinct pathogen names from the mentions table using the same
    word-prefix / case-insensitive matching as the pathogen-record dedup.
    Within each group, the longer (more specific) name wins and all mention
    rows for the shorter aliases are reassigned or merged.

    Example:
      "Measles" + "Measles morbillivirus" → both rows → "Measles morbillivirus"

    Returns {"groups_merged", "names_consolidated"}.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PathogenMention.pathogen_name).distinct()
        )
        names: list[str] = [row[0] for row in result.all()]

    if not names:
        return {"agent": "mention_deduplicator", "groups_merged": 0, "names_consolidated": 0}

    # Union-find grouping using the shared _names_match predicate
    parent = list(range(len(names)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        parent[find(x)] = find(y)

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            if _names_match(names[i], names[j]):
                union(i, j)

    buckets: dict[int, list[str]] = {}
    for i, name in enumerate(names):
        buckets.setdefault(find(i), []).append(name)

    groups = [g for g in buckets.values() if len(g) > 1]
    names_consolidated = 0

    for group in groups:
        winner = max(group, key=len)  # longer = more specific name wins
        losers = [n for n in group if n != winner]
        logger.info("mention_dedup_merging", winner=winner, losers=losers)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                for loser_name in losers:
                    loser_result = await session.execute(
                        select(PathogenMention).where(
                            PathogenMention.pathogen_name == loser_name
                        )
                    )
                    for mention in loser_result.scalars().all():
                        existing_result = await session.execute(
                            select(PathogenMention).where(
                                PathogenMention.document_id == mention.document_id,
                                PathogenMention.pathogen_name == winner,
                            )
                        )
                        existing = existing_result.scalar_one_or_none()
                        if existing:
                            existing.mention_count += mention.mention_count
                            await session.delete(mention)
                        else:
                            mention.pathogen_name = winner
                    names_consolidated += 1

    logger.info(
        "mention_dedup_complete",
        groups_merged=len(groups),
        names_consolidated=names_consolidated,
    )
    return {
        "agent": "mention_deduplicator",
        "groups_merged": len(groups),
        "names_consolidated": names_consolidated,
    }


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_deduplication() -> dict:
    """
    Detect and merge duplicate pathogen rows.

    Returns {"agent", "merged_groups", "records_removed", "records_updated"}.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Pathogen))
        pathogens = list(result.scalars().all())

    groups = _find_groups(pathogens)
    merged_groups = 0
    records_removed = 0
    records_updated = 0

    for group in groups:
        winner, losers = _pick_winner(group)
        loser_names = [lo.species_name for lo in losers]
        loser_ids = [lo.id for lo in losers]

        logger.info("dedup_merging", winner=winner.species_name, losers=loser_names)

        async with AsyncSessionLocal() as session:
            async with session.begin():
                # 1. Compute merged field updates and apply to winner
                merge_kwargs = _merge_updates(winner, losers)
                if merge_kwargs:
                    await session.execute(
                        update(Pathogen)
                        .where(Pathogen.id == winner.id)
                        .values(**merge_kwargs)
                    )
                    records_updated += 1

                # 2. Reroute outbreak FK: loser.id → winner.id
                for loser_id in loser_ids:
                    await session.execute(
                        update(Outbreak)
                        .where(Outbreak.pathogen_id == loser_id)
                        .values(pathogen_id=winner.id)
                    )

                # 3. Reroute pathogen_mentions: handle unique (document_id, pathogen_name)
                for loser_name in loser_names:
                    loser_mentions_result = await session.execute(
                        select(PathogenMention).where(
                            PathogenMention.pathogen_name == loser_name
                        )
                    )
                    loser_mentions = loser_mentions_result.scalars().all()

                    for mention in loser_mentions:
                        # Check if winner name already has a row for this document
                        existing_result = await session.execute(
                            select(PathogenMention).where(
                                PathogenMention.document_id == mention.document_id,
                                PathogenMention.pathogen_name == winner.species_name,
                            )
                        )
                        existing = existing_result.scalar_one_or_none()

                        if existing:
                            # Merge counts into existing winner row, drop loser row
                            existing.mention_count += mention.mention_count
                            await session.delete(mention)
                        else:
                            # No conflict — just reassign
                            mention.pathogen_name = winner.species_name

                # 4. Delete loser pathogen records
                for loser_id in loser_ids:
                    loser_obj = await session.get(Pathogen, loser_id)
                    if loser_obj:
                        await session.delete(loser_obj)
                        records_removed += 1

        merged_groups += 1

    logger.info(
        "dedup_complete",
        merged_groups=merged_groups,
        records_removed=records_removed,
        records_updated=records_updated,
    )
    return {
        "agent": "deduplicator",
        "merged_groups": merged_groups,
        "records_removed": records_removed,
        "records_updated": records_updated,
    }
