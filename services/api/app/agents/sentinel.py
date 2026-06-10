"""
SentinelAgent — Phase 3 pathogen extraction agent.

Role: Process all PENDING documents from the Phase 2 ingestion pipeline,
extract every infectious pathogen mentioned, normalize names to canonical form,
count occurrences per document, and produce a frequency table across the database.

LangGraph pipeline:
  START → load_pending → [no docs? → END] → extract_mentions → save_results → END

WHY LANGGRAPH?
  LangGraph gives us a composable, observable state machine for multi-step
  agent workflows. Each node is an isolated async function that receives and
  returns the full state — easy to test, easy to add retry/branching logic later.
  In Phase 4, this graph will gain a "verify_mentions" node before save_results.

WHY BATCH EXTRACTION?
  Sending one document per LLM call wastes tokens on repeated system-prompt
  overhead and is slower (N serial API calls vs N/BATCH_SIZE calls).
  Batching 5 documents per call reduces cost ~4× at the expense of slightly
  larger individual responses. If one document in a batch triggers a parse
  error, the whole batch is skipped — acceptable because each doc will be
  retried on the next Sentinel run (status stays PENDING until saved).

WHY source_spans?
  Every AI extraction must be auditable. source_spans lets a human reviewer
  see exactly which sentences triggered a mention count — preventing silent
  hallucinations from inflating the frequency table.
"""

import json
import re
import uuid
from typing import TypedDict

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.db.models.document import DocumentStatus
from app.db.session import AsyncSessionLocal
from app.repositories.document import DocumentRepository
from app.repositories.pathogen_mention import PathogenMentionRepository

from .llm import get_llm
from .prompts import SENTINEL_SYSTEM
from .validators import normalize_pathogen_name

logger = structlog.get_logger(__name__)

BATCH_SIZE = 5          # 5 docs per call — Groq is fast enough to handle batches
MAX_DOCS_PER_RUN = 100  # process up to 100 docs per run on Groq


# ── LangGraph state ───────────────────────────────────────────────────────────

class SentinelState(TypedDict):
    """Accumulated state passed between LangGraph nodes."""
    pending_docs: list[dict]      # loaded from DB: {id, title, text}
    mention_records: list[dict]   # extracted: {doc_id, pathogen_name, mention_count, source_spans}
    processed_count: int
    error_count: int
    errors: list[str]


# ── Graph nodes ───────────────────────────────────────────────────────────────

async def load_pending(state: SentinelState) -> SentinelState:
    """
    Load PENDING documents from PostgreSQL.

    Documents without any text (no title AND no raw_content) are filtered out
    before they reach the LLM — nothing to extract from a blank record.
    Text is capped at 4 000 characters per document to keep prompt size bounded;
    the most epidemiologically relevant content appears in the first few paragraphs.
    """
    async with AsyncSessionLocal() as session:
        repo = DocumentRepository(session)
        docs = await repo.get_pending(limit=MAX_DOCS_PER_RUN)

    pending: list[dict] = []
    for doc in docs:
        text = " ".join(filter(None, [doc.title, doc.raw_content]))
        if text.strip():
            pending.append({
                "id": str(doc.id),
                "title": doc.title or "",
                "text": text[:300],
            })

    logger.info("sentinel_loaded_pending", count=len(pending))
    return {**state, "pending_docs": pending}


async def extract_mentions(state: SentinelState) -> SentinelState:
    """
    Call Claude to extract pathogen mentions from documents in batches.

    Each batch is one API call with BATCH_SIZE document blocks. Claude returns
    a JSON array with one object per document. On parse failure the batch is
    skipped (logged as an error) and those documents remain PENDING for retry.
    """
    llm = get_llm(max_tokens=4096)

    all_mentions: list[dict] = []
    errors = list(state["errors"])
    error_count = state["error_count"]

    for batch_start in range(0, len(state["pending_docs"]), BATCH_SIZE):
        batch = state["pending_docs"][batch_start : batch_start + BATCH_SIZE]
        try:
            response = await llm.ainvoke([
                SystemMessage(content=SENTINEL_SYSTEM),
                HumanMessage(content=_format_batch(batch)),
            ])
            parsed = _parse_json_array(response.content)
            for doc_result in parsed:
                doc_id = doc_result.get("doc_id")
                if not doc_id:
                    continue
                for mention in doc_result.get("mentions", []):
                    name = normalize_pathogen_name(mention.get("pathogen_name", "").strip())
                    count = int(mention.get("mention_count") or 0)
                    if name and count > 0:
                        all_mentions.append({
                            "doc_id": doc_id,
                            "pathogen_name": name,
                            "mention_count": count,
                            "source_spans": mention.get("source_spans") or [],
                        })
        except Exception as exc:
            msg = f"batch {batch_start}–{batch_start + len(batch) - 1}: {type(exc).__name__}: {exc}"
            logger.warning("sentinel_batch_error", batch_start=batch_start, error=str(exc))
            errors.append(msg)
            error_count += 1

    logger.info(
        "sentinel_extraction_done",
        mention_records=len(all_mentions),
        batches=len(state["pending_docs"]) // BATCH_SIZE + 1,
    )
    return {
        **state,
        "mention_records": all_mentions,
        "errors": errors,
        "error_count": error_count,
    }


async def save_results(state: SentinelState) -> SentinelState:
    """
    Write mention records to the pathogen_mentions table and mark every
    loaded document as PROCESSED.

    Documents with zero mentions are still marked PROCESSED — they've been
    read by the Sentinel and contain no pathogen content, which is a valid
    result. Marking them PROCESSED prevents infinite re-processing.

    Uses upsert so a re-run on an already-processed document updates the
    counts rather than raising a unique-constraint error.
    """
    saved_mentions = 0

    async with AsyncSessionLocal() as session:
        async with session.begin():
            mention_repo = PathogenMentionRepository(session)
            doc_repo = DocumentRepository(session)

            for record in state["mention_records"]:
                try:
                    await mention_repo.upsert_mention(
                        document_id=uuid.UUID(record["doc_id"]),
                        pathogen_name=record["pathogen_name"],
                        mention_count=record["mention_count"],
                        source_spans=record["source_spans"],
                    )
                    saved_mentions += 1
                except Exception as exc:
                    logger.warning(
                        "sentinel_mention_save_error",
                        doc_id=record["doc_id"],
                        pathogen=record["pathogen_name"],
                        error=str(exc),
                    )

            for doc in state["pending_docs"]:
                try:
                    await doc_repo.mark_processed(
                        uuid.UUID(doc["id"]),
                        processed_content="sentinel_processed",
                    )
                except Exception as exc:
                    logger.warning(
                        "sentinel_mark_processed_error",
                        doc_id=doc["id"],
                        error=str(exc),
                    )

    docs_marked = len(state["pending_docs"])
    logger.info(
        "sentinel_saved",
        mention_records=saved_mentions,
        documents_marked=docs_marked,
    )
    return {**state, "processed_count": docs_marked}


# ── Graph construction ────────────────────────────────────────────────────────

def _build_graph():
    graph = StateGraph(SentinelState)

    graph.add_node("load_pending", load_pending)
    graph.add_node("extract_mentions", extract_mentions)
    graph.add_node("save_results", save_results)

    graph.add_edge(START, "load_pending")
    graph.add_conditional_edges(
        "load_pending",
        lambda s: END if not s["pending_docs"] else "extract_mentions",
    )
    graph.add_edge("extract_mentions", "save_results")
    graph.add_edge("save_results", END)

    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_batch(docs: list[dict]) -> str:
    """Format a list of document dicts into a structured LLM prompt."""
    blocks = []
    for doc in docs:
        blocks.append(
            f'<document id="{doc["id"]}">\n'
            f'<title>{doc["title"]}</title>\n'
            f'<content>{doc["text"]}</content>\n'
            '</document>'
        )
    return "\n\n".join(blocks)


def _parse_json_array(raw: str) -> list[dict]:
    """Strip markdown fences if present, then parse as a JSON array."""
    text = re.sub(r"^```(?:json)?\s*", "", raw.strip(), flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text.strip(), flags=re.MULTILINE)
    data = json.loads(text.strip())
    return data if isinstance(data, list) else []


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_sentinel() -> dict:
    """
    Run the Sentinel agent end-to-end.

    Returns a summary dict suitable for storage as an ARQ task result:
      - documents_processed: how many PENDING docs were marked PROCESSED
      - unique_pathogens_found: number of distinct normalized pathogen names
      - mention_totals: leaderboard sorted by frequency descending
      - errors: list of error messages from failed batches
    """
    initial: SentinelState = {
        "pending_docs": [],
        "mention_records": [],
        "processed_count": 0,
        "error_count": 0,
        "errors": [],
    }
    final = await _get_graph().ainvoke(initial)

    # Build aggregate counts from this run's extracted records
    counts: dict[str, int] = {}
    for r in final["mention_records"]:
        counts[r["pathogen_name"]] = counts.get(r["pathogen_name"], 0) + r["mention_count"]
    sorted_counts = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "agent": "sentinel",
        "documents_processed": final["processed_count"],
        "unique_pathogens_found": len(counts),
        "mention_totals": [{"pathogen": k, "mentions": v} for k, v in sorted_counts],
        "errors": final["errors"],
    }
