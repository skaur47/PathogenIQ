"""
PathogenIQ — full pipeline runner.

Pipeline order:
    ─── PHASE 1: COLLECTION (once) ───────────────────────────────────────────
    1. CDC collector     — CDC Health Alert Network advisories
    2. WHO collector     — WHO/PAHO/ECDC outbreak reports
    3. ProMED collector  — ProMED outbreak intelligence
    4. News collector    — BBC Health, STAT News, NPR Health, etc.

    ─── PHASE 2: SENTINEL (drain — repeats until no PENDING docs remain) ─────
    Sentinel runs until every collected document has been processed for
    pathogen mentions. Each pass handles one batch; the loop exits when
    documents_processed == 0.

    ─── PHASE 3: SCHOLAR (one call per pathogen, until all profiled) ─────────
    Scholar pages through pathogen_mentions (sorted by frequency) and builds
    a biological profile for each discovered pathogen. Stops when no new
    profiles are saved.

    ─── PHASE 4: DEDUPLICATOR (once) ─────────────────────────────────────────
    Merges duplicate pathogen records before downstream research begins.

    ─── PHASE 5: RESEARCH LOOP (one pathogen per pass, sequential) ───────────
    For each pathogen in the DB (by alphabetical offset):
        Research    — 4-domain PubMed synthesis
        Verifier    — coherence + relevance check on research summaries
        Hypothesis  — research gaps, strategies, wet-lab steps
        Verifier    — coherence + relevance check on hypothesis outputs

    ─── PHASE 6: GRAPH SYNC (once, after all pathogens processed) ────────────
    Pushes the complete, deduplicated, research-enriched pathogen set to Neo4j.

Usage (inside Docker):
    docker compose exec api python run_pipeline.py

Usage (local, with .env):
    cd services/api
    python run_pipeline.py
"""

import asyncio
import sys
import textwrap
import time
from typing import Any

# ── Logging must be configured before any app import ─────────────────────────
from app.core.logging import configure_logging
configure_logging()


# ── Colour helpers ────────────────────────────────────────────────────────────

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_GREEN  = "\033[32m"
_YELLOW = "\033[33m"
_RED    = "\033[31m"
_CYAN   = "\033[36m"
_DIM    = "\033[2m"


def _hdr(title: str) -> None:
    bar = "─" * 60
    print(f"\n{_CYAN}{_BOLD}{bar}{_RESET}")
    print(f"{_CYAN}{_BOLD}  {title}{_RESET}")
    print(f"{_CYAN}{_BOLD}{bar}{_RESET}")


def _pathogen_hdr(idx: int, total: int, name: str = "") -> None:
    bar = "━" * 60
    label = f"Pathogen {idx}/{total}" + (f"  ·  {name}" if name else "")
    print(f"\n{_BOLD}{bar}{_RESET}")
    print(f"{_BOLD}  {label}{_RESET}")
    print(f"{_BOLD}{bar}{_RESET}")


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET}  {msg}")


def _skip(msg: str) -> None:
    print(f"  {_DIM}–  {msg}{_RESET}")


def _warn(msg: str) -> None:
    print(f"  {_YELLOW}⚠{_RESET}  {msg}")


def _err(msg: str) -> None:
    print(f"  {_RED}✗{_RESET}  {msg}")


def _kv(key: str, value: Any) -> None:
    print(f"  {_DIM}{key:<28}{_RESET}{value}")


def _elapsed(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def _print_errors(errors: list[str]) -> None:
    if not errors:
        return
    _warn(f"{len(errors)} error(s):")
    for e in errors[:5]:
        print(f"      {_RED}{textwrap.shorten(e, 100)}{_RESET}")
    if len(errors) > 5:
        print(f"      {_DIM}… and {len(errors) - 5} more{_RESET}")


# ── Stage runner ──────────────────────────────────────────────────────────────

async def _run_stage(label: str, coro) -> dict:
    _hdr(label)
    t0 = time.monotonic()
    try:
        result = await coro
        elapsed = time.monotonic() - t0
        _ok(f"Completed in {_elapsed(elapsed)}")
        return result
    except Exception as exc:
        elapsed = time.monotonic() - t0
        _err(f"Stage failed after {_elapsed(elapsed)}: {type(exc).__name__}: {exc}")
        return {"errors": [str(exc)]}


# ── Stage result printers ─────────────────────────────────────────────────────

def _show_collection(r: dict) -> None:
    _kv("New documents:", r.get("new_documents", 0))
    _kv("Duplicates skipped:", r.get("duplicates", 0))
    _kv("Errors:", r.get("errors", 0))
    dur = r.get("duration_seconds")
    if dur is not None:
        _kv("Fetch time:", f"{dur}s")


def _show_sentinel(r: dict) -> None:
    _kv("Documents processed:", r.get("documents_processed", 0))
    _kv("Unique pathogens found:", r.get("unique_pathogens_found", 0))
    top = r.get("mention_totals", [])[:5]
    if top:
        _kv("Top pathogens:", "")
        for item in top:
            print(f"      {item['pathogen']:<35} {item['mentions']} mention(s)")
    _print_errors(r.get("errors", []))


def _show_scholar(r: dict) -> None:
    _kv("Pathogens researched:", r.get("pathogens_researched", 0))
    _kv("Profiles saved/updated:", r.get("profiles_saved", 0))
    _print_errors(r.get("errors", []))


def _show_mention_dedup(r: dict) -> None:
    _kv("Name groups merged:", r.get("groups_merged", 0))
    _kv("Aliases consolidated:", r.get("names_consolidated", 0))


def _show_dedup(r: dict) -> None:
    _kv("Duplicate groups merged:", r.get("merged_groups", 0))
    _kv("Records removed:", r.get("records_removed", 0))
    _kv("Records updated:", r.get("records_updated", 0))
    _print_errors(r.get("errors", []))


def _show_graph(r: dict) -> None:
    _kv("Pathogens synced to Neo4j:", r.get("pathogens_synced", 0))
    _print_errors(r.get("errors", []))


def _show_research(r: dict) -> None:
    _kv("Pathogens researched:", r.get("pathogens_researched", 0))
    _kv("Articles saved:", r.get("articles_saved", 0))
    _print_errors(r.get("errors", []))


def _show_verifier(r: dict) -> None:
    _kv("Mode:", r.get("mode", "?"))
    _kv("Pathogens checked:", r.get("pathogens_checked", 0))
    _kv("Fields corrected:", r.get("fields_corrected", 0))
    _print_errors(r.get("errors", []))


def _show_hypothesis(r: dict) -> None:
    _kv("Pathogens processed:", r.get("pathogens_processed", 0))
    _kv("Hypotheses saved:", r.get("hypotheses_saved", 0))
    _print_errors(r.get("errors", []))


# ── Database reset ────────────────────────────────────────────────────────────

async def _clear_databases() -> None:
    """Wipe all data before each pipeline run (schema and migrations preserved)."""
    from sqlalchemy import text
    from app.db.session import AsyncSessionLocal

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
            _ok(f"Cleared {table}")
        except Exception as exc:
            _warn(f"Could not clear {table}: {exc}")

    # Neo4j
    try:
        from app.graph.neo4j_client import get_neo4j_driver
        driver = get_neo4j_driver()
        async with driver.session() as neo:
            await neo.run("MATCH (n) DETACH DELETE n")
        await driver.close()
        _ok("Cleared Neo4j graph")
    except Exception as exc:
        _warn(f"Neo4j clear failed: {exc}")

    # Redis
    try:
        import redis.asyncio as aioredis
        from app.config import get_settings
        r = aioredis.from_url(get_settings().redis_url)
        await r.flushall()
        await r.aclose()
        _ok("Cleared Redis")
    except Exception as exc:
        _warn(f"Redis clear failed: {exc}")

    # Qdrant
    try:
        import httpx
        from app.config import get_settings
        base = get_settings().qdrant_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base}/collections")
            resp.raise_for_status()
            for col in resp.json().get("result", {}).get("collections", []):
                await client.delete(f"{base}/collections/{col['name']}")
        _ok("Cleared Qdrant")
    except Exception as exc:
        _warn(f"Qdrant clear failed: {exc}")


# ── Pathogen counter ──────────────────────────────────────────────────────────

async def _count_pathogens() -> int:
    from sqlalchemy import func, select
    from app.db.models.pathogen import Pathogen
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.count()).select_from(Pathogen))
        return result.scalar_one()


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    wall_start = time.monotonic()

    print(f"\n{_BOLD}PathogenIQ — Full Pipeline Run{_RESET}")
    print(f"{_DIM}Collection → Sentinel (drain) → Scholar → Dedup → Research/Hypothesis per pathogen → Graph Sync{_RESET}")

    _hdr("0  Clear — wipe all databases before run")
    await _clear_databases()

    from app.collectors.cdc import CDCCollector
    from app.collectors.ecdc import ECDCCollector
    from app.collectors.news import NewsCollector
    from app.collectors.promed import ProMEDCollector
    from app.collectors.who import WHOCollector
    from app.db.session import AsyncSessionLocal
    from app.services.ingestion import IngestionService

    from app.agents.sentinel import run_sentinel
    from app.agents.scholar import run_scholar
    from app.agents.deduplicator import run_deduplication, run_mention_deduplication
    from app.graph.sync import run_graph_sync
    from app.agents.research import run_research
    from app.agents.verifier import run_verifier
    from app.agents.hypothesis import run_hypothesis

    async def _collect(collector_cls):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                svc = IngestionService(session)
                return await svc.ingest(collector_cls(), max_results=150)

    # ─── Phase 1: Collection (once) ───────────────────────────────────────────

    r = await _run_stage("1/4  Collect — CDC Health Alert Network", _collect(CDCCollector))
    _show_collection(r.model_dump() if hasattr(r, "model_dump") else r)

    _hdr("2/4  Collect — WHO / PAHO / ECDC")
    t0 = time.monotonic()
    who_new = who_dup = who_err = 0
    for cls in (WHOCollector, ECDCCollector):
        try:
            res = await _collect(cls)
            d = res.model_dump() if hasattr(res, "model_dump") else res
            who_new += d.get("new_documents", 0)
            who_dup += d.get("duplicates", 0)
            who_err += d.get("errors", 0)
        except Exception as exc:
            _err(f"{cls.__name__} failed: {exc}")
            who_err += 1
    _ok(f"Completed in {_elapsed(time.monotonic() - t0)}")
    _show_collection({"new_documents": who_new, "duplicates": who_dup, "errors": who_err})

    r = await _run_stage("3/4  Collect — ProMED outbreak intelligence", _collect(ProMEDCollector))
    _show_collection(r.model_dump() if hasattr(r, "model_dump") else r)

    r = await _run_stage("4/4  Collect — News (BBC/STAT/NPR/etc.)", _collect(NewsCollector))
    _show_collection(r.model_dump() if hasattr(r, "model_dump") else r)

    # ─── Phase 2: Sentinel — drain all pending documents ─────────────────────
    # Runs until every PENDING document has had its pathogen mentions extracted.
    # Each call handles one batch; loop exits when documents_processed == 0.

    sentinel_pass = 0
    sentinel_docs_total = 0
    MAX_SENTINEL_PASSES = 50

    while sentinel_pass < MAX_SENTINEL_PASSES:
        r = await _run_stage(
            f"Sentinel — extract pathogen mentions (pass {sentinel_pass + 1})",
            run_sentinel(),
        )
        _show_sentinel(r)
        docs = r.get("documents_processed", 0)
        sentinel_docs_total += docs
        sentinel_pass += 1
        if docs == 0:
            _ok(
                f"Sentinel drain complete — {sentinel_docs_total} document(s) "
                f"processed across {sentinel_pass - 1} pass(es)"
            )
            break
    else:
        _warn(f"Sentinel hit safety limit ({MAX_SENTINEL_PASSES} passes). Some documents may remain PENDING.")

    # ─── Phase 2.5: Mention-level dedup — before Scholar profiles anything ──────
    # Consolidates "Measles" + "Measles morbillivirus" → "Measles morbillivirus"
    # in the pathogen_mentions table so Scholar profiles each canonical name once.

    r = await _run_stage(
        "Mention Dedup — consolidate duplicate pathogen names",
        run_mention_deduplication(),
    )
    _show_mention_dedup(r)

    # ─── Phase 3: Scholar — profile every discovered pathogen ─────────────────
    # Pages through pathogen_mentions (sorted by frequency) until all pathogens
    # have a biological profile. Each call profiles one pathogen.

    scholar_offset = 0
    scholar_total = 0
    MAX_SCHOLAR_PASSES = 500

    for _ in range(MAX_SCHOLAR_PASSES):
        r = await _run_stage(
            f"Scholar — biological profile synthesis (offset {scholar_offset})",
            run_scholar(offset=scholar_offset),
        )
        _show_scholar(r)
        saved = r.get("profiles_saved", 0)
        errors = r.get("errors", [])
        scholar_total += saved
        if saved == 0 and not errors:
            # No targets remain — truly done.
            _ok(f"Scholar complete — {scholar_total} profile(s) saved")
            break
        elif saved == 0 and errors:
            # This offset's pathogen failed (e.g. JSON parse error from LLM).
            # Advance by 1 so we don't retry the same pathogen forever.
            _warn(f"Scholar: pathogen at offset {scholar_offset} failed — skipping")
            scholar_offset += 1
        else:
            scholar_offset += saved
    else:
        _warn(f"Scholar hit safety limit ({MAX_SCHOLAR_PASSES} passes).")

    # ─── Phase 4: Deduplicator (once, after all pathogens profiled) ───────────

    r = await _run_stage("Deduplicator — merge duplicate pathogen records", run_deduplication())
    _show_dedup(r)

    # ─── Phase 5: Research + Hypothesis loop (one pathogen per iteration) ─────
    # total_pathogens is fixed after dedup; each iteration targets one DB row
    # by SQL OFFSET so every pathogen is covered exactly once.

    total_pathogens = await _count_pathogens()

    if total_pathogens == 0:
        _warn("No pathogens in DB — skipping research loop.")
    else:
        _ok(f"Starting research loop — {total_pathogens} pathogen(s) to process")

        for pathogen_idx in range(total_pathogens):
            _pathogen_hdr(pathogen_idx + 1, total_pathogens)

            r = await _run_stage(
                f"Research — 4-domain PubMed synthesis ({pathogen_idx + 1}/{total_pathogens})",
                run_research(offset=pathogen_idx),
            )
            _show_research(r)

            r = await _run_stage(
                f"Verifier — research summaries ({pathogen_idx + 1}/{total_pathogens})",
                run_verifier("research"),
            )
            _show_verifier(r)

            r = await _run_stage(
                f"Hypothesis — strategies & wet-lab steps ({pathogen_idx + 1}/{total_pathogens})",
                run_hypothesis(offset=pathogen_idx),
            )
            _show_hypothesis(r)

            r = await _run_stage(
                f"Verifier — hypothesis outputs ({pathogen_idx + 1}/{total_pathogens})",
                run_verifier("hypothesis"),
            )
            _show_verifier(r)

    # ─── Phase 6: Graph Sync (once, after all pathogens are enriched) ─────────

    r = await _run_stage(
        "Graph Sync — push all pathogens to Neo4j",
        run_graph_sync(),
    )
    _show_graph(r)

    # ─── Summary ──────────────────────────────────────────────────────────────

    total = time.monotonic() - wall_start
    bar = "═" * 60
    print(f"\n{_GREEN}{_BOLD}{bar}{_RESET}")
    print(
        f"{_GREEN}{_BOLD}  Pipeline complete"
        f"  ·  {total_pathogens} pathogen(s)"
        f"  ·  Total time: {_elapsed(total)}{_RESET}"
    )
    print(f"{_GREEN}{_BOLD}{bar}{_RESET}\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{_YELLOW}Interrupted by user.{_RESET}\n")
        sys.exit(1)
