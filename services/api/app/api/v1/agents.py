"""
Agents API — trigger AI agents and query their outputs.

TRIGGER ENDPOINTS:
  POST /agents/trigger/sentinel    → enqueue Sentinel Agent (202 + job_id)
  POST /agents/trigger/scholar     → enqueue Scholar Agent  (202 + job_id)
  POST /agents/trigger/dedup       → enqueue Deduplicator   (202 + job_id)
  POST /agents/trigger/graph-sync  → enqueue Graph Sync     (202 + job_id)
  POST /agents/trigger/research    → enqueue Research Agent (202 + job_id)

QUERY ENDPOINTS:
  GET  /agents/mentions                  → pathogen frequency table (Sentinel)
  GET  /agents/pathogens                 → biological profiles      (Scholar)
  GET  /agents/research/{pathogen_name}  → literature landscape + source links
  GET  /agents/research                  → all researched pathogens (index)

AGENT PIPELINE:
  Sentinel → Scholar → Dedup → GraphSync  (automatic chain)
  Research  (independent, run after the chain to deep-dive each pathogen)

JOB STATUS:
  All trigger endpoints return a job_id. Poll
  GET /api/v1/ingestion/jobs/{job_id} for completion status.
"""

from collections import defaultdict
from datetime import date, timedelta
from typing import Any

import structlog
from arq.jobs import Job, JobStatus
from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.db.models.document import Document
from app.db.models.hypothesis import PathogenHypothesis
from app.db.models.pathogen import Pathogen
from app.db.models.pathogen_mention import PathogenMention
from app.db.models.research import PathogenResearchSummary, ResearchArticle
from app.db.session import AsyncSessionLocal
from app.graph.neo4j_client import get_neo4j_driver
from app.repositories.hypothesis import HypothesisRepository
from app.repositories.pathogen import PathogenRepository
from app.repositories.pathogen_mention import PathogenMentionRepository
from app.repositories.research import ResearchRepository

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


# ── Response schemas ──────────────────────────────────────────────────────────

class AgentTriggerResponse(BaseModel):
    job_id: str
    agent: str
    status: str = "queued"
    message: str


class PathogenMentionCount(BaseModel):
    pathogen_name: str
    total_mentions: int
    document_count: int


class MentionsResponse(BaseModel):
    mentions: list[PathogenMentionCount]
    total_pathogens: int


class PathogenProfile(BaseModel):
    species_name: str
    common_name: str | None
    category: str
    genome_type: str | None
    transmission_routes: list[str] | None
    reservoir_hosts: list[str] | None
    description: str | None
    who_priority: bool
    ncbi_taxonomy_id: str | None


class PathogensResponse(BaseModel):
    pathogens: list[PathogenProfile]
    total: int


# Maps ArticleCategory value → human-readable sub-agent name for source attribution
_CATEGORY_TO_AGENT: dict[str, str] = {
    "molecular_biology": "Molecular Biology Agent",
    "experiments": "Experiments Agent",
    "therapeutics": "Therapeutics Agent",
    "clinical_epidemiology": "Clinical Epidemiology Agent",
    # Legacy v1 categories
    "infection_mechanism": "Research Agent (v1)",
    "wet_lab": "Research Agent (v1)",
    "clinical_trial": "Research Agent (v1)",
    "vaccine_therapy": "Research Agent (v1)",
}


class ResearchArticleOut(BaseModel):
    pmid: str | None
    title: str
    authors: str | None
    published_date: str | None
    article_category: str
    gathered_by: str  # which sub-agent collected this article
    source_url: str | None
    article_summary: str | None


class PathogenResearchOut(BaseModel):
    pathogen_name: str
    overall_summary: str | None
    # Phase 4 v2 sub-agent summaries
    molecular_biology_summary: str | None
    experiments_summary: str | None
    therapeutics_summary: str | None
    clinical_epi_summary: str | None
    # Phase 4 v1 legacy summaries (populated by older runs)
    infection_mechanism_summary: str | None
    wet_lab_summary: str | None
    clinical_trial_summary: str | None
    vaccine_therapy_summary: str | None
    article_count: int
    last_researched_at: str | None
    articles: list[ResearchArticleOut]


class ResearchIndexItem(BaseModel):
    pathogen_name: str
    article_count: int
    last_researched_at: str | None
    has_overall_summary: bool


class ResearchIndexResponse(BaseModel):
    pathogens: list[ResearchIndexItem]
    total: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_arq_redis(request: Request):
    arq_redis = getattr(request.app.state, "arq_redis", None)
    if arq_redis is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable. Check Redis via GET /api/v1/health.",
        )
    return arq_redis


# ── Trigger endpoints ─────────────────────────────────────────────────────────

@router.post(
    "/trigger/sentinel",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Sentinel Agent",
    description=(
        "Process all PENDING documents: extract pathogen mentions, normalize names, "
        "count occurrences, and write results to the pathogen_mentions table. "
        "Automatically chains Scholar on completion."
    ),
)
async def trigger_sentinel(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_sentinel")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Sentinel job.",
        )
    logger.info("sentinel_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="sentinel",
        message=(
            "Sentinel Agent queued. It will extract pathogen mentions from all "
            "PENDING documents, then automatically enqueue the Scholar Agent. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/scholar",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Scholar Agent",
    description=(
        "For each pathogen in the mentions table, query PubMed for recent literature "
        "and synthesize a biological profile (transmission, fatality, genome type, etc.). "
        "Upserts results into the pathogens table, then enqueues deduplication."
    ),
)
async def trigger_scholar(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_scholar")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Scholar job.",
        )
    logger.info("scholar_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="scholar",
        message=(
            "Scholar Agent queued. It will research each discovered pathogen via PubMed "
            "and synthesize biological profiles, then automatically run deduplication "
            "and graph sync. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/dedup",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Deduplicator",
    description=(
        "Merge pathogen records that refer to the same organism under different names "
        "(case variants, partial names). After merging, automatically enqueues graph sync."
    ),
)
async def trigger_dedup(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_dedup")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Dedup job.",
        )
    logger.info("dedup_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="deduplicator",
        message=(
            "Deduplicator queued. It will merge case-variant and partial-name duplicates "
            "in the pathogens table, then automatically run graph sync. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/graph-sync",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sync Neo4j knowledge graph",
    description=(
        "Sync all pathogen profiles from PostgreSQL into Neo4j. "
        "Builds/refreshes (:Pathogen)-[:IN_CATEGORY]->(:Category), "
        "(:Pathogen)-[:SPREADS_VIA]->(:TransmissionRoute), and "
        "(:Pathogen)-[:HOSTED_BY]->(:ReservoirHost) nodes and edges. "
        "Fully idempotent — safe to run multiple times."
    ),
)
async def trigger_graph_sync(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_sync_graph")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue graph sync job.",
        )
    logger.info("graph_sync_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="graph_sync",
        message=(
            "Graph sync queued. It will build/refresh pathogen nodes and "
            "category/transmission/host edges in Neo4j. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


# ── Query endpoints ───────────────────────────────────────────────────────────

@router.get(
    "/mentions",
    response_model=MentionsResponse,
    summary="Pathogen frequency table",
    description=(
        "Returns the total mention count per pathogen across all ingested documents, "
        "ordered by frequency descending. Populated by the Sentinel Agent."
    ),
)
async def get_mentions() -> MentionsResponse:
    """
    Aggregate pathogen mention counts across all documents in the database.

    Example response:
        {"mentions": [{"pathogen_name": "SARS-CoV-2", "total_mentions": 17, "document_count": 5}, ...]}
    """
    async with AsyncSessionLocal() as session:
        repo = PathogenMentionRepository(session)
        counts = await repo.get_aggregate_counts()

    return MentionsResponse(
        mentions=[PathogenMentionCount(**row) for row in counts],
        total_pathogens=len(counts),
    )


@router.get(
    "/pathogens",
    response_model=PathogensResponse,
    summary="Pathogen biological profiles",
    description=(
        "Returns biological profiles synthesized by the Scholar Agent: "
        "transmission routes, reservoir hosts, genome type, fatality rates, "
        "WHO priority status, and pandemic potential scores."
    ),
)
async def get_pathogens(limit: int = 100, offset: int = 0) -> PathogensResponse:
    """
    List all pathogen profiles created or updated by the Scholar Agent.
    """
    async with AsyncSessionLocal() as session:
        repo = PathogenRepository(session)
        pathogens = await repo.get_all(limit=limit, offset=offset)
        total = await repo.count()

    profiles = [
        PathogenProfile(
            species_name=p.species_name,
            common_name=p.common_name,
            category=p.category.value if p.category else "unknown",
            genome_type=p.genome_type,
            transmission_routes=p.transmission_routes,
            reservoir_hosts=p.reservoir_hosts,
            description=p.description,
            who_priority=p.who_priority,
            ncbi_taxonomy_id=p.ncbi_taxonomy_id,
        )
        for p in pathogens
    ]

    return PathogensResponse(pathogens=profiles, total=total)


@router.post(
    "/trigger/research",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Research Agent",
    description=(
        "Runs four specialized sub-agents per pathogen (8 PubMed queries total, up to 16 articles): "
        "Molecular Biology Agent (genome, structure, host-cell entry), "
        "Experiments Agent (in vitro, in vivo models), "
        "Therapeutics Agent (vaccines, antivirals, clinical trials), and "
        "Clinical Epidemiology Agent (outbreak dynamics, risk factors, public health). "
        "Each article is tagged with the sub-agent that gathered it. "
        "Safe to re-run — upserts existing records."
    ),
)
async def trigger_research(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_research")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Research job.",
        )
    logger.info("research_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="research",
        message=(
            "Research Agent (v2) queued. Four specialized sub-agents will run 8 PubMed "
            "queries per pathogen: Molecular Biology, Experiments, Therapeutics, and "
            "Clinical Epidemiology. Each article is tagged with its gathering sub-agent. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status. "
            "Results at GET /api/v1/agents/research/{pathogen_name}."
        ),
    )


# ── Research query endpoints ──────────────────────────────────────────────────

@router.get(
    "/research",
    response_model=ResearchIndexResponse,
    summary="List all researched pathogens",
    description=(
        "Returns an index of every pathogen that has been processed by the Research Agent, "
        "with article counts and timestamps. Use GET /agents/research/{pathogen_name} "
        "for the full landscape report and source links."
    ),
)
async def list_research(limit: int = 100, offset: int = 0) -> ResearchIndexResponse:
    async with AsyncSessionLocal() as session:
        path_repo = PathogenRepository(session)
        res_repo = ResearchRepository(session)
        summaries = await res_repo.get_all_summaries(limit=limit, offset=offset)
        total = len(summaries)

        # Count actual DB rows per pathogen (not the stale denormalized summary.article_count)
        counts_result = await session.execute(
            select(ResearchArticle.pathogen_id, func.count(ResearchArticle.id).label("cnt"))
            .group_by(ResearchArticle.pathogen_id)
        )
        counts_map: dict = {row.pathogen_id: row.cnt for row in counts_result}

        items = []
        for s in summaries:
            pathogen = await path_repo.get_by_id(s.pathogen_id)
            items.append(ResearchIndexItem(
                pathogen_name=pathogen.species_name if pathogen else str(s.pathogen_id),
                article_count=counts_map.get(s.pathogen_id, 0),
                last_researched_at=s.last_researched_at.isoformat() if s.last_researched_at else None,
                has_overall_summary=bool(s.overall_summary),
            ))

    return ResearchIndexResponse(pathogens=items, total=total)


@router.get(
    "/research/{pathogen_name:path}",
    response_model=PathogenResearchOut,
    summary="Pathogen research landscape",
    description=(
        "Returns the full research landscape for a specific pathogen: "
        "four-section summary (infection mechanism, wet-lab, clinical trials, vaccines/therapies), "
        "an overall narrative, and all source articles with PubMed links and individual summaries."
    ),
)
async def get_research(pathogen_name: str) -> PathogenResearchOut:
    async with AsyncSessionLocal() as session:
        path_repo = PathogenRepository(session)
        res_repo = ResearchRepository(session)

        pathogen = await path_repo.get_by_species_name(pathogen_name)
        if not pathogen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pathogen '{pathogen_name}' not found. "
                       "Check GET /agents/pathogens for known pathogens.",
            )

        summary = await res_repo.get_summary_for_pathogen(pathogen.id)
        articles = await res_repo.get_articles_for_pathogen(pathogen.id)

    article_out = [
        ResearchArticleOut(
            pmid=a.pmid,
            title=a.title,
            authors=a.authors,
            published_date=a.published_date,
            article_category=a.article_category.value if a.article_category else "unknown",
            gathered_by=_CATEGORY_TO_AGENT.get(
                a.article_category.value if a.article_category else "", "Unknown Agent"
            ),
            source_url=a.source_url,
            article_summary=a.article_summary,
        )
        for a in articles
    ]

    return PathogenResearchOut(
        pathogen_name=pathogen_name,
        overall_summary=summary.overall_summary if summary else None,
        molecular_biology_summary=summary.molecular_biology_summary if summary else None,
        experiments_summary=summary.experiments_summary if summary else None,
        therapeutics_summary=summary.therapeutics_summary if summary else None,
        clinical_epi_summary=summary.clinical_epi_summary if summary else None,
        infection_mechanism_summary=summary.infection_mechanism_summary if summary else None,
        wet_lab_summary=summary.wet_lab_summary if summary else None,
        clinical_trial_summary=summary.clinical_trial_summary if summary else None,
        vaccine_therapy_summary=summary.vaccine_therapy_summary if summary else None,
        article_count=len(article_out),
        last_researched_at=summary.last_researched_at.isoformat() if summary and summary.last_researched_at else None,
        articles=article_out,
    )


# ── Hypothesis schemas ────────────────────────────────────────────────────────

class PathogenHypothesisOut(BaseModel):
    pathogen_name: str
    research_gap: str | None
    proposed_strategy: str | None
    wetlab_experiments: str | None
    clinical_approaches: str | None
    rationale: str | None
    overall_recommendation: str | None
    last_synthesized_at: str | None


class HypothesisIndexItem(BaseModel):
    pathogen_name: str
    last_synthesized_at: str | None
    has_recommendation: bool


class HypothesisIndexResponse(BaseModel):
    pathogens: list[HypothesisIndexItem]
    total: int


class VerifierResult(BaseModel):
    agent: str
    mode: str
    pathogens_checked: int
    fields_corrected: int
    errors: list[str]


# ── Hypothesis trigger ────────────────────────────────────────────────────────

@router.post(
    "/trigger/hypothesis",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Hypothesis Agent",
    description=(
        "For each pathogen in the database, reads across all evidence sources "
        "(biological profile, research landscape, outbreak signal) and synthesizes: "
        "a critical research gap, a specific therapeutic/vaccine strategy, "
        "numbered wet-lab experiments, feasible clinical approaches, biological rationale, "
        "and an overall strategic recommendation. Priority score computed from profile data. "
        "Safe to re-run — upserts existing records."
    ),
)
async def trigger_hypothesis(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_hypothesis")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Hypothesis job.",
        )
    logger.info("hypothesis_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="hypothesis",
        message=(
            "Hypothesis Agent queued. For each pathogen it will identify research gaps, "
            "propose a specific strategy, specify wet-lab experiments, and outline clinical "
            "approaches — all grounded in the available evidence. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status. "
            "Results at GET /api/v1/agents/hypothesis/{pathogen_name}."
        ),
    )


# ── Verifier trigger endpoints ────────────────────────────────────────────────

@router.post(
    "/trigger/verify-research",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Verifier (research mode)",
    description=(
        "Quality-gate over all PathogenResearchSummary records. "
        "Runs a deterministic coherence check (catches error strings, fragments, "
        "and garbage text) then an LLM biological-relevance pass. "
        "Corrections are written back to the database immediately. "
        "Normally triggered automatically after the Research Agent completes."
    ),
)
async def trigger_verify_research(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_verifier_research")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Verifier (research) job.",
        )
    logger.info("verifier_research_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="verifier",
        message=(
            "Verifier Agent (research mode) queued. It will check every research "
            "summary field for coherence and biological relevance, then write "
            "corrections back to the database. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/verify-hypothesis",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run Verifier (hypothesis mode)",
    description=(
        "Quality-gate over all PathogenHypothesis records. "
        "Runs a deterministic coherence check then an LLM biological-relevance pass "
        "across all hypothesis fields (research gap, strategy, wet-lab, clinical, "
        "recommendation). Corrections are written back immediately. "
        "Normally triggered automatically after the Hypothesis Agent completes."
    ),
)
async def trigger_verify_hypothesis(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_verifier_hypothesis")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue Verifier (hypothesis) job.",
        )
    logger.info("verifier_hypothesis_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="verifier",
        message=(
            "Verifier Agent (hypothesis mode) queued. It will check every hypothesis "
            "field for coherence and biological relevance, then write corrections "
            "back to the database. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/send-newsletter",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Send daily digest now",
    description="Immediately enqueue the newsletter digest task for all active subscribers.",
)
async def trigger_send_newsletter(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_send_newsletter")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue newsletter job.",
        )
    logger.info("newsletter_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="newsletter",
        message=(
            "Newsletter digest queued. Emails will be sent to all active subscribers. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


@router.post(
    "/trigger/run-pipeline",
    response_model=AgentTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run full pipeline",
    description=(
        "Enqueue a complete end-to-end pipeline run: collection → sentinel → scholar → "
        "dedup → research → hypothesis → graph sync → newsletter. "
        "Does NOT clear existing data. Watch worker logs for step-by-step progress."
    ),
)
async def trigger_run_pipeline(request: Request) -> AgentTriggerResponse:
    arq_redis = _get_arq_redis(request)
    job = await arq_redis.enqueue_job("task_run_full_pipeline")
    if not job:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to enqueue pipeline job.",
        )
    await arq_redis.set("pathogeniq:pipeline:latest_job_id", job.job_id, ex=86400)
    logger.info("full_pipeline_triggered", job_id=job.job_id)
    return AgentTriggerResponse(
        job_id=job.job_id,
        agent="full_pipeline",
        message=(
            "Full pipeline queued. "
            f"Poll GET /api/v1/ingestion/jobs/{job.job_id} for status."
        ),
    )


class PipelineRunningResponse(BaseModel):
    running: bool
    job_id: str | None = None


_PIPELINE_RUNNING_KEY = "pathogeniq:pipeline:running"
_PIPELINE_JOB_KEY = "pathogeniq:pipeline:latest_job_id"


@router.post(
    "/pipeline/start",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark pipeline as running (called by run_pipeline.sh at start)",
)
async def pipeline_start(request: Request) -> None:
    arq_redis = getattr(request.app.state, "arq_redis", None)
    if arq_redis is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis unavailable.")
    await arq_redis.set(_PIPELINE_RUNNING_KEY, "1", ex=28800)  # 8 h safety TTL
    logger.info("pipeline_started_flag_set")


@router.post(
    "/pipeline/stop",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark pipeline as stopped (called by run_pipeline.sh on finish or error)",
)
async def pipeline_stop(request: Request) -> None:
    arq_redis = getattr(request.app.state, "arq_redis", None)
    if arq_redis is None:
        return
    await arq_redis.delete(_PIPELINE_RUNNING_KEY)
    logger.info("pipeline_stopped_flag_cleared")


@router.get(
    "/pipeline-running",
    response_model=PipelineRunningResponse,
    summary="Check if the pipeline is currently running",
)
async def get_pipeline_running(request: Request) -> PipelineRunningResponse:
    arq_redis = getattr(request.app.state, "arq_redis", None)
    if arq_redis is None:
        return PipelineRunningResponse(running=False)

    # Check script-driven flag first (set by run_pipeline.sh via /pipeline/start)
    flag = await arq_redis.get(_PIPELINE_RUNNING_KEY)
    if flag:
        return PipelineRunningResponse(running=True)

    # Fall back: check ARQ job status for pipelines triggered via API
    raw = await arq_redis.get(_PIPELINE_JOB_KEY)
    if not raw:
        return PipelineRunningResponse(running=False)
    job_id = raw.decode() if isinstance(raw, bytes) else raw
    job_status = await Job(job_id, arq_redis).status()
    running = job_status in (JobStatus.queued, JobStatus.in_progress)
    return PipelineRunningResponse(running=running, job_id=job_id if running else None)


# ── Hypothesis query endpoints ────────────────────────────────────────────────

@router.get(
    "/hypothesis",
    response_model=HypothesisIndexResponse,
    summary="List all pathogen hypotheses",
    description=(
        "Returns all pathogens that have been processed by the Hypothesis Agent, "
        "ordered by priority score (highest first). Use GET /agents/hypothesis/{pathogen_name} "
        "for the full research gap analysis and proposed strategy."
    ),
)
async def list_hypotheses(limit: int = 100, offset: int = 0) -> HypothesisIndexResponse:
    async with AsyncSessionLocal() as session:
        path_repo = PathogenRepository(session)
        hyp_repo = HypothesisRepository(session)
        hypotheses = await hyp_repo.get_all_hypotheses(limit=limit, offset=offset)
        total = len(hypotheses)

        items = []
        for h in hypotheses:
            pathogen = await path_repo.get_by_id(h.pathogen_id)
            items.append(HypothesisIndexItem(
                pathogen_name=pathogen.species_name if pathogen else str(h.pathogen_id),
                last_synthesized_at=h.last_synthesized_at.isoformat() if h.last_synthesized_at else None,
                has_recommendation=bool(h.overall_recommendation),
            ))

    return HypothesisIndexResponse(pathogens=items, total=total)


@router.get(
    "/hypothesis/{pathogen_name:path}",
    response_model=PathogenHypothesisOut,
    summary="Pathogen research hypothesis",
    description=(
        "Returns the full Hypothesis Agent output for a specific pathogen: "
        "identified research gap, proposed strategy, wet-lab experiments, "
        "clinical approaches, biological rationale, and overall recommendation."
    ),
)
async def get_hypothesis(pathogen_name: str) -> PathogenHypothesisOut:
    async with AsyncSessionLocal() as session:
        path_repo = PathogenRepository(session)
        hyp_repo = HypothesisRepository(session)

        pathogen = await path_repo.get_by_species_name(pathogen_name)
        if not pathogen:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pathogen '{pathogen_name}' not found. "
                       "Check GET /agents/pathogens for known pathogens.",
            )

        hyp = await hyp_repo.get_hypothesis_for_pathogen(pathogen.id)
        if not hyp:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No hypothesis found for '{pathogen_name}'. "
                       "Run POST /agents/trigger/hypothesis first.",
            )

    return PathogenHypothesisOut(
        pathogen_name=pathogen_name,
        research_gap=hyp.research_gap,
        proposed_strategy=hyp.proposed_strategy,
        wetlab_experiments=hyp.wetlab_experiments,
        clinical_approaches=hyp.clinical_approaches,
        rationale=hyp.rationale,
        overall_recommendation=hyp.overall_recommendation,
        last_synthesized_at=hyp.last_synthesized_at.isoformat() if hyp.last_synthesized_at else None,
    )


# ── Source documents ──────────────────────────────────────────────────────────

class DocumentSourceOut(BaseModel):
    document_id: str
    title: str | None
    url: str | None
    source: str
    published_date: str | None
    mention_count: int


class PathogenSourcesOut(BaseModel):
    pathogen_name: str
    total_documents: int
    documents: list[DocumentSourceOut]


@router.get(
    "/sources/{pathogen_name:path}",
    response_model=PathogenSourcesOut,
    summary="Source documents for a pathogen",
    description=(
        "Returns every document in which the Sentinel Agent detected this pathogen, "
        "with titles, URLs, source labels, and per-document mention counts."
    ),
)
async def get_pathogen_sources(pathogen_name: str) -> PathogenSourcesOut:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PathogenMention, Document)
            .join(Document, PathogenMention.document_id == Document.id)
            .where(PathogenMention.pathogen_name == pathogen_name)
            .order_by(PathogenMention.mention_count.desc())
        )
        rows = result.all()

    docs = [
        DocumentSourceOut(
            document_id=str(mention.document_id),
            title=doc.title,
            url=doc.url,
            source=doc.source.value,
            published_date=doc.published_date,
            mention_count=mention.mention_count,
        )
        for mention, doc in rows
    ]

    return PathogenSourcesOut(
        pathogen_name=pathogen_name,
        total_documents=len(docs),
        documents=docs,
    )


# ── Knowledge graph ───────────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: str
    label: str
    type: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


@router.get(
    "/graph",
    response_model=GraphResponse,
    summary="Knowledge graph nodes and edges",
    description=(
        "Returns all nodes (Pathogen, Category, ReservoirHost, TransmissionRoute) "
        "and edges (IN_CATEGORY, HOSTED_BY, SPREADS_VIA) from the knowledge graph. "
        "Queries Neo4j when available; falls back to constructing the graph from PostgreSQL."
    ),
)
async def get_graph() -> GraphResponse:
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    seen: set[str] = set()

    def add_node(nid: str, label: str, ntype: str) -> None:
        if nid not in seen:
            nodes.append(GraphNode(id=nid, label=label, type=ntype))
            seen.add(nid)

    # ── Try Neo4j ─────────────────────────────────────────────────────────────
    try:
        driver = get_neo4j_driver()
        async with driver.session() as neo:
            result = await neo.run(
                """
                MATCH (p:Pathogen)
                OPTIONAL MATCH (p)-[:IN_CATEGORY]->(c:Category)
                OPTIONAL MATCH (p)-[:HOSTED_BY]->(h:ReservoirHost)
                OPTIONAL MATCH (p)-[:SPREADS_VIA]->(t:TransmissionRoute)
                RETURN p.species_name AS pathogen,
                       collect(DISTINCT c.name) AS categories,
                       collect(DISTINCT h.name) AS hosts,
                       collect(DISTINCT t.name) AS routes
                """
            )
            records = await result.data()
        await driver.close()

        for r in records:
            p_id = f"pathogen:{r['pathogen']}"
            add_node(p_id, r["pathogen"], "Pathogen")
            for cat in r["categories"]:
                if cat:
                    c_id = f"category:{cat}"
                    add_node(c_id, cat.capitalize(), "Category")
                    edges.append(GraphEdge(source=p_id, target=c_id, type="IN_CATEGORY"))
            for host in r["hosts"]:
                if host:
                    h_id = f"host:{host}"
                    add_node(h_id, host, "ReservoirHost")
                    edges.append(GraphEdge(source=p_id, target=h_id, type="HOSTED_BY"))
            for route in r["routes"]:
                if route:
                    t_id = f"route:{route}"
                    add_node(t_id, route, "TransmissionRoute")
                    edges.append(GraphEdge(source=p_id, target=t_id, type="SPREADS_VIA"))

        if nodes:
            return GraphResponse(nodes=nodes, edges=edges)
    except Exception:
        pass  # fall through to PostgreSQL fallback

    # ── Fallback: construct from PostgreSQL ───────────────────────────────────
    nodes, edges, seen = [], [], set()
    _VAGUE = frozenset({"animals", "unknown", "various"})

    async with AsyncSessionLocal() as session:
        repo = PathogenRepository(session)
        pathogens = await repo.get_all(limit=500)

    for p in pathogens:
        if not p.category or p.category.value == "unknown":
            continue
        p_id = f"pathogen:{p.species_name}"
        add_node(p_id, p.species_name, "Pathogen")
        c_id = f"category:{p.category.value}"
        add_node(c_id, p.category.value.capitalize(), "Category")
        edges.append(GraphEdge(source=p_id, target=c_id, type="IN_CATEGORY"))
        for route in p.transmission_routes or []:
            t_id = f"route:{route}"
            add_node(t_id, str(route), "TransmissionRoute")
            edges.append(GraphEdge(source=p_id, target=t_id, type="SPREADS_VIA"))
        for host in p.reservoir_hosts or []:
            if str(host).lower() not in _VAGUE:
                h_id = f"host:{host}"
                add_node(h_id, str(host), "ReservoirHost")
                edges.append(GraphEdge(source=p_id, target=h_id, type="HOSTED_BY"))

    return GraphResponse(nodes=nodes, edges=edges)


# ── Pipeline status ───────────────────────────────────────────────────────────

class PipelineStatus(BaseModel):
    last_research_run_at: str | None
    last_hypothesis_run_at: str | None
    last_ingested_at: str | None
    total_pathogens: int
    total_documents: int
    total_research_articles: int


@router.get(
    "/pipeline-status",
    response_model=PipelineStatus,
    summary="Pipeline run timestamps and dataset counts",
    description=(
        "Returns the most recent timestamps from each agent pipeline stage "
        "and total record counts for pathogens, documents, and research articles."
    ),
)
async def get_pipeline_status() -> PipelineStatus:
    async with AsyncSessionLocal() as session:
        last_research = (await session.execute(
            select(func.max(PathogenResearchSummary.last_researched_at))
        )).scalar()

        last_hypothesis = (await session.execute(
            select(func.max(PathogenHypothesis.last_synthesized_at))
        )).scalar()

        last_ingested = (await session.execute(
            select(func.max(Document.created_at))
        )).scalar()

        total_pathogens = (await session.execute(
            select(func.count(Pathogen.id))
        )).scalar() or 0

        total_documents = (await session.execute(
            select(func.count(Document.id))
        )).scalar() or 0

        total_articles = (await session.execute(
            select(func.count(ResearchArticle.id))
        )).scalar() or 0

    return PipelineStatus(
        last_research_run_at=last_research.isoformat() if last_research else None,
        last_hypothesis_run_at=last_hypothesis.isoformat() if last_hypothesis else None,
        last_ingested_at=last_ingested.isoformat() if last_ingested else None,
        total_pathogens=int(total_pathogens),
        total_documents=int(total_documents),
        total_research_articles=int(total_articles),
    )


# ── Pathogen trends ───────────────────────────────────────────────────────────

class PathogenDaySeries(BaseModel):
    pathogen_name: str
    counts: list[int]


class PathogenTrendsOut(BaseModel):
    dates: list[str]          # ISO date strings, one per day in the window
    series: list[PathogenDaySeries]


@router.get(
    "/pathogen-trends",
    response_model=PathogenTrendsOut,
    summary="Daily pathogen document counts by publication date",
    description=(
        "For each day in the requested window, returns how many documents "
        "mentioning each pathogen were published on that day. "
        "Uses published_date (not ingestion date) so batch pipeline runs don't "
        "collapse all articles onto a single spike. "
        "Use ?days= to control the window (7–90, default 30)."
    ),
)
async def get_pathogen_trends(
    days: int = Query(default=30, ge=7, le=90),
) -> PathogenTrendsOut:
    from email.utils import parsedate_to_datetime

    today = date.today()
    cutoff = today - timedelta(days=days - 1)

    # Fetch raw rows — no SQL date filter because published_date is a free-form
    # string that can't be compared in SQL. Python handles the window filter below.
    # Use a loose created_at guard (cutoff - 180 days) to avoid full-table scans
    # on large datasets while still catching documents ingested before the window
    # that were published within it.
    loose_cutoff = cutoff - timedelta(days=180)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(
                Document.published_date,
                Document.created_at,
                PathogenMention.pathogen_name,
            )
            .join(Document, PathogenMention.document_id == Document.id)
            .where(Document.created_at >= loose_cutoff)
        )
        rows = result.all()

    # Accumulate counts per (pathogen_name, day) using published_date where
    # available (RFC 2822 strings); fall back to created_at date.
    data: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        pub_day: date | None = None
        if row.published_date:
            try:
                pub_day = parsedate_to_datetime(row.published_date).date()
            except Exception:
                pass
        if pub_day is None and row.created_at:
            pub_day = row.created_at.date()
        if pub_day is None or not (cutoff <= pub_day <= today):
            continue
        data[str(row.pathogen_name)][pub_day.isoformat()] += 1

    # Build a dense date range (every day from cutoff → today)
    day_range = [
        (cutoff + timedelta(days=i)).isoformat()
        for i in range((today - cutoff).days + 1)
    ]

    # Emit only pathogens that have at least one non-zero day in the window
    series = [
        PathogenDaySeries(
            pathogen_name=name,
            counts=[day_counts.get(d, 0) for d in day_range],
        )
        for name, day_counts in sorted(data.items())
        if any(day_counts.values())
    ]

    return PathogenTrendsOut(dates=day_range, series=series)
