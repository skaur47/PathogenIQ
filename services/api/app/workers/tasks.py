"""
ARQ task functions — the actual work units run by the worker process.

HOW ARQ TASKS WORK:
  1. The API (or the cron scheduler) calls arq_redis.enqueue_job("task_collect_cdc")
     which writes a job record to Redis.
  2. The worker process polls Redis, picks up the job, and calls the function.
  3. The function runs, returns a result dict, which ARQ stores back in Redis.
  4. The API can query job status via GET /api/v1/ingestion/jobs/{job_id}.

THE ctx ARGUMENT:
  Every ARQ task receives a `ctx` dict as its first argument. ARQ injects:
    ctx["redis"]  — the ArqRedis connection (the worker's Redis pool)
    ctx["job_id"] — unique job identifier for logging
  Additional keys can be added in WorkerSettings.on_startup() (e.g., a DB engine).
  We don't store DB state in ctx because AsyncSessionLocal handles connection
  pooling at the module level — sessions are cheap to create per task.

DATABASE SESSIONS IN TASKS:
  Tasks use `async with AsyncSessionLocal() as session: async with session.begin():`
  because they run OUTSIDE FastAPI's request lifecycle. There's no `get_session`
  dependency available. session.begin() auto-commits on success, auto-rollbacks
  on exception — the same contract as our HTTP session middleware.

RETURN VALUES:
  Tasks return dict (not Pydantic models) because ARQ serialises them to JSON
  for Redis storage. IngestionResult.model_dump(mode="json") converts datetime
  fields to ISO strings, which is what ARQ's JSON encoder expects.

IDEMPOTENCY:
  Running the same task twice is safe. The IngestionService's ON CONFLICT DO NOTHING
  means re-collecting the same articles just counts them as duplicates.

PUBMED:
  PubMed collection is intentionally excluded from Phase 2. PubMed requires a
  structured NCBI ESearch query and is best paired with the LiteratureAgent
  (Scholar) that processes abstracts with embeddings. It will be wired in Phase 3.
  The collector implementation lives in collectors/pubmed.py.
"""

import structlog

from app.core.logging import configure_logging
from app.db.session import AsyncSessionLocal
from app.collectors.cdc import CDCCollector
from app.collectors.ecdc import ECDCCollector
from app.collectors.news import NewsCollector
from app.collectors.promed import ProMEDCollector
from app.collectors.who import WHOCollector
from app.services.ingestion import IngestionService

logger = structlog.get_logger(__name__)


async def task_collect_cdc(ctx: dict, max_results: int = 150) -> dict:
    """
    Collect CDC Health Alert Network advisories.

    Called automatically every 4 hours.
    The CDC HAN feed refreshes when CDC publishes new health alerts.
    """
    configure_logging()
    log = logger.bind(task="collect_cdc", job_id=ctx.get("job_id"))
    log.info("task_start")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            service = IngestionService(session)
            result = await service.ingest(CDCCollector(), max_results=max_results)

    log.info("task_done", new=result.new_documents, duplicates=result.duplicates)
    return result.model_dump(mode="json")


async def task_collect_who(ctx: dict, max_results: int = 150) -> dict:
    """
    Collect WHO-affiliated outbreak reports: PAHO (Americas) + ECDC (Europe).

    Called automatically every 4 hours. Runs both collectors sequentially
    and returns combined stats. Both use source=who in the database.
    """
    configure_logging()
    log = logger.bind(task="collect_who", job_id=ctx.get("job_id"))
    log.info("task_start")

    total_new = total_dup = total_err = 0

    for CollectorClass in (WHOCollector, ECDCCollector):
        async with AsyncSessionLocal() as session:
            async with session.begin():
                service = IngestionService(session)
                result = await service.ingest(CollectorClass(), max_results=max_results)
        total_new += result.new_documents
        total_dup += result.duplicates
        total_err += result.errors

    log.info("task_done", new=total_new, duplicates=total_dup, errors=total_err)

    from app.collectors.schemas import IngestionResult
    from datetime import datetime, timezone
    combined = IngestionResult(
        source="who",
        new_documents=total_new,
        duplicates=total_dup,
        errors=total_err,
    )
    return combined.model_dump(mode="json")


async def task_collect_promed(ctx: dict, max_results: int = 150) -> dict:
    """
    Collect ProMED outbreak intelligence reports.

    ProMED is the world's leading early-warning system for emerging infectious
    diseases. Every post is expert-curated — no relevance filter needed.
    Called automatically every 6 hours.
    """
    configure_logging()
    log = logger.bind(task="collect_promed", job_id=ctx.get("job_id"))
    log.info("task_start")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            service = IngestionService(session)
            result = await service.ingest(ProMEDCollector(), max_results=max_results)

    log.info("task_done", new=result.new_documents, duplicates=result.duplicates)
    return result.model_dump(mode="json")


async def task_collect_news(ctx: dict, max_results: int = 150) -> dict:
    """
    Collect outbreak-relevant news from BBC Health, STAT News, NPR Health,
    Outbreak News Today, and ScienceDaily.

    Relevance filter built into NewsCollector — only pathogen/outbreak content
    is ingested. Called automatically every 4 hours (offset to stagger DB load).
    """
    configure_logging()
    log = logger.bind(task="collect_news", job_id=ctx.get("job_id"))
    log.info("task_start")

    async with AsyncSessionLocal() as session:
        async with session.begin():
            service = IngestionService(session)
            result = await service.ingest(NewsCollector(), max_results=max_results)

    log.info("task_done", new=result.new_documents, duplicates=result.duplicates)
    return result.model_dump(mode="json")


# ── Phase 3 — AI agents ───────────────────────────────────────────────────────

async def task_run_sentinel(ctx: dict) -> dict:
    """
    Run the Sentinel Agent: process all PENDING documents, extract pathogen
    mentions, and write a frequency table to the pathogen_mentions table.

    After completing, automatically enqueues task_run_scholar if at least
    one pathogen was found — so the two agents run as a natural pipeline
    without requiring a separate trigger.

    Triggered manually via POST /api/v1/agents/trigger/sentinel, or
    automatically after any ingestion run (Phase 4 cron integration).
    """
    configure_logging()
    log = logger.bind(task="run_sentinel", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.sentinel import run_sentinel
    result = await run_sentinel()

    log.info(
        "task_done",
        documents_processed=result.get("documents_processed", 0),
        unique_pathogens=result.get("unique_pathogens_found", 0),
    )

    # Chain Scholar automatically when Sentinel found pathogens
    arq_redis = ctx.get("redis")
    if arq_redis and result.get("unique_pathogens_found", 0) > 0:
        await arq_redis.enqueue_job("task_run_scholar")
        log.info("scholar_enqueued")


    return result


async def task_run_scholar(ctx: dict) -> dict:
    """
    Run the Scholar Agent: for each pathogen in the pathogen_mentions table,
    query PubMed for recent literature and synthesize a biological profile
    (transmission, fatality, genome type, reservoir hosts, etc.) using Claude.

    Profiles are upserted into the pathogens table. Normally triggered
    automatically by task_run_sentinel, but can also be triggered manually
    via POST /api/v1/agents/trigger/scholar to refresh profiles from latest
    PubMed without re-running the full ingestion pipeline.
    """
    configure_logging()
    log = logger.bind(task="run_scholar", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.scholar import run_scholar
    result = await run_scholar()

    log.info(
        "task_done",
        pathogens_researched=result.get("pathogens_researched", 0),
        profiles_saved=result.get("profiles_saved", 0),
    )

    # Chain deduplication automatically after Scholar completes
    arq_redis = ctx.get("redis")
    if arq_redis and result.get("profiles_saved", 0) > 0:
        await arq_redis.enqueue_job("task_run_dedup")
        log.info("dedup_enqueued")

    return result


async def task_run_dedup(ctx: dict) -> dict:
    """
    Run the Deduplicator: merge pathogen records that refer to the same
    organism under different names (case variants, partial names).

    After completing, automatically enqueues task_sync_graph so the Neo4j
    knowledge graph reflects the cleaned, merged data.

    Triggered automatically by task_run_scholar, or manually via
    POST /api/v1/agents/trigger/dedup.
    """
    configure_logging()
    log = logger.bind(task="run_dedup", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.deduplicator import run_deduplication
    result = await run_deduplication()

    log.info(
        "task_done",
        merged_groups=result.get("merged_groups", 0),
        records_removed=result.get("records_removed", 0),
    )

    # Chain graph sync after deduplication
    arq_redis = ctx.get("redis")
    if arq_redis:
        await arq_redis.enqueue_job("task_sync_graph")
        log.info("graph_sync_enqueued")

    return result


async def task_run_research(ctx: dict) -> dict:
    """
    Run the Research Agent: for each pathogen in the database, execute four
    targeted PubMed queries (infection mechanism, wet-lab, clinical trials,
    vaccines/therapies), summarise each article with the local LLM, and
    synthesise a four-section landscape summary per pathogen.

    Results are stored in research_articles and pathogen_research_summaries.
    Source URLs (PubMed links) are stored alongside each article summary.

    Triggered manually via POST /api/v1/agents/trigger/research.
    Can be re-run at any time to refresh summaries from the latest literature.
    """
    configure_logging()
    log = logger.bind(task="run_research", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.research import run_research
    result = await run_research()

    log.info(
        "task_done",
        pathogens_researched=result.get("pathogens_researched", 0),
        articles_saved=result.get("articles_saved", 0),
        errors=len(result.get("errors", [])),
    )

    # Auto-chain verifier after research completes
    arq_redis = ctx.get("redis")
    if arq_redis and result.get("pathogens_researched", 0) > 0:
        await arq_redis.enqueue_job("task_run_verifier_research")
        log.info("verifier_research_enqueued")

    return result


async def task_run_hypothesis(ctx: dict) -> dict:
    """
    Run the Hypothesis Agent: for each pathogen, reads across all evidence
    (biological profile, research landscape, outbreak signal) and synthesizes:
      - The critical research gap
      - A specific therapeutic/vaccine strategy with biological rationale
      - Numbered wet-lab experiments (model, assay, hypothesis)
      - Numbered clinical/epidemiological approaches
      - An overall strategic recommendation

    Results are stored in pathogen_hypotheses. Re-running refreshes all sections.
    Triggered manually via POST /api/v1/agents/trigger/hypothesis.
    """
    configure_logging()
    log = logger.bind(task="run_hypothesis", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.hypothesis import run_hypothesis
    result = await run_hypothesis()

    log.info(
        "task_done",
        pathogens_processed=result.get("pathogens_processed", 0),
        hypotheses_saved=result.get("hypotheses_saved", 0),
        errors=len(result.get("errors", [])),
    )

    # Auto-chain verifier after hypothesis completes
    arq_redis = ctx.get("redis")
    if arq_redis and result.get("hypotheses_saved", 0) > 0:
        await arq_redis.enqueue_job("task_run_verifier_hypothesis")
        log.info("verifier_hypothesis_enqueued")

    return result


async def task_run_verifier_research(ctx: dict) -> dict:
    """
    Run the Verifier Agent in research mode.

    Checks every PathogenResearchSummary field for coherence (no garbage,
    error strings, or fragments) and biological relevance to the named
    pathogen. Corrections are written back to the DB immediately.

    Triggered manually via POST /api/v1/agents/trigger/verify-research,
    or automatically after task_run_research completes.
    """
    configure_logging()
    log = logger.bind(task="run_verifier_research", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.verifier import run_verifier
    result = await run_verifier("research")

    log.info(
        "task_done",
        pathogens_checked=result.get("pathogens_checked", 0),
        fields_corrected=result.get("fields_corrected", 0),
        errors=len(result.get("errors", [])),
    )
    return result


async def task_run_verifier_hypothesis(ctx: dict) -> dict:
    """
    Run the Verifier Agent in hypothesis mode.

    Checks every PathogenHypothesis field for coherence and biological
    relevance. Corrections are written back to the DB immediately.

    Triggered manually via POST /api/v1/agents/trigger/verify-hypothesis,
    or automatically after task_run_hypothesis completes.
    """
    configure_logging()
    log = logger.bind(task="run_verifier_hypothesis", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.agents.verifier import run_verifier
    result = await run_verifier("hypothesis")

    log.info(
        "task_done",
        pathogens_checked=result.get("pathogens_checked", 0),
        fields_corrected=result.get("fields_corrected", 0),
        errors=len(result.get("errors", [])),
    )
    return result


async def task_run_full_pipeline(ctx: dict) -> dict:
    """
    Run the complete PathogenIQ pipeline in one shot.

    Order:
      1. Collect — CDC, WHO/ECDC, ProMED, News
      2. Sentinel drain — process all PENDING docs
      3. Mention dedup — consolidate name variants
      4. Scholar loop — profile every discovered pathogen
      5. Dedup — merge duplicate pathogen records
      6. Research + Verifier — PubMed synthesis for all pathogens
      7. Hypothesis + Verifier — strategy synthesis for all pathogens
      8. Graph sync — push enriched data to Neo4j

    Scheduled daily at 02:00 UTC via WorkerSettings.cron_jobs.
    """
    configure_logging()
    import time
    log = logger.bind(task="run_full_pipeline", job_id=ctx.get("job_id"))
    log.info("task_start")
    t0 = time.monotonic()
    results: dict = {}

    # ── Phase 1: Collection ───────────────────────────────────────────────────
    from app.collectors.ecdc import ECDCCollector as _ECDC
    from app.collectors.who import WHOCollector as _WHO
    for CollectorClass, name in [
        (CDCCollector,    "cdc"),
        (_WHO,            "who"),
        (_ECDC,           "ecdc"),
        (ProMEDCollector, "promed"),
        (NewsCollector,   "news"),
    ]:
        try:
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    svc = IngestionService(session)
                    r = await svc.ingest(CollectorClass(), max_results=150)
            results[f"collect_{name}"] = r.new_documents
            log.info(f"collect_{name}_done", new=r.new_documents, dups=r.duplicates)
        except Exception as exc:
            log.error(f"collect_{name}_failed", error=str(exc))

    # ── Phase 2: Sentinel drain ───────────────────────────────────────────────
    from app.agents.sentinel import run_sentinel
    sentinel_total = 0
    for _ in range(50):
        r = await run_sentinel()
        docs = r.get("documents_processed", 0)
        sentinel_total += docs
        if docs == 0:
            break
    results["sentinel_docs"] = sentinel_total
    log.info("sentinel_done", total_docs=sentinel_total)

    # ── Phase 2.5: Mention dedup ──────────────────────────────────────────────
    from app.agents.deduplicator import run_mention_deduplication, run_deduplication
    await run_mention_deduplication()

    # ── Phase 3: Scholar loop ─────────────────────────────────────────────────
    from app.agents.scholar import run_scholar
    scholar_offset = 0
    scholar_saved = 0
    for _ in range(500):
        r = await run_scholar(offset=scholar_offset)
        saved = r.get("profiles_saved", 0)
        errors = r.get("errors", [])
        if saved == 0 and not errors:
            break
        scholar_offset += saved if saved else 1
        scholar_saved += saved
    results["scholar_profiles"] = scholar_saved
    log.info("scholar_done", profiles=scholar_saved)

    # ── Phase 4: Dedup ────────────────────────────────────────────────────────
    r = await run_deduplication()
    log.info("dedup_done", merged=r.get("merged_groups", 0))

    # ── Phase 5: Research + Verifier ─────────────────────────────────────────
    from app.agents.research import run_research
    from app.agents.verifier import run_verifier
    r = await run_research()
    results["research_articles"] = r.get("articles_saved", 0)
    log.info("research_done", articles=r.get("articles_saved", 0))
    await run_verifier("research")

    # ── Phase 6: Hypothesis + Verifier ───────────────────────────────────────
    from app.agents.hypothesis import run_hypothesis
    r = await run_hypothesis()
    results["hypotheses_saved"] = r.get("hypotheses_saved", 0)
    log.info("hypothesis_done", saved=r.get("hypotheses_saved", 0))
    await run_verifier("hypothesis")

    # ── Phase 7: Graph sync ───────────────────────────────────────────────────
    from app.graph.sync import run_graph_sync
    r = await run_graph_sync()
    results["graph_synced"] = r.get("pathogens_synced", 0)
    log.info("graph_sync_done", synced=r.get("pathogens_synced", 0))

    results["elapsed_seconds"] = round(time.monotonic() - t0)
    log.info("task_done", elapsed_s=results["elapsed_seconds"])
    return results


async def task_send_newsletter(ctx: dict) -> dict:
    """
    Send the daily PathogenIQ digest to all active newsletter subscribers.

    For each pathogen, includes: biological summary, 1-2 recent news/surveillance
    documents, and 1 research article. Guarded by a Redis key so the digest is
    sent at most once per calendar day regardless of how many times the task is
    triggered (cron at 08:00 UTC + manual pipeline run).

    Scheduled daily at 08:00 UTC by WorkerSettings.cron_jobs.
    """
    configure_logging()
    log = logger.bind(task="send_newsletter", job_id=ctx.get("job_id"))
    log.info("task_start")

    from datetime import date
    from sqlalchemy import select
    from app.db.models.document import Document
    from app.db.models.pathogen_mention import PathogenMention
    from app.db.models.research import ResearchArticle
    from app.repositories.newsletter import NewsletterRepository
    from app.repositories.pathogen import PathogenRepository
    from app.services.newsletter import send_digest_to

    # Once-per-day guard: prevent double-sends when cron + manual pipeline both fire
    arq_redis = ctx.get("redis")
    today = date.today().isoformat()
    if arq_redis:
        guard_key = f"newsletter:sent:{today}"
        if await arq_redis.get(guard_key):
            log.info("newsletter_already_sent_today", date=today)
            return {"sent": 0, "reason": "already_sent_today", "date": today}
        await arq_redis.set(guard_key, "1", ex=60 * 60 * 25)

    async with AsyncSessionLocal() as session:
        sub_repo = NewsletterRepository(session)
        path_repo = PathogenRepository(session)
        subscribers = await sub_repo.get_active_subscribers()
        pathogens_orm = await path_repo.get_all()

        pathogens = []
        for p in pathogens_orm:
            # 1-2 most recent surveillance/news documents mentioning this pathogen
            news_result = await session.execute(
                select(Document)
                .join(PathogenMention, Document.id == PathogenMention.document_id)
                .where(PathogenMention.pathogen_name == p.species_name)
                .where(Document.title.isnot(None))
                .order_by(Document.created_at.desc())
                .limit(2)
            )
            news_docs = list(news_result.scalars().all())

            # 1 most recent research article
            research_result = await session.execute(
                select(ResearchArticle)
                .where(ResearchArticle.pathogen_id == p.id)
                .where(ResearchArticle.title.isnot(None))
                .order_by(ResearchArticle.published_date.desc().nulls_last())
                .limit(1)
            )
            research_article = research_result.scalar_one_or_none()

            pathogens.append({
                "species_name": p.species_name,
                "common_name": p.common_name,
                "category": p.category.value if p.category else None,
                "transmission_routes": p.transmission_routes or [],
                "reservoir_hosts": p.reservoir_hosts or [],
                "who_priority": p.who_priority,
                "description": p.description,
                "news_articles": [
                    {
                        "title": doc.title,
                        "url": doc.url,
                        "source": doc.source.value,
                        "published_date": doc.published_date,
                    }
                    for doc in news_docs
                ],
                "research_article": {
                    "title": research_article.title,
                    "authors": research_article.authors,
                    "url": research_article.source_url,
                    "published_date": research_article.published_date,
                    "summary": research_article.article_summary,
                } if research_article else None,
            })

    sent = 0
    for sub in subscribers:
        await send_digest_to(sub, pathogens)
        sent += 1

    log.info("task_done", subscribers=len(subscribers), sent=sent)
    return {"sent": sent, "subscribers": len(subscribers)}


async def task_sync_graph(ctx: dict) -> dict:
    """
    Sync all pathogen profiles from PostgreSQL into the Neo4j knowledge graph.

    Builds or refreshes nodes and edges:
      (:Pathogen)-[:IN_CATEGORY]->(:Category)
      (:Pathogen)-[:SPREADS_VIA]->(:TransmissionRoute)
      (:Pathogen)-[:HOSTED_BY]->(:ReservoirHost)

    Fully idempotent — safe to run multiple times. All writes use MERGE.

    Triggered automatically by task_run_dedup, or manually via
    POST /api/v1/agents/trigger/graph-sync.
    """
    configure_logging()
    log = logger.bind(task="sync_graph", job_id=ctx.get("job_id"))
    log.info("task_start")

    from app.graph.sync import run_graph_sync
    result = await run_graph_sync()

    log.info("task_done", pathogens_synced=result.get("pathogens_synced", 0))
    return result
