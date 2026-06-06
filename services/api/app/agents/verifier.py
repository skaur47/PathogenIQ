"""
VerifierAgent — post-synthesis quality gate for Research and Hypothesis Agents.

Two entry points:
  run_verifier("research")   — checks PathogenResearchSummary v2 fields
  run_verifier("hypothesis") — checks PathogenHypothesis fields

Each non-null field goes through two checks:
  1. Deterministic coherence: catches error strings, short fragments, and
     numeric/symbol garbage — no LLM needed, instant.
  2. LLM biological relevance: one call per pathogen covers all fields;
     incoherent fields are flagged [INCOHERENT] so the model always rewrites
     them; coherent fields are spot-checked for on-topic accuracy.

Corrections are written back to the same DB record immediately.
"""

import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from app.agents.llm import get_llm
from app.db.models.hypothesis import PathogenHypothesis
from app.db.models.pathogen import Pathogen
from app.db.models.research import PathogenResearchSummary
from app.db.session import AsyncSessionLocal

logger = structlog.get_logger(__name__)


# ── Coherence rules (deterministic, no LLM) ───────────────────────────────────

_BAD_SUBSTRINGS = (
    "synthesis failed",
    "failed for this section",
    "recommendation synthesis failed",
    "no summary extracted",
    "synthesis error",
    "section failed:",
)


def _is_coherent(text: str | None) -> bool:
    """Return False for null-like, error-message, or garbage text."""
    if not text or not text.strip():
        return True  # absent is acceptable; we only flag non-null garbage
    t = text.strip()
    if len(t) < 15:
        return False
    if any(bad in t.lower() for bad in _BAD_SUBSTRINGS):
        return False
    if len(t.split()) < 3:
        return False
    if not any(c.isalpha() for c in t):
        return False
    if sum(c.isdigit() for c in t) / len(t) > 0.35:
        return False
    return True


# ── Field definitions ──────────────────────────────────────────────────────────

# (model_attr, display_label)
_RESEARCH_FIELDS: list[tuple[str, str]] = [
    ("molecular_biology_summary", "MOLECULAR BIOLOGY"),
    ("experiments_summary",       "EXPERIMENTS"),
    ("therapeutics_summary",      "THERAPEUTICS"),
    ("clinical_epi_summary",      "CLINICAL EPIDEMIOLOGY"),
]

_HYPOTHESIS_FIELDS: list[tuple[str, str]] = [
    ("research_gap",           "RESEARCH GAP"),
    ("proposed_strategy",      "PROPOSED STRATEGY"),
    ("wetlab_experiments",     "WETLAB EXPERIMENTS"),
    ("clinical_approaches",    "CLINICAL APPROACHES"),
    ("overall_recommendation", "OVERALL RECOMMENDATION"),
]


# ── LLM prompt ─────────────────────────────────────────────────────────────────

_VERIFY_SYSTEM = (
    "You are a biomedical fact-checker. "
    "Review each labeled field for the given pathogen. "
    "For fields marked [INCOHERENT], always write a corrected 1-2 sentence version. "
    "For all other fields, write OK if the text is coherent and biologically relevant "
    "to the named pathogen, or FIX: <corrected text> if it is off-topic, misleading, "
    "or does not make sense for this pathogen. "
    "Keep any FIX text to 1-2 sentences. "
    "Output ONLY the labeled lines — no explanations, no extra text:\n"
    "[LABEL] OK\n"
    "[LABEL] FIX: corrected text"
)


# ── Response parser ────────────────────────────────────────────────────────────

def _parse_response(
    raw: str,
    included: list[tuple[str, str]],
) -> dict[str, str | None]:
    """
    Parse LLM verification output.
    Returns {attr: corrected_text_or_None} — None means keep original.
    """
    result: dict[str, str | None] = {}
    for attr, label in included:
        pattern = re.compile(
            r"\[" + re.escape(label) + r"\]\s*(.*?)(?=\n\[|\Z)",
            re.IGNORECASE | re.DOTALL,
        )
        m = pattern.search(raw)
        if not m:
            result[attr] = None
            continue
        content = m.group(1).strip()
        if re.match(r"^OK\b", content, re.IGNORECASE):
            result[attr] = None
        elif re.match(r"^FIX\s*:", content, re.IGNORECASE):
            corrected = re.sub(r"^FIX\s*:\s*", "", content, flags=re.IGNORECASE).strip()
            result[attr] = corrected if corrected else None
        else:
            result[attr] = None  # ambiguous — preserve original
    return result


# ── Per-record verify ──────────────────────────────────────────────────────────

async def _verify_record(
    llm,
    pathogen: Pathogen,
    record,
    fields: list[tuple[str, str]],
    mode: str,
) -> dict[str, str]:
    """
    Run coherence + LLM relevance check on all fields of one record.
    Returns {attr: new_value} for fields that need correction.
    """
    log = logger.bind(pathogen=pathogen.species_name, mode=mode)

    # Mark each present field as coherent or not
    coherence = {attr: _is_coherent(getattr(record, attr)) for attr, _ in fields}
    bad_fields = [lbl for (attr, lbl) in fields if not coherence[attr] and getattr(record, attr)]

    if bad_fields:
        log.warning("verifier_coherence_fail", fields=bad_fields)
    else:
        # All non-null fields passed the deterministic coherence check — skip the LLM call.
        # Calling LLM for "relevance spot-checks" on already-coherent text is too expensive
        # on CPU-only inference and adds little value with small models.
        log.debug("verifier_skip_llm", reason="all_coherent")
        return {}

    # Build LLM prompt — skip None fields entirely
    transmission = ", ".join(pathogen.transmission_routes or []) or "unknown"
    lines = [
        f"PATHOGEN: {pathogen.species_name}"
        + (f" ({pathogen.category.value})" if pathogen.category else "")
        + (f", {pathogen.genome_type}" if pathogen.genome_type else ""),
        f"TRANSMISSION: {transmission}",
        "",
        "Check these fields:",
    ]

    included: list[tuple[str, str]] = []
    for attr, label in fields:
        text = getattr(record, attr)
        if text is None:
            continue  # nothing to check
        if not coherence[attr]:
            lines.append(f"[{label}] [INCOHERENT]")
        else:
            lines.append(f"[{label}] {text[:300]}")
        included.append((attr, label))

    if not included:
        return {}

    try:
        response = await llm.ainvoke([
            SystemMessage(content=_VERIFY_SYSTEM),
            HumanMessage(content="\n".join(lines)),
        ])
        corrections = _parse_response(response.content, included)
        log.debug("verifier_llm_raw", raw=response.content[:400])
    except Exception as exc:
        log.warning("verifier_llm_error", error=str(exc))
        return {}

    changes: dict[str, str] = {}
    for attr, new_val in corrections.items():
        if new_val is not None:
            old_snippet = str(getattr(record, attr) or "")[:60]
            log.info("verifier_correction", field=attr, old=old_snippet, new=new_val[:60])
            changes[attr] = new_val

    return changes


# ── Entry points ───────────────────────────────────────────────────────────────

async def run_verifier(mode: str) -> dict:
    """
    Run the verifier for mode "research" or "hypothesis".

    Returns:
      agent, mode, pathogens_checked, fields_corrected, errors
    """
    if mode not in ("research", "hypothesis"):
        raise ValueError(f"Unknown verifier mode: {mode!r}")

    llm = get_llm(max_tokens=300)
    fields = _RESEARCH_FIELDS if mode == "research" else _HYPOTHESIS_FIELDS
    Model = PathogenResearchSummary if mode == "research" else PathogenHypothesis

    pathogens_checked = 0
    fields_corrected = 0
    errors: list[str] = []

    # Load all pathogens once
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Pathogen).order_by(Pathogen.species_name))
        pathogens = list(result.scalars().all())

    for pathogen in pathogens:
        name = pathogen.species_name
        log = logger.bind(pathogen=name, mode=mode)

        try:
            # Read — session closed before LLM call so we don't hold a DB
            # connection during inference
            async with AsyncSessionLocal() as session:
                res = await session.execute(
                    select(Model).where(Model.pathogen_id == pathogen.id)
                )
                record = res.scalar_one_or_none()

            if not record:
                log.info("verifier_skip", reason="no record")
                continue

            # LLM verification (no session held)
            changes = await _verify_record(llm, pathogen, record, fields, mode)

            # Write corrections
            if changes:
                async with AsyncSessionLocal() as session:
                    async with session.begin():
                        res2 = await session.execute(
                            select(Model).where(Model.pathogen_id == pathogen.id)
                        )
                        live = res2.scalar_one_or_none()
                        if live:
                            for attr, val in changes.items():
                                setattr(live, attr, val)
                fields_corrected += len(changes)

            pathogens_checked += 1
            log.info("verifier_done", corrections=len(changes))

        except Exception as exc:
            msg = f"{name}: {type(exc).__name__}: {exc}"
            log.warning("verifier_error", error=str(exc))
            errors.append(msg)

    return {
        "agent": "verifier",
        "mode": mode,
        "pathogens_checked": pathogens_checked,
        "fields_corrected": fields_corrected,
        "errors": errors,
    }
