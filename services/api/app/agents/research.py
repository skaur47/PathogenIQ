"""
ResearchAgent — Phase 4 v2 multi-agent deep literature synthesis (qwen-optimised).

Four specialized sub-agents each own a distinct research domain and run
non-overlapping PubMed queries. Optimised for small LLMs (qwen2.5:1.5b):
  - 2 targeted PubMed queries per sub-agent (8 queries total, down from 13)
  - Up to 2 articles per query (up to 16 articles per pathogen, down from 39)
  - 200-char abstract truncation (down from 400) keeps prompts small
  - ONE combined synthesis call writes 1 sentence per domain (~150 tokens out)

Sub-agents and their domains (no information overlap):
  MolecularBiologyAgent   — genome organisation, structural proteins, host-cell entry
  ExperimentsAgent        — in vitro cell-culture models, in vivo animal models
  TherapeuticsAgent       — approved/investigational vaccines and antivirals
  ClinicalEpiAgent        — outbreak dynamics, risk factors, public health

Attribution: every ResearchArticle row carries an article_category that maps 1:1
to the sub-agent that collected it. The API exposes this as a `gathered_by` field.

LangGraph pipeline:
  START → load_pathogens → [none? → END] → research_each → END

CONCURRENCY DESIGN:
  - All 4 sub-agents fetch PubMed in parallel per pathogen (asyncio.gather)
  - pubmed_sem(1) + 0.35s hold keeps NCBI under 3 req/s unauthenticated limit
  - llm_sem(8) allows generous synthesis parallelism without overwhelming the API
  - Up to _PATHOGEN_CONCURRENCY pathogens processed simultaneously
"""

import asyncio
import re
from dataclasses import dataclass
from typing import TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import select

from app.collectors.pubmed import PubMedCollector
from app.collectors.schemas import CollectedDocument
from app.db.models.pathogen import Pathogen
from app.db.models.research import ArticleCategory, PathogenResearchSummary
from app.db.session import AsyncSessionLocal

from .filters import classify_article_category, is_non_pathogen
from .llm import get_llm, llm_invoke_with_retry

logger = structlog.get_logger(__name__)

ARTICLES_PER_QUERY = 2     # 2×8 queries = up to 16 articles per pathogen (was 3×13=39)
_ABSTRACT_CHARS = 200      # truncate abstracts to keep LLM prompt small (was 400)
_MAX_PATHOGENS_PER_RUN = 50 # process all pathogens per run on Groq

_YEARS = '"2022"[dp] OR "2023"[dp] OR "2024"[dp] OR "2025"[dp] OR "2026"[dp]'

# Concurrency limits
_PUBMED_CONCURRENCY = 1   # single NCBI slot; 0.35s hold keeps us under 3 req/s
_LLM_CONCURRENCY = 8      # max simultaneous LLM synthesis calls
_PATHOGEN_CONCURRENCY = 2 # parallel pathogens; llama-3.1-8b-instant: 30K TPM, 2×~4.5K ≈ 9K/min (safe)

# Module-level semaphore — shared across ALL concurrent research job invocations.
# If two ARQ jobs happen to run simultaneously they still share one NCBI slot.
_pubmed_sem: asyncio.Semaphore | None = None
_llm_sem: asyncio.Semaphore | None = None


def _get_sems() -> tuple[asyncio.Semaphore, asyncio.Semaphore]:
    global _pubmed_sem, _llm_sem
    if _pubmed_sem is None:
        _pubmed_sem = asyncio.Semaphore(_PUBMED_CONCURRENCY)
    if _llm_sem is None:
        _llm_sem = asyncio.Semaphore(_LLM_CONCURRENCY)
    return _pubmed_sem, _llm_sem


# ── Sub-agent definitions ─────────────────────────────────────────────────────

@dataclass
class SubAgent:
    """
    Configuration for one specialized research sub-agent.

    queries:       PubMed query templates — {name} and {years} are substituted.
    category:      ArticleCategory value used to tag collected articles.
    summary_field: Column name on PathogenResearchSummary to write the synthesis.
    label:         Human-readable display name used in overall_summary and logs.
    system_prompt: LLM system prompt for the synthesis call.
    """
    category: ArticleCategory
    summary_field: str
    label: str
    queries: list[str]
    system_prompt: str


_SUB_AGENTS: list[SubAgent] = [

    SubAgent(
        category=ArticleCategory.MOLECULAR_BIOLOGY,
        summary_field="molecular_biology_summary",
        label="MOLECULAR BIOLOGY",
        queries=[
            # Genome organisation and structural proteins
            (
                '"{name}"[tiab] AND '
                '(genome[tiab] OR "protein structure"[tiab] OR "spike protein"[tiab] '
                'OR "capsid"[tiab] OR proteomics[tiab]) '
                "AND ({years})"
            ),
            # Host-cell entry, replication, immune evasion
            (
                '"{name}"[tiab] AND '
                '("host cell"[tiab] OR "receptor binding"[tiab] OR replication[tiab] '
                'OR "immune evasion"[tiab] OR "virulence factor"[tiab]) '
                "AND ({years})"
            ),
        ],
        system_prompt=(
            "You are a molecular virologist. "
            "Given PubMed abstracts, write ONE sentence covering: "
            "genome type, key structural proteins, host-cell entry, and any noted immune-evasion. "
            "Only state what the abstracts say. Plain text only."
        ),
    ),

    SubAgent(
        category=ArticleCategory.EXPERIMENTS,
        summary_field="experiments_summary",
        label="LABORATORY EXPERIMENTS & ASSAYS",
        queries=[
            # In vitro models
            (
                '"{name}"[tiab] AND '
                '("in vitro"[tiab] OR "cell culture"[tiab] OR "cell line"[tiab] '
                'OR "Vero"[tiab] OR "organoid"[tiab]) '
                "AND ({years})"
            ),
            # In vivo models and assays
            (
                '"{name}"[tiab] AND '
                '("in vivo"[tiab] OR "animal model"[tiab] OR "mouse model"[tiab] '
                'OR "neutralization assay"[tiab] OR "ELISA"[tiab] OR "RNA-seq"[tiab]) '
                "AND ({years})"
            ),
        ],
        system_prompt=(
            "You are an experimental infectious disease scientist. "
            "Given PubMed abstracts, write ONE sentence covering: "
            "the main in vitro and in vivo models used and the key quantitative findings. "
            "Only state what the abstracts say. Plain text only."
        ),
    ),

    SubAgent(
        category=ArticleCategory.THERAPEUTICS,
        summary_field="therapeutics_summary",
        label="THERAPEUTICS & VACCINES",
        queries=[
            # Vaccines
            (
                '"{name}"[tiab] AND '
                '(vaccine[tiab] OR vaccination[tiab] OR "mRNA vaccine"[tiab] '
                'OR "vaccine efficacy"[tiab] OR immunization[tiab]) '
                "AND ({years})"
            ),
            # Antivirals, antibodies, clinical trials
            (
                '"{name}"[tiab] AND '
                '(antiviral[tiab] OR "monoclonal antibody"[tiab] OR "neutralizing antibody"[tiab] '
                'OR "clinical trial"[pt] OR "phase II"[tiab] OR "phase III"[tiab]) '
                "AND ({years})"
            ),
        ],
        system_prompt=(
            "You are a pharmacologist. "
            "Given PubMed abstracts, write ONE sentence covering: "
            "approved vaccines or antivirals and any leading investigational candidates. "
            "If nothing approved, say so. Only state what the abstracts say. Plain text only."
        ),
    ),

    SubAgent(
        category=ArticleCategory.CLINICAL_EPIDEMIOLOGY,
        summary_field="clinical_epi_summary",
        label="CLINICAL EPIDEMIOLOGY",
        queries=[
            # Outbreak dynamics
            (
                '"{name}"[tiab] AND '
                '(epidemiology[tiab] OR outbreak[tiab] OR "transmission dynamics"[tiab] '
                'OR incidence[tiab] OR prevalence[tiab]) '
                "AND ({years})"
            ),
            # Risk factors and public health
            (
                '"{name}"[tiab] AND '
                '("risk factor"[tiab] OR mortality[tiab] OR "case fatality rate"[tiab] '
                'OR surveillance[tiab] OR "public health"[tiab] OR "infection control"[tiab]) '
                "AND ({years})"
            ),
        ],
        system_prompt=(
            "You are a clinical epidemiologist. "
            "Given PubMed abstracts, write ONE sentence covering: "
            "geographic spread, CFR or R0 if reported, key risk factors, and control measures. "
            "Only state what the abstracts say. Plain text only."
        ),
    ),
]


# ── LangGraph state ───────────────────────────────────────────────────────────

class ResearchState(TypedDict):
    pathogens: list[Pathogen]
    offset: int
    pathogens_researched: int
    articles_saved: int
    errors: list[str]


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def load_pathogens(state: ResearchState) -> ResearchState:
    offset = state.get("offset", 0)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Pathogen)
            .order_by(Pathogen.species_name)
            .offset(offset)
            .limit(_MAX_PATHOGENS_PER_RUN)
        )
        pathogens = list(result.scalars().all())

    pathogens = [p for p in pathogens if not is_non_pathogen(p.species_name)]
    logger.info("research_loaded_pathogens", count=len(pathogens), offset=offset)
    return {**state, "pathogens": pathogens}


async def research_each(state: ResearchState) -> ResearchState:
    """
    Process all pathogens concurrently.

    Semaphores:
      pubmed_sem  — caps simultaneous NCBI HTTP calls at _PUBMED_CONCURRENCY
      llm_sem     — caps simultaneous LLM synthesis calls at _LLM_CONCURRENCY
      pathogen_sem — caps simultaneously active pathogens at _PATHOGEN_CONCURRENCY
    """
    llm = get_llm(max_tokens=150)
    pubmed = PubMedCollector()

    pubmed_sem, llm_sem = _get_sems()
    pathogen_sem = asyncio.Semaphore(_PATHOGEN_CONCURRENCY)

    async def _run_with_sem(pathogen: Pathogen):
        async with pathogen_sem:
            return await _run_one_pathogen(pubmed, llm, pathogen, pubmed_sem, llm_sem)

    results = await asyncio.gather(
        *[_run_with_sem(p) for p in state["pathogens"]],
        return_exceptions=True,
    )

    pathogens_researched = state["pathogens_researched"]
    articles_saved = state["articles_saved"]
    errors = list(state["errors"])

    for pathogen, result in zip(state["pathogens"], results):
        if isinstance(result, Exception):
            msg = f"{pathogen.species_name}: {type(result).__name__}: {result}"
            logger.warning("research_error", pathogen=pathogen.species_name, error=str(result))
            errors.append(msg)
        else:
            n_ok, n_articles = result
            pathogens_researched += n_ok
            articles_saved += n_articles

    return {
        **state,
        "pathogens_researched": pathogens_researched,
        "articles_saved": articles_saved,
        "errors": errors,
    }


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("load_pathogens", load_pathogens)
    graph.add_node("research_each", research_each)
    graph.add_edge(START, "load_pathogens")
    graph.add_conditional_edges(
        "load_pathogens",
        lambda s: END if not s["pathogens"] else "research_each",
    )
    graph.add_edge("research_each", END)
    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Pathogen runner ───────────────────────────────────────────────────────────

async def _run_one_pathogen(
    pubmed: PubMedCollector,
    llm,
    pathogen: Pathogen,
    pubmed_sem: asyncio.Semaphore,
    llm_sem: asyncio.Semaphore,
) -> tuple[int, int]:
    """
    Run all 4 sub-agents concurrently for a single pathogen, persist results.
    Returns (1, article_count) on success; raises on unrecoverable error.
    """
    name = pathogen.species_name
    log = logger.bind(pathogen=name)
    log.info("research_start")

    # Fetch all PubMed articles for all 4 sub-agents in parallel, then ONE combined LLM call.
    fetch_results = await asyncio.gather(
        *[_fetch_sub_agent_articles(pubmed, name, sa, pubmed_sem) for sa in _SUB_AGENTS],
        return_exceptions=True,
    )

    articles_per_field: dict[str, list[dict]] = {}
    for sub_agent, result in zip(_SUB_AGENTS, fetch_results):
        if isinstance(result, Exception):
            logger.warning("research_fetch_failed", pathogen=name, agent=sub_agent.label, error=str(result))
            articles_per_field[sub_agent.summary_field] = []
        else:
            articles_per_field[sub_agent.summary_field] = result

    summaries = await _synthesise_combined(llm, name, articles_per_field, llm_sem)

    sub_results: dict[str, dict] = {}
    for sub_agent in _SUB_AGENTS:
        articles = articles_per_field.get(sub_agent.summary_field, [])
        sub_results[sub_agent.summary_field] = {
            "articles": articles,
            "synthesis": summaries.get(sub_agent.summary_field, f"No summary for {sub_agent.label}."),
            "category": sub_agent.category,
            "label": sub_agent.label,
        }
        logger.info("research_sub_agent_done", pathogen=name, agent=sub_agent.label, articles=len(articles))

    total_articles = sum(
        sum(1 for a in r["articles"] if a["pmid"]) for r in sub_results.values()
    )

    async with AsyncSessionLocal() as session:
        async with session.begin():
            await _persist(session, pathogen, sub_results, total_articles)

    log.info("research_pathogen_done", total_articles=total_articles)
    return 1, total_articles


# ── Sub-agent PubMed fetcher (no synthesis) ───────────────────────────────────

async def _fetch_sub_agent_articles(
    pubmed: PubMedCollector,
    pathogen_name: str,
    sub_agent: SubAgent,
    pubmed_sem: asyncio.Semaphore,
) -> list[dict]:
    """Run all PubMed queries for one sub-agent, deduplicate by PMID, return article dicts."""
    query_strings = [q.format(name=pathogen_name, years=_YEARS) for q in sub_agent.queries]

    fetch_results = await asyncio.gather(
        *[_fetch_one_query(pubmed, q, pubmed_sem) for q in query_strings],
        return_exceptions=True,
    )

    seen_pmids: set[str] = set()
    articles: list[dict] = []

    for result in fetch_results:
        if isinstance(result, Exception):
            logger.warning("research_pubmed_failed", pathogen=pathogen_name, agent=sub_agent.label, error=str(result))
            continue
        for doc in result:
            pmid = doc.external_id or ""
            if not doc.abstract or (pmid and pmid in seen_pmids):
                continue
            if pmid:
                seen_pmids.add(pmid)
            truncated = doc.abstract[:_ABSTRACT_CHARS] + ("…" if len(doc.abstract) > _ABSTRACT_CHARS else "")
            articles.append({
                "pmid": pmid,
                "title": doc.title or "(no title)",
                "authors": ", ".join(doc.authors) if doc.authors else None,
                "published_date": doc.published_date,
                "category": classify_article_category(
                    doc.title or "", doc.abstract or "", sub_agent.category
                ),
                "source_url": doc.url,
                "abstract": doc.abstract,
                "article_summary": truncated,
            })

    return articles


async def _fetch_one_query(
    pubmed: PubMedCollector,
    query: str,
    pubmed_sem: asyncio.Semaphore,
) -> list[CollectedDocument]:
    """Single PubMed collect() call, rate-limited by the shared semaphore.

    The 0.4s sleep is held inside the lock so the next waiter can't start
    an ESearch immediately after this EFetch finishes — keeps us under NCBI's
    3 req/s unauthenticated limit even when multiple pathogens are queued.
    """
    async with pubmed_sem:
        result = await pubmed.collect(query=query, max_results=ARTICLES_PER_QUERY)
        await asyncio.sleep(0.5)
        return result


# ── LLM synthesis ─────────────────────────────────────────────────────────────

_COMBINED_SYSTEM = (
    "You are a biomedical researcher. Summarize pathogen research. "
    "Output ONLY the following four labeled sections in this exact order, each on its own line:\n"
    "[MOLECULAR BIOLOGY] one sentence summary\n"
    "[LABORATORY EXPERIMENTS & ASSAYS] one sentence summary\n"
    "[THERAPEUTICS & VACCINES] one sentence summary\n"
    "[CLINICAL EPIDEMIOLOGY] one sentence summary\n"
    "Use ONLY information from the provided abstracts. No markdown, no extra text."
)


async def _synthesise_combined(
    llm,
    pathogen_name: str,
    articles_per_field: dict[str, list[dict]],
    llm_sem: asyncio.Semaphore | None = None,
) -> dict[str, str]:
    """One LLM call covering all 4 domains. Returns field_name→synthesis_text dict."""
    sections = []
    for sa in _SUB_AGENTS:
        articles = articles_per_field.get(sa.summary_field, [])
        if not articles:
            sections.append(f"[{sa.label}]\nNo recent articles found.")
        else:
            lines = "\n".join(
                f"- [{a['published_date'] or 'n.d.'}] {a['title']}: {a['article_summary']}"
                for a in articles
            )
            sections.append(f"[{sa.label}]\n{lines}")

    user_content = f"Pathogen: {pathogen_name}\n\n" + "\n\n".join(sections)

    async def _invoke() -> dict[str, str]:
        try:
            content = await llm_invoke_with_retry(
                llm,
                [SystemMessage(content=_COMBINED_SYSTEM), HumanMessage(content=user_content)],
                pathogen=pathogen_name,
            )
            return _parse_combined(content.strip(), pathogen_name)
        except Exception as exc:
            logger.warning("research_synthesis_failed", pathogen=pathogen_name, error=str(exc))
            return {sa.summary_field: f"Synthesis failed: {exc}" for sa in _SUB_AGENTS}

    if llm_sem:
        async with llm_sem:
            return await _invoke()
    return await _invoke()


def _parse_combined(text: str, pathogen_name: str) -> dict[str, str]:
    """
    Parse the combined LLM output into per-domain summary strings.

    Handles variations in bracket style, spacing, and capitalisation.
    Falls back to splitting the text evenly across domains if no headers found.
    """
    logger.debug("research_llm_raw", pathogen=pathogen_name, text=text[:500])

    result: dict[str, str] = {}
    for sa in _SUB_AGENTS:
        # Accept [LABEL], LABEL:, or LABEL (case-insensitive, optional brackets)
        pattern = re.compile(
            r"(?:\[" + re.escape(sa.label) + r"\]|" + re.escape(sa.label) + r"\s*:?)\s*",
            re.IGNORECASE,
        )
        m = pattern.search(text)
        if not m:
            result[sa.summary_field] = ""
            continue
        start = m.end()
        # Find next section header
        next_idx = len(text)
        for other in _SUB_AGENTS:
            if other.summary_field == sa.summary_field:
                continue
            op = re.compile(
                r"(?:\[" + re.escape(other.label) + r"\]|" + re.escape(other.label) + r"\s*:?)\s*",
                re.IGNORECASE,
            )
            om = op.search(text, start)
            if om:
                next_idx = min(next_idx, om.start())
        section = text[start:next_idx].strip()
        # Strip common qwen preambles like "One sentence summary: "
        section = re.sub(r"^(?:one sentence summary|summary)\s*:\s*", "", section, flags=re.IGNORECASE)
        result[sa.summary_field] = section

    # If ALL sections are empty the model didn't follow the format at all.
    # Split the raw text evenly across the 4 domains so we preserve SOMETHING.
    if not any(result.values()):
        logger.warning("research_parse_fallback", pathogen=pathogen_name, raw=text[:200])
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        for i, sa in enumerate(_SUB_AGENTS):
            result[sa.summary_field] = lines[i] if i < len(lines) else text.strip()

    return result


# ── Persistence ───────────────────────────────────────────────────────────────

async def _persist(
    session,
    pathogen: Pathogen,
    sub_results: dict[str, dict],
    total_articles: int,
) -> None:
    """Write all articles and the four sub-agent summaries inside an active transaction."""
    from app.repositories.research import ResearchRepository

    repo = ResearchRepository(session)

    for field_name, result in sub_results.items():
        for art in result["articles"]:
            if not art["pmid"]:
                continue
            await repo.upsert_article(
                pathogen_id=pathogen.id,
                pmid=art["pmid"],
                title=art["title"],
                authors=art["authors"],
                published_date=art["published_date"],
                category=art["category"],
                source_url=art["source_url"],
                abstract=art["abstract"],
                article_summary=art["article_summary"],
            )

    overall_parts = []
    for sub_agent in _SUB_AGENTS:
        result = sub_results.get(sub_agent.summary_field, {})
        text = result.get("synthesis", "").strip()
        if text:
            overall_parts.append(f"{sub_agent.label}\n{text}")
    overall = "\n\n".join(overall_parts)

    await repo.upsert_summary(
        pathogen_id=pathogen.id,
        overall_summary=overall,
        article_count=total_articles,
        molecular_biology_summary=sub_results.get("molecular_biology_summary", {}).get("synthesis"),
        experiments_summary=sub_results.get("experiments_summary", {}).get("synthesis"),
        therapeutics_summary=sub_results.get("therapeutics_summary", {}).get("synthesis"),
        clinical_epi_summary=sub_results.get("clinical_epi_summary", {}).get("synthesis"),
    )


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_research(offset: int = 0) -> dict:
    """
    Run the multi-agent Research pipeline end-to-end.

    offset: skip this many pathogens (alphabetical order) before processing.
            The pipeline runner advances this across passes to cover all pathogens.

    Returns a summary dict for ARQ:
      - pathogens_researched: int
      - articles_saved: int
      - errors: list[str]
    """
    initial: ResearchState = {
        "pathogens": [],
        "offset": offset,
        "pathogens_researched": 0,
        "articles_saved": 0,
        "errors": [],
    }
    final = await _get_graph().ainvoke(initial)
    return {
        "agent": "research",
        "pathogens_researched": final["pathogens_researched"],
        "articles_saved": final["articles_saved"],
        "errors": final["errors"],
    }
