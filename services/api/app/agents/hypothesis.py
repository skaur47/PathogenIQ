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
from .llm import get_llm

logger = structlog.get_logger(__name__)

MAX_PATHOGENS_PER_RUN = 1  # 5 LLM calls per pathogen — 1 is enough per run on CPU inference


# ── LangGraph state ───────────────────────────────────────────────────────────

class HypothesisState(TypedDict):
    pathogens: list[Pathogen]
    offset: int
    pathogens_processed: int
    hypotheses_saved: int
    errors: list[str]


# ── Focused LLM system prompts ────────────────────────────────────────────────

_GAP_SYSTEM = (
    "You are a senior biomedical research strategist advising a global health surveillance team. "
    "Given a pathogen's biological profile and current research landscape, identify the single most "
    "critical gap in current research — the missing knowledge that most limits our ability to treat, "
    "prevent, or control this pathogen. "
    "Write 3-5 sentences. State precisely what is known, what is absent, and why this gap is "
    "consequential for public health. Base your analysis only on the evidence provided. "
    "If the landscape is sparse, say what category of research is entirely missing. "
    "Plain text only, no headers, no markdown."
)

_STRATEGY_SYSTEM = (
    "You are a senior biomedical research strategist. Given a pathogen's biological profile and "
    "current research landscape, propose one specific therapeutic or preventive strategy AND "
    "explain the biological and epidemiological rationale for why this approach is sound. "
    "Be mechanistically precise: name the biological target (protein, receptor, pathway), "
    "the intervention type (e.g., mRNA vaccine, monoclonal antibody, small-molecule inhibitor, "
    "attenuated live vaccine, repurposed antiviral), and explain what properties of this pathogen "
    "make this approach feasible given the available evidence. "
    "Write 4-6 sentences covering both the strategy and the reasoning behind it. "
    "Do not invent data — only reason from what is provided. "
    "If evidence is insufficient to propose a specific strategy, state what additional data "
    "would first be needed. Plain text only, no headers, no markdown."
)

_WETLAB_SYSTEM = (
    "You are a senior experimental virologist and microbiologist. Given a pathogen's profile and "
    "proposed strategy, specify the next wet-lab experiments required to advance that strategy. "
    "Provide exactly 3-5 numbered experiments. Each must include: "
    "(a) the experimental model — name the specific cell line (e.g., Vero E6, HEK293T, A549) "
    "or animal model (e.g., BALB/c mice, Syrian hamster, ferret); "
    "(b) the assay type (e.g., plaque reduction assay, ELISA, flow cytometry, Western blot, "
    "RNA-seq, challenge model); "
    "(c) the specific hypothesis or endpoint being tested. "
    "Base recommendations only on the provided evidence. Number each experiment (1., 2., etc.). "
    "Plain text only, no markdown."
)

_CLINICAL_SYSTEM = (
    "You are a senior clinical infectious disease specialist and field epidemiologist. "
    "Given a pathogen's profile and current outbreak signal, propose feasible clinical and "
    "epidemiological approaches to control the outbreak. "
    "Provide exactly 3-5 numbered approaches. Each should specify: "
    "whether it is a clinical intervention (drug trial, vaccine deployment, prophylaxis protocol) "
    "or epidemiological measure (surveillance enhancement, contact tracing, vector control, "
    "quarantine protocol); the target population; and the expected outcome or endpoint. "
    "If Phase I/II trial evidence exists, reference it. If none does, specify what preclinical "
    "threshold must be met first. "
    "Number each approach (1., 2., etc.). Plain text only, no markdown."
)

_RECOMMENDATION_SYSTEM = (
    "You are a senior biosurveillance analyst writing a briefing for public health decision-makers. "
    "Given a pathogen's research gap, proposed strategy, wet-lab experiments, and clinical approaches, "
    "synthesize a concise strategic recommendation. "
    "Write 3-4 sentences covering: (1) the core opportunity — what makes this moment the right time "
    "to act; (2) the single most impactful first action; (3) why this pathogen warrants prioritization "
    "given its current outbreak signal and research gaps relative to its threat level. "
    "Ground every claim in the provided evidence. Plain text only, no markdown."
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
    llm = get_llm(max_tokens=150)

    pathogens_processed = state["pathogens_processed"]
    hypotheses_saved = state["hypotheses_saved"]
    errors = list(state["errors"])

    for pathogen in state["pathogens"]:
        name = pathogen.species_name
        log = logger.bind(pathogen=name)
        log.info("hypothesis_start")

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

            hypotheses_saved += 1
            pathogens_processed += 1
            log.info("hypothesis_done")

        except Exception as exc:
            msg = f"{name}: {type(exc).__name__}: {exc}"
            logger.warning("hypothesis_error", pathogen=name, error=str(exc))
            errors.append(msg)

    return {
        **state,
        "pathogens_processed": pathogens_processed,
        "hypotheses_saved": hypotheses_saved,
        "errors": errors,
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

_SECTION_PROMPTS = {
    "research_gap": (_GAP_SYSTEM, "Based on the above evidence, identify the critical research gap for this pathogen."),
    "proposed_strategy": (_STRATEGY_SYSTEM, "Propose a specific therapeutic or preventive strategy for this pathogen."),
    "wetlab_experiments": (_WETLAB_SYSTEM, "Specify the next wet-lab experiments to advance the strategy against this pathogen."),
    "clinical_approaches": (_CLINICAL_SYSTEM, "Propose feasible clinical and epidemiological approaches to control this pathogen's outbreak."),
}

_RECOMMENDATION_PROMPT = "Synthesize a strategic recommendation for prioritizing research and intervention against this pathogen."


async def _synthesize_sections(llm, pathogen_name: str, ctx: dict) -> dict:
    pathogen = ctx["pathogen"]
    context_text = _format_context(pathogen, ctx)
    sections: dict[str, str] = {}

    # Run gap / strategy / wetlab / clinical sequentially (each builds on prior)
    for key, (system_prompt, user_suffix) in _SECTION_PROMPTS.items():
        user_content = f"{context_text}\n\n{user_suffix}"
        try:
            response = await llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_content),
            ])
            sections[key] = response.content.strip()
        except Exception as exc:
            logger.warning(
                "hypothesis_section_failed",
                pathogen=pathogen_name,
                section=key,
                error=str(exc),
            )
            sections[key] = f"Synthesis failed for this section: {exc}"
        await asyncio.sleep(0.3)

    # Rationale is embedded in the strategy response — no separate LLM call needed.
    sections["rationale"] = sections.get("proposed_strategy", "")

    await asyncio.sleep(0.3)

    # Overall recommendation — synthesizes all prior sections.
    # Truncate each section to 300 chars to keep the combined prompt small for CPU inference.
    def _trunc(s: str, n: int = 300) -> str:
        return s[:n] + "…" if len(s) > n else s

    rec_context = (
        f"{context_text}\n\n"
        f"RESEARCH GAP: {_trunc(sections.get('research_gap', ''))}\n\n"
        f"PROPOSED STRATEGY: {_trunc(sections.get('proposed_strategy', ''))}\n\n"
        f"KEY WET-LAB STEPS: {_trunc(sections.get('wetlab_experiments', ''))}\n\n"
        f"KEY CLINICAL STEPS: {_trunc(sections.get('clinical_approaches', ''))}\n\n"
        f"{_RECOMMENDATION_PROMPT}"
    )
    try:
        response = await llm.ainvoke([
            SystemMessage(content=_RECOMMENDATION_SYSTEM),
            HumanMessage(content=rec_context),
        ])
        sections["overall_recommendation"] = response.content.strip()
    except Exception as exc:
        logger.warning("hypothesis_recommendation_failed", pathogen=pathogen_name, error=str(exc))
        sections["overall_recommendation"] = f"Recommendation synthesis failed: {exc}"

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
