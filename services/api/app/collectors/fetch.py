"""
Article full-text extraction — shared utility for all Phase 2 collectors.

After the relevance + date filters narrow the document list, each collector
calls enrich_with_full_text() to replace the RSS summary in raw_content with
the full article body text.

WHY trafilatura?
  Designed specifically for article extraction — removes navigation, ads,
  footers, and boilerplate. Handles most news and health authority sites
  without site-specific rules. Falls back gracefully on JavaScript-rendered
  pages or paywalls by returning None.

FALLBACK:
  If extraction fails for any reason (network error, paywall, JavaScript-only
  rendering, or extracted text < 150 chars), the document's existing
  raw_content (the RSS summary) is left unchanged.

CONCURRENCY:
  Up to max_concurrent=10 article fetches run simultaneously. With an 8-second
  timeout per request, 150 articles complete in ~120 seconds worst-case — well
  within the 10-minute ARQ job timeout.
"""

import asyncio

import httpx
import structlog
import trafilatura

from .schemas import CollectedDocument

logger = structlog.get_logger(__name__)

_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (article text extraction; "
        "admin@pathogeniq.io)"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}

# Minimum extracted text length to replace the RSS summary.
# Below this threshold trafilatura likely hit a paywall or sparse page.
_MIN_TEXT_LEN = 150


async def enrich_with_full_text(
    docs: list[CollectedDocument],
    max_concurrent: int = 10,
    request_timeout: float = 8.0,
) -> list[CollectedDocument]:
    """
    Fetch and extract full article body text for each document.

    For each document:
      - URL missing → returned unchanged (keeps RSS summary).
      - Fetch + extract succeeds (>= 150 chars) → raw_content updated.
      - Fetch / extract fails → raw_content keeps the RSS summary.

    Returns the same list length, same order as input.
    """
    if not docs:
        return docs

    sem = asyncio.Semaphore(max_concurrent)

    async with httpx.AsyncClient(
        timeout=request_timeout,
        follow_redirects=True,
        headers=_HEADERS,
    ) as client:
        tasks = [_fetch_one(client, doc, sem) for doc in docs]
        enriched = list(await asyncio.gather(*tasks))

    succeeded = sum(
        1 for orig, new in zip(docs, enriched)
        if new.raw_content != orig.raw_content
    )
    logger.info(
        "full_text_enrichment_done",
        total=len(docs),
        enriched=succeeded,
        unchanged=len(docs) - succeeded,
    )
    return enriched


async def _fetch_one(
    client: httpx.AsyncClient,
    doc: CollectedDocument,
    sem: asyncio.Semaphore,
) -> CollectedDocument:
    if not doc.url:
        return doc

    async with sem:
        try:
            response = await client.get(doc.url)
            response.raise_for_status()
            text = trafilatura.extract(
                response.text,
                include_links=False,
                include_images=False,
                no_fallback=False,
            )
            if text and len(text.strip()) >= _MIN_TEXT_LEN:
                return doc.model_copy(update={"raw_content": text})
        except Exception as exc:
            logger.debug(
                "full_text_fetch_failed",
                url=doc.url,
                error=type(exc).__name__,
            )

    return doc
