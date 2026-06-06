"""
ECDCCollector — polls the European Centre for Disease Prevention and Control RSS feed.

WHAT IS ECDC?
  The European Centre for Disease Prevention and Control (ECDC) is an EU agency
  that monitors and reports on communicable disease threats across Europe and
  globally. Their threat assessments, rapid risk assessments, and surveillance
  reports are authoritative early-warning signals comparable to WHO DON.

  ECDC covers:
    - Rapid Risk Assessments (new or evolving outbreak threats to Europe)
    - Weekly influenza and COVID surveillance
    - Multi-country outbreak investigations
    - Antimicrobial resistance (AMR) alerts
    - Vaccination coverage reports

WHY source=WHO?
  The DocumentSource enum represents the authority tier, not the exact agency.
  ECDC operates under the same IHR (International Health Regulations) framework
  as WHO and publishes equivalent-grade scientific alerts. Storing them as WHO
  reflects their authoritative status. The source URL in metadata distinguishes
  ECDC from PAHO records at query time.

DEDUPLICATION:
  We use the entry link as external_id. ECDC links are permanent per-publication
  URLs, so the same report is never ingested twice.

RELEVANCE FILTER:
  Applied after collection — ECDC covers a broad range of topics including
  non-outbreak surveillance summaries (vaccination uptake statistics, antibiotic
  consumption reports). The filter keeps only pathogen/outbreak-relevant items.
"""

import hashlib

import feedparser
import httpx
import structlog

from app.db.models.document import DocumentSource

from .base import BaseCollector
from .fetch import enrich_with_full_text
from .filter import filter_outbreak_relevant, filter_recent
from .schemas import CollectedDocument

logger = structlog.get_logger(__name__)

# Communicable Disease Threats Report — ECDC's weekly threat report covering all
# active outbreaks and emerging threats in Europe. This taxonomy term is stable.
# Confirmed HTTP 200 as of May 2026. /en/rss.xml (old URL) returns 404 after
# their 2024 website redesign.
ECDC_RSS_URL = "https://www.ecdc.europa.eu/en/taxonomy/term/323/feed"

_PREFETCH = 300

_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (European outbreak surveillance; "
        "admin@pathogeniq.io)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class ECDCCollector(BaseCollector):
    """
    Collects European outbreak intelligence from ECDC's RSS feed.

    Documents are stored with source=WHO (ECDC is a WHO-tier authority).
    Relevance filter applied — ECDC covers broader public health topics
    beyond just active outbreaks.
    """

    @property
    def source_name(self) -> str:
        return "who"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 150,
    ) -> list[CollectedDocument]:
        log = logger.bind(source="ecdc", url=ECDC_RSS_URL)
        log.info("collector_start")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                response = await client.get(ECDC_RSS_URL)
                response.raise_for_status()
        except Exception as e:
            log.error("collector_http_error", error=str(e))
            return []

        feed = feedparser.parse(response.content)

        if feed.bozo:
            log.warning(
                "collector_feed_malformed",
                bozo_exception=str(feed.bozo_exception),
            )

        if not feed.entries:
            log.warning("collector_no_entries")
            return []

        raw_docs: list[CollectedDocument] = []
        for entry in feed.entries[:_PREFETCH]:
            doc = self._entry_to_document(entry)
            if doc:
                raw_docs.append(doc)

        relevant = filter_outbreak_relevant(raw_docs)
        recent = filter_recent(relevant, days=14)
        to_enrich = recent[:max_results]
        enriched = await enrich_with_full_text(to_enrich)

        log.info(
            "collector_done",
            fetched=len(raw_docs),
            relevant=len(relevant),
            recent=len(recent),
            returned=len(enriched),
        )
        return enriched

    def _entry_to_document(self, entry) -> CollectedDocument | None:
        link: str | None = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not link:
            title_text = getattr(entry, "title", "")
            if not title_text:
                return None
            link = hashlib.sha256(title_text.encode()).hexdigest()[:40]

        title: str | None = getattr(entry, "title", None)
        summary: str | None = getattr(entry, "summary", None)

        raw_content = summary
        if hasattr(entry, "content") and entry.content:
            raw_content = entry.content[0].get("value") or summary

        pub_date: str | None = None
        if hasattr(entry, "published") and entry.published:
            pub_date = entry.published
        elif hasattr(entry, "updated") and entry.updated:
            pub_date = entry.updated

        return CollectedDocument(
            source=DocumentSource.WHO,
            external_id=link,
            title=title,
            abstract=summary,
            raw_content=raw_content,
            url=link if link.startswith("http") else None,
            published_date=pub_date,
            metadata={
                "feed_entry_id": getattr(entry, "id", None),
                "feed_source": "ecdc",
            },
        )
