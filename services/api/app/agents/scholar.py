"""
ScholarAgent — Phase 3 biological profile synthesis agent.

Role: For each pathogen discovered by the Sentinel Agent, query PubMed for
recent peer-reviewed literature and synthesize a structured biological profile:
transmission routes, reservoir hosts, fatality rates, genome type, WHO priority
status, and pandemic potential score.

LangGraph pipeline:
  START → load_targets → [no targets? → END] → research_pathogens → save_profiles → END

RELATIONSHIP WITH SENTINEL:
  Scholar is the second agent in the Phase 3 pipeline. It reads directly from
  the pathogen_mentions table (Sentinel's output) to know which pathogens to
  research. Sentinel runs first; Scholar runs after.

  In the ARQ task chain: task_run_sentinel automatically enqueues task_run_scholar
  when it completes and found at least one pathogen.

WHY PUBMED?
  PubMed indexes 37+ million biomedical citations. For any known pathogen, there
  are peer-reviewed papers on transmission, pathogenesis, epidemiology, and
  countermeasures. Scholar uses the existing PubMedCollector (collectors/pubmed.py)
  with a pathogen-specific query rather than the static cron query used in Phase 3+.

WHY LLM SYNTHESIS INSTEAD OF STRUCTURED EXTRACTION?
  PubMed abstracts are heterogeneous: structured (BACKGROUND/METHODS/RESULTS),
  narrative, meta-analytic, letter format. A regex extractor would miss most
  content. Claude synthesizes across multiple abstracts simultaneously, resolves
  conflicting CFR estimates across studies, and produces a coherent profile in
  one call rather than requiring hand-crafted field extractors per abstract type.

PROFILE PERSISTENCE:
  Profiles are upserted into the pathogens table. Existing pathogen records
  are updated with fresh synthesis from the latest literature. New pathogens
  are inserted. Scholar never deletes pathogen records.
"""

import asyncio
import json
import re
from typing import TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.collectors.pubmed import PubMedCollector
from app.collectors.schemas import CollectedDocument
from app.db.models.pathogen import Pathogen, PathogenCategory
from app.db.session import AsyncSessionLocal
from app.repositories.pathogen import PathogenRepository
from app.repositories.pathogen_mention import PathogenMentionRepository

from .filters import is_non_pathogen
from .llm import get_llm
from .prompts import SCHOLAR_SYSTEM
from .validators import correct_pathogen_profile

logger = structlog.get_logger(__name__)

MIN_MENTION_THRESHOLD = 1
MAX_ABSTRACTS = 8          # 8 abstracts gives richer evidence for accurate field synthesis
MAX_PATHOGENS_PER_RUN = 50  # process all pathogens per run on Groq
_ABSTRACT_CHARS = 600      # chars per abstract in the synthesis prompt

# English function words that appear in descriptive phrases but not scientific names
_NL_INDICATORS = frozenset({
    "for", "which", "that", "we", "no", "have", "and", "with", "our", "it", "not", "without",
})


def _is_descriptive_phrase(name: str) -> bool:
    """Return True for LLM outputs that are sentences rather than pathogen names.

    e.g. 'Ebola strain for which we have no vaccine and no treatment' → True
         'Klebsiella pneumoniae' → False
    """
    words = name.lower().split()
    return len(words) >= 7 or sum(1 for w in words if w in _NL_INDICATORS) >= 2


# ── LangGraph state ───────────────────────────────────────────────────────────

class ScholarState(TypedDict):
    """Accumulated state passed between LangGraph nodes."""
    target_pathogens: list[str]   # canonical names to research (from Sentinel)
    profiles: list[dict]          # synthesized profiles: one per pathogen
    saved_count: int
    error_count: int
    errors: list[str]
    offset: int                   # skip this many eligible mentions before taking MAX_PATHOGENS_PER_RUN


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def load_targets(state: ScholarState) -> ScholarState:
    """
    Load pathogen names that exceed the minimum mention threshold.

    Uses offset pagination so consecutive pipeline passes profile different
    pathogens (sorted by mention frequency) rather than re-profiling the same
    top-N every time.
    """
    async with AsyncSessionLocal() as session:
        repo = PathogenMentionRepository(session)
        counts = await repo.get_aggregate_counts()

    offset = state.get("offset", 0)
    eligible = [
        row["pathogen_name"]
        for row in counts
        if row["total_mentions"] >= MIN_MENTION_THRESHOLD
        and not _is_descriptive_phrase(row["pathogen_name"])
        and not is_non_pathogen(row["pathogen_name"])
    ]
    targets = eligible[offset : offset + MAX_PATHOGENS_PER_RUN]

    logger.info("scholar_loaded_targets", count=len(targets), offset=offset, targets=targets[:10])
    return {**state, "target_pathogens": targets}


async def research_pathogens(state: ScholarState) -> ScholarState:
    """
    For each target pathogen:
      1. Query PubMed for recent literature using the pathogen name.
      2. Synthesize a biological profile via LLM.
      3. Immediately persist the profile to the DB.

    Saving after each synthesis (rather than batching at the end) makes this
    node timeout-safe: partial results survive even if the job is killed mid-run.
    """
    llm = get_llm(max_tokens=700)
    pubmed = PubMedCollector()
    profiles: list[dict] = []
    errors = list(state["errors"])
    error_count = state["error_count"]
    saved_count = state["saved_count"]

    for i, pathogen_name in enumerate(state["target_pathogens"]):
        if i > 0:
            await asyncio.sleep(20)  # 20s between pathogens to avoid Groq TPM rate limit
        try:
            papers = await _fetch_pubmed_papers(pubmed, pathogen_name)
            # Retry up to 3 times on Groq 429 rate-limit errors
            profile = None
            for attempt in range(3):
                try:
                    profile = await _synthesize_profile(llm, pathogen_name, papers)
                    break
                except Exception as exc:
                    if "429" in str(exc) and attempt < 2:
                        wait = 60 * (attempt + 1)
                        logger.warning("groq_rate_limit_retry", pathogen=pathogen_name, attempt=attempt + 1, wait_s=wait)
                        await asyncio.sleep(wait)
                    else:
                        raise
            profile["pathogen_name"] = pathogen_name
            profiles.append(profile)
            logger.info(
                "scholar_profiled",
                pathogen=pathogen_name,
                papers_used=len(papers),
            )
            # Persist immediately — don't wait for save_profiles node
            async with AsyncSessionLocal() as session:
                async with session.begin():
                    await _upsert_pathogen(PathogenRepository(session), profile)
            saved_count += 1
            logger.info("scholar_profile_saved", pathogen=pathogen_name)
        except Exception as exc:
            msg = f"{pathogen_name}: {type(exc).__name__}: {exc}"
            logger.warning("scholar_research_error", pathogen=pathogen_name, error=str(exc))
            errors.append(msg)
            error_count += 1

    return {
        **state,
        "profiles": profiles,
        "saved_count": saved_count,
        "errors": errors,
        "error_count": error_count,
    }


async def save_profiles(state: ScholarState) -> ScholarState:
    """
    Profiles were saved incrementally in research_pathogens — just log the total.
    """
    logger.info("scholar_profiles_saved", count=state["saved_count"])
    return state


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(ScholarState)

    graph.add_node("load_targets", load_targets)
    graph.add_node("research_pathogens", research_pathogens)
    graph.add_node("save_profiles", save_profiles)

    graph.add_edge(START, "load_targets")
    graph.add_conditional_edges(
        "load_targets",
        lambda s: END if not s["target_pathogens"] else "research_pathogens",
    )
    graph.add_edge("research_pathogens", "save_profiles")
    graph.add_edge("save_profiles", END)

    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Private helpers ───────────────────────────────────────────────────────────

async def _fetch_pubmed_papers(
    pubmed: PubMedCollector, pathogen_name: str
) -> list[dict]:
    """
    Query PubMed for recent literature on a specific pathogen.
    Builds a targeted ESearch query using title/abstract and MeSH fields.
    Returns simplified paper dicts (title, abstract, date) for the LLM prompt.
    """
    query = (
        f'("{pathogen_name}"[tiab] OR "{pathogen_name}"[mh]) '
        'AND ("2023"[dp] OR "2024"[dp] OR "2025"[dp] OR "2026"[dp])'
    )
    try:
        docs: list[CollectedDocument] = await pubmed.collect(
            query=query, max_results=MAX_ABSTRACTS
        )
    except Exception as exc:
        logger.warning("scholar_pubmed_fetch_failed", pathogen=pathogen_name, error=str(exc))
        docs = []

    return [
        {
            "title": d.title or "",
            "abstract": d.abstract or "",
            "published_date": d.published_date or "",
        }
        for d in docs
        if d.abstract
    ][:MAX_ABSTRACTS]


async def _synthesize_profile(
    llm,
    pathogen_name: str,
    papers: list[dict],
) -> dict:
    """
    Ask Claude to synthesize a biological profile from PubMed abstracts.
    Returns a parsed profile dict ready for DB insertion.
    """
    if papers:
        paper_blocks = [
            f"[{i}] {p['title']}\n{p['abstract'][:_ABSTRACT_CHARS]}"
            for i, p in enumerate(papers, 1)
        ]
        literature_section = "\n\n".join(paper_blocks)
        count_phrase = f"{len(papers)} PubMed abstract(s)"
    else:
        literature_section = (
            "No PubMed abstracts available. "
            "For well-known pathogens, synthesize from established scientific consensus."
        )
        count_phrase = "no PubMed abstracts (use general knowledge)"

    user_content = (
        f"Synthesize a biological profile for: **{pathogen_name}**\n\n"
        f"Based on {count_phrase}:\n\n"
        f"{literature_section}"
    )

    response = await llm.ainvoke([
        SystemMessage(content=SCHOLAR_SYSTEM),
        HumanMessage(content=user_content),
    ])
    return _parse_json_object(response.content)


def _parse_json_object(raw: str) -> dict:
    """Strip markdown fences then parse as JSON, with control-char fallback."""
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    text = text.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # LLM emitted a literal control character inside a string value (e.g. a
        # bare newline or carriage return). Replace the full 0x00–0x1F range
        # with spaces — structural JSON whitespace is not required between tokens
        # so the document still parses correctly.
        sanitized = re.sub(r"[\x00-\x1f\x7f]", " ", text)
        data = json.loads(sanitized)
    return data if isinstance(data, dict) else {}


async def _upsert_pathogen(repo: PathogenRepository, profile: dict) -> None:
    """
    Insert or update a pathogen record from the Scholar's synthesized profile.

    Resolves the category string to the PathogenCategory enum. Unknown or
    invalid category strings fall back to UNKNOWN rather than erroring.
    """
    pathogen_name: str = profile["pathogen_name"]

    # Apply programmatic corrections before persisting — overrides LLM hallucinations
    profile = correct_pathogen_profile(pathogen_name, profile)

    category_str = (profile.get("category") or "unknown").lower()
    try:
        category = PathogenCategory(category_str)
    except ValueError:
        category = PathogenCategory.UNKNOWN

    fields = {
        "category": category,
        "common_name": profile.get("common_name") or None,
        "genome_type": profile.get("genome_type") or None,
        "transmission_routes": profile.get("transmission_routes") or None,
        "reservoir_hosts": profile.get("reservoir_hosts") or None,
        "description": profile.get("description") or None,
        "who_priority": bool(profile.get("who_priority", False)),
    }
    ncbi_id = profile.get("ncbi_taxonomy_id") or None

    existing = await repo.get_by_species_name(pathogen_name)

    if existing:
        # Update all synthesized fields; never overwrite a manually-set NCBI ID
        update_fields = {k: v for k, v in fields.items() if v is not None}
        if ncbi_id and not existing.ncbi_taxonomy_id:
            update_fields["ncbi_taxonomy_id"] = ncbi_id
        await repo.update(existing, **update_fields)
    else:
        if ncbi_id:
            fields["ncbi_taxonomy_id"] = ncbi_id
        await repo.create(species_name=pathogen_name, **fields)


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_scholar(offset: int = 0) -> dict:
    """
    Run the Scholar agent end-to-end.

    offset: skip this many eligible mentions (sorted by frequency) before
            profiling. The pipeline runner advances this across passes so
            every discovered pathogen gets profiled, not just the top-N.

    Returns a summary dict:
      - pathogens_researched: how many pathogens were sent for PubMed research
      - profiles_saved: how many pathogen records were inserted or updated
      - errors: list of per-pathogen error messages
    """
    initial: ScholarState = {
        "target_pathogens": [],
        "profiles": [],
        "saved_count": 0,
        "error_count": 0,
        "errors": [],
        "offset": offset,
    }
    final = await _get_graph().ainvoke(initial)

    return {
        "agent": "scholar",
        "pathogens_researched": len(final["profiles"]),
        "profiles_saved": final["saved_count"],
        "errors": final["errors"],
    }
