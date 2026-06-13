"""
HypothesisAgent — Phase 5 research gap & strategy synthesis agent.

Role: For each pathogen in the database, read across all available evidence
(biological profile, research landscape, outbreak signal) and:
  1. Identify the most critical current gap in research
  2. Propose a specific therapeutic or preventive strategy
  3. Specify concrete next wet-lab experiments
  4. Propose feasible clinical approaches to control the outbreak
  5. Explain the rationale and synthesize an overall recommendation

The agent NEVER guesses — every claim is grounded in the provided evidence
from pathogens, pathogen_research_summaries, research_articles, and
pathogen_mentions. If data is absent, the agent says so explicitly.

LangGraph pipeline:
  START → load_pathogens → [none? → END] → synthesize_each → END

DESIGN CHOICES:
  - 5 separate focused LLM calls per pathogen rather than one large prompt,
    keeping context small for the local model and each call sharply scoped.
  - Context uses research summaries (not raw articles) to stay within the
    model's context window — summaries are already distilled by ResearchAgent.
  - Per-pathogen persistence immediately after synthesis, identical to
    ResearchAgent's pattern, so partial runs survive worker timeouts.
"""

import asyncio
from typing import TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from sqlalchemy import func, select

from app.db.models.hypothesis import PathogenHypothesis
from app.db.models.pathogen import Pathogen
from app.db.models.pathogen_mention import PathogenMention
from app.db.models.research import PathogenResearchSummary, ResearchArticle, ArticleCategory
from app.db.session import AsyncSessionLocal
from app.repositories.hypothesis import HypothesisRepository
from app.repositories.pathogen import PathogenRepository

from .filters import is_non_pathogen
from .llm import get_llm, llm_invoke_with_retry

logger = structlog.get_logger(__name__)

MAX_PATHOGENS_PER_RUN = 50  # process all pathogens per run on Groq


# ── LangGraph state ───────────────────────────────────────────────────────────

class HypothesisState(TypedDict):
    pathogens: list[Pathogen]
    offset: int
    pathogens_processed: int
    hypotheses_saved: int
    errors: list[str]


# ── Combined LLM system prompt ────────────────────────────────────────────────
# Single call per pathogen (5 separate calls × N pathogens exhausted RPD limits).
# All five sections returned in one response, parsed by _parse_combined_response.

_COMBINED_SYSTEM = (
    "You are a senior biomedical research strategist writing a structured briefing. "
    "Given a pathogen's biological profile and research landscape, produce exactly five labeled sections. "
    "Use these exact labels on their own line, followed immediately by the content:\n\n"
    "RESEARCH_GAP: 2 sentences identifying the most critical knowledge gap.\n"
    "PROPOSED_STRATEGY: 2 sentences proposing one specific therapeutic or preventive approach with its biological rationale.\n"
    "WETLAB_EXPERIMENTS:\n1. One complete sentence per experiment (cell line or animal model, assay type, endpoint).\n2. ...\n3. ...\n"
    "CLINICAL_APPROACHES:\n1. One complete sentence per approach (intervention type, target population, expected outcome).\n2. ...\n3. ...\n"
    "OVERALL_RECOMMENDATION: 2 sentences on the single most impactful first action and why this pathogen warrants prioritization.\n\n"
    "Rules: Every sentence must end with a period. "
    "Every numbered item must be a single complete sentence ending with a period — never a fragment, never trailing punctuation like a comma. "
    "Be concise and specific. Base all claims only on the provided evidence. "
    "Plain text only, no markdown, no extra headers."
)


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def load_pathogens(state: HypothesisState) -> HypothesisState:
    offset = state.get("offset", 0)
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Pathogen)
            .order_by(Pathogen.species_name)
            .offset(offset)
            .limit(MAX_PATHOGENS_PER_RUN)
        )
        pathogens = list(result.scalars().all())

    pathogens = [p for p in pathogens if not is_non_pathogen(p.species_name)]
    logger.info("hypothesis_loaded_pathogens", count=len(pathogens), offset=offset)
    return {**state, "pathogens": pathogens}


async def synthesize_each(state: HypothesisState) -> HypothesisState:
    """
    For each pathogen: gather cross-table evidence, run 5 focused LLM calls,
    compute a deterministic priority score, then persist immediately.
    """
    llm = get_llm(max_tokens=700)
    sem = asyncio.Semaphore(1)  # 1 combined call per pathogen; serialise to stay within RPD limits

    async def _process_one(pathogen: Pathogen) -> tuple[bool, str | None]:
        async with sem:
            name = pathogen.species_name
            try:
                context = await _build_context(pathogen)
                sections = await _synthesize_sections(llm, name, context)
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        repo = HypothesisRepository(session)
                        await repo.upsert_hypothesis(
                            pathogen_id=pathogen.id,
                            research_gap=sections["research_gap"],
                            proposed_strategy=sections["proposed_strategy"],
                            wetlab_experiments=sections["wetlab_experiments"],
                            clinical_approaches=sections["clinical_approaches"],
                            rationale=sections["rationale"],
                            overall_recommendation=sections["overall_recommendation"],
                        )
                logger.info("hypothesis_done", pathogen=name)
                return True, None
            except Exception as exc:
                msg = f"{name}: {type(exc).__name__}: {exc}"
                logger.warning("hypothesis_error", pathogen=name, error=str(exc))
                return False, msg

    results = await asyncio.gather(*[_process_one(p) for p in state["pathogens"]])

    saved = sum(1 for ok, _ in results if ok)
    new_errors = [e for _, e in results if e is not None]

    return {
        **state,
        "pathogens_processed": state["pathogens_processed"] + saved,
        "hypotheses_saved": state["hypotheses_saved"] + saved,
        "errors": state["errors"] + new_errors,
    }


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(HypothesisState)
    graph.add_node("load_pathogens", load_pathogens)
    graph.add_node("synthesize_each", synthesize_each)
    graph.add_edge(START, "load_pathogens")
    graph.add_conditional_edges(
        "load_pathogens",
        lambda s: END if not s["pathogens"] else "synthesize_each",
    )
    graph.add_edge("synthesize_each", END)
    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Context builder ───────────────────────────────────────────────────────────

async def _build_context(pathogen: Pathogen) -> dict:
    """
    Gather all available evidence for one pathogen from four sources:
      1. pathogens — biological profile (already on the object)
      2. pathogen_research_summaries — synthesized landscape
      3. research_articles — top 3 articles per category (title + summary)
      4. pathogen_mentions — aggregate mention / document count
    """
    async with AsyncSessionLocal() as session:
        # Research landscape summary
        summary_result = await session.execute(
            select(PathogenResearchSummary).where(
                PathogenResearchSummary.pathogen_id == pathogen.id
            )
        )
        summary = summary_result.scalar_one_or_none()

        # Recent articles — top 3 per category for context richness
        articles_result = await session.execute(
            select(ResearchArticle)
            .where(ResearchArticle.pathogen_id == pathogen.id)
            .order_by(ResearchArticle.article_category, ResearchArticle.published_date.desc().nulls_last())
        )
        articles = list(articles_result.scalars().all())

        # Outbreak signal — aggregate mention count across all documents
        mention_result = await session.execute(
            select(
                func.sum(PathogenMention.mention_count).label("total_mentions"),
                func.count(PathogenMention.document_id).label("document_count"),
            ).where(PathogenMention.pathogen_name == pathogen.species_name)
        )
        mention_row = mention_result.one_or_none()

    total_mentions = int(mention_row.total_mentions or 0) if mention_row else 0
    document_count = int(mention_row.document_count or 0) if mention_row else 0

    # Group articles by category for structured context
    articles_by_cat: dict[str, list] = {}
    for a in articles:
        cat = a.article_category.value if a.article_category else "unknown"
        articles_by_cat.setdefault(cat, []).append(a)

    return {
        "pathogen": pathogen,
        "summary": summary,
        "articles_by_cat": articles_by_cat,
        "total_mentions": total_mentions,
        "document_count": document_count,
    }


def _format_context(pathogen: Pathogen, ctx: dict) -> str:
    """
    Build a compact, structured context string to feed each LLM call.
    Uses research summaries (not raw articles) to stay within context window.
    """
    p = pathogen
    summary = ctx["summary"]

    transmission = ", ".join(p.transmission_routes) if p.transmission_routes else "unknown"
    hosts = ", ".join(p.reservoir_hosts) if p.reservoir_hosts else "unknown"

    lines = [
        f"PATHOGEN: {p.species_name}" + (f" ({p.common_name})" if p.common_name else ""),
        f"TYPE: {p.category.value if p.category else 'unknown'} | GENOME: {p.genome_type or 'N/A'}",
        f"TRANSMISSION: {transmission}",
        f"RESERVOIR HOSTS: {hosts}",
        f"WHO PRIORITY PATHOGEN: {'yes' if p.who_priority else 'no'}",
        f"OUTBREAK SIGNAL: {ctx['total_mentions']} mentions across {ctx['document_count']} surveillance documents",
        "",
        "CURRENT RESEARCH LANDSCAPE:",
    ]

    if summary:
        # Prefer Phase 4 v2 sub-agent summaries; fall back to v1 legacy columns
        # so hypotheses remain usable even on pre-v2 data.
        v2_sections = [
            ("Molecular Biology", summary.molecular_biology_summary),
            ("Laboratory Experiments & Assays", summary.experiments_summary),
            ("Therapeutics & Vaccines", summary.therapeutics_summary),
            ("Clinical Epidemiology", summary.clinical_epi_summary),
        ]
        v1_fallback = [
            ("Infection Mechanism (legacy)", summary.infection_mechanism_summary),
            ("Wet Lab Findings (legacy)", summary.wet_lab_summary),
            ("Clinical Trials (legacy)", summary.clinical_trial_summary),
            ("Vaccines & Therapies (legacy)", summary.vaccine_therapy_summary),
        ]
        has_v2 = any(text for _, text in v2_sections)
        sections_to_show = v2_sections if has_v2 else v1_fallback
        for label, text in sections_to_show:
            lines.append(f"[{label}] {text or 'No data available.'}")
    else:
        lines.append("No research landscape data available yet.")

    return "\n".join(lines)


# ── LLM synthesis ─────────────────────────────────────────────────────────────

_SECTION_LABELS = [
    ("RESEARCH_GAP:", "research_gap"),
    ("PROPOSED_STRATEGY:", "proposed_strategy"),
    ("WETLAB_EXPERIMENTS:", "wetlab_experiments"),
    ("CLINICAL_APPROACHES:", "clinical_approaches"),
    ("OVERALL_RECOMMENDATION:", "overall_recommendation"),
]


def _parse_combined_response(text: str) -> dict:
    """Extract each labeled section from the combined LLM response."""
    sections: dict[str, str] = {}
    labels = [label for label, _ in _SECTION_LABELS]
    keys = [key for _, key in _SECTION_LABELS]

    for i, (label, key) in enumerate(zip(labels, keys)):
        start = text.find(label)
        if start == -1:
            sections[key] = ""
            continue
        start += len(label)
        end = len(text)
        for next_label in labels[i + 1 :]:
            pos = text.find(next_label, start)
            if pos != -1 and pos < end:
                end = pos
        sections[key] = text[start:end].strip()

    return sections


async def _synthesize_sections(llm, pathogen_name: str, ctx: dict) -> dict:
    pathogen = ctx["pathogen"]
    context_text = _format_context(pathogen, ctx)
    user_content = (
        f"{context_text}\n\n"
        "Produce all five labeled sections for this pathogen following the format in your instructions."
    )
    try:
        content = await llm_invoke_with_retry(
            llm,
            [SystemMessage(content=_COMBINED_SYSTEM), HumanMessage(content=user_content)],
            pathogen=pathogen_name, section="all_sections",
        )
        sections = _parse_combined_response(content.strip())
    except Exception as exc:
        logger.warning("hypothesis_synthesis_failed", pathogen=pathogen_name, error=str(exc))
        msg = f"Synthesis failed: {exc}"
        sections = {key: msg for _, key in _SECTION_LABELS}

    sections["rationale"] = sections.get("proposed_strategy", "")
    return sections


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_hypothesis(offset: int = 0) -> dict:
    """
    Run the Hypothesis Agent end-to-end.

    offset: skip this many pathogens (alphabetical order) before processing.
            The pipeline runner advances this across passes to cover all pathogens.

    Returns a summary dict:
      - pathogens_processed: int
      - hypotheses_saved: int
      - errors: list[str]
    """
    initial: HypothesisState = {
        "pathogens": [],
        "offset": offset,
        "pathogens_processed": 0,
        "hypotheses_saved": 0,
        "errors": [],
    }
    final = await _get_graph().ainvoke(initial)
    return {
        "agent": "hypothesis",
        "pathogens_processed": final["pathogens_processed"],
        "hypotheses_saved": final["hypotheses_saved"],
        "errors": final["errors"],
    }
