"""
PathogenIQ — partial pipeline: Collection → Sentinel → Scholar → Dedup only.

Runs only through Phase 4 (pathogen DB generation). Skips the Research,
Hypothesis, and Graph Sync phases. Use this to test and validate that
transmission_routes and reservoir_hosts are being assigned correctly before
running the full pipeline.

Usage (inside Docker):
    docker compose exec api python run_pipeline_pathogens.py

Usage (local, with .env):
    cd services/api
    python run_pipeline_pathogens.py
"""

import asyncio
import sys
import textwrap
import time
from typing import Any

from app.core.logging import configure_logging
configure_logging()


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


def _ok(msg: str) -> None:
    print(f"  {_GREEN}✓{_RESET}  {msg}")


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


def _show_collection(r: dict) -> None:
    _kv("New documents:", r.get("new_documents", 0))
    _kv("Duplicates skipped:", r.get("duplicates", 0))
    _kv("Errors:", r.get("errors", 0))


def _show_sentinel(r: dict) -> None:
    _kv("Documents processed:", r.get("documents_processed", 0))
    _kv("Unique pathogens found:", r.get("unique_pathogens_found", 0))
    top = r.get("mention_totals", [])[:5]
    if top:
        _kv("Top pathogens:", "")
        for item in top:
            print(f"      {item['pathogen']:<35} {item['mentions']} mention(s)")
    _print_errors(r.get("errors", []))


def _show_mention_dedup(r: dict) -> None:
    _kv("Name groups merged:", r.get("groups_merged", 0))
    _kv("Aliases consolidated:", r.get("names_consolidated", 0))


def _show_scholar(r: dict) -> None:
    _kv("Pathogens researched:", r.get("pathogens_researched", 0))
    _kv("Profiles saved/updated:", r.get("profiles_saved", 0))
    _print_errors(r.get("errors", []))


def _show_dedup(r: dict) -> None:
    _kv("Duplicate groups merged:", r.get("merged_groups", 0))
    _kv("Records removed:", r.get("records_removed", 0))
    _kv("Records updated:", r.get("records_updated", 0))
    _print_errors(r.get("errors", []))


async def _count_pathogens() -> int:
    from sqlalchemy import func, select
    from app.db.models.pathogen import Pathogen
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(func.count()).select_from(Pathogen))
        return result.scalar_one()


async def main() -> None:
    wall_start = time.monotonic()

    print(f"\n{_BOLD}PathogenIQ — Pathogen DB Generation (Phases 1–4){_RESET}")
    print(f"{_DIM}Collection → Sentinel → Scholar → Dedup  (no Research / Hypothesis / Graph){_RESET}")

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

    async def _collect(collector_cls):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                svc = IngestionService(session)
                return await svc.ingest(collector_cls(), max_results=150)

    # ─── Phase 1: Collection ──────────────────────────────────────────────────

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

    # ─── Phase 2: Sentinel drain ──────────────────────────────────────────────

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
        _warn(f"Sentinel hit safety limit ({MAX_SENTINEL_PASSES} passes).")

    # ─── Phase 2.5: Mention dedup ─────────────────────────────────────────────

    r = await _run_stage(
        "Mention Dedup — consolidate duplicate pathogen names",
        run_mention_deduplication(),
    )
    _show_mention_dedup(r)

    # ─── Phase 3: Scholar ─────────────────────────────────────────────────────

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
            _ok(f"Scholar complete — {scholar_total} profile(s) saved")
            break
        elif saved == 0 and errors:
            _warn(f"Scholar: pathogen at offset {scholar_offset} failed — skipping")
            scholar_offset += 1
        else:
            scholar_offset += saved
    else:
        _warn(f"Scholar hit safety limit ({MAX_SCHOLAR_PASSES} passes).")

    # ─── Phase 4: Deduplicator ────────────────────────────────────────────────

    r = await _run_stage("Deduplicator — merge duplicate pathogen records", run_deduplication())
    _show_dedup(r)

    # ─── Summary ──────────────────────────────────────────────────────────────

    total_pathogens = await _count_pathogens()
    total = time.monotonic() - wall_start
    bar = "═" * 60
    print(f"\n{_GREEN}{_BOLD}{bar}{_RESET}")
    print(
        f"{_GREEN}{_BOLD}  Pathogen DB generation complete"
        f"  ·  {total_pathogens} pathogen(s)"
        f"  ·  Total time: {_elapsed(total)}{_RESET}"
    )
    print(f"{_GREEN}{_BOLD}{bar}{_RESET}\n")

    # ─── Print pathogen summary ───────────────────────────────────────────────
    print(f"{_BOLD}Pathogen profiles in DB:{_RESET}")
    from sqlalchemy import select
    from app.db.models.pathogen import Pathogen
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Pathogen).order_by(Pathogen.species_name)
        )
        pathogens = result.scalars().all()
        for p in pathogens:
            routes = ", ".join(p.transmission_routes or []) or "—"
            hosts  = ", ".join(p.reservoir_hosts or []) or "—"
            print(f"  {_BOLD}{p.species_name:<35}{_RESET} [{p.category.value if p.category else '?'}]")
            print(f"    routes : {routes}")
            print(f"    hosts  : {hosts}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{_YELLOW}Interrupted by user.{_RESET}\n")
        sys.exit(1)
