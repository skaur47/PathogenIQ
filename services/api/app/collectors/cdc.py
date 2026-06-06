"""
CDCCollector — polls the CDC Health Alert Network (HAN) RSS feed.

WHAT IS HAN?
  The CDC Health Alert Network distributes three types of alerts to
  healthcare providers:
    - Health Alert:   Immediate action or attention required.
    - Health Advisory: Important guidance, may not require immediate action.
    - Health Update:  Updates to existing alerts.

  These are the earliest official US government signals for outbreak events.
  An HAN Advisory about a novel pathogen often precedes a full WHO DON by days.

WHY RSS?
  CDC doesn't have a public outbreak events API. RSS is their machine-readable
  output. We fetch the XML with httpx (async) then parse with feedparser (sync,
  very fast). This split keeps the HTTP layer non-blocking.

DEDUPLICATION KEY:
  We use the RSS entry's link URL as external_id. It's stable and unique per
  alert. If CDC updates an alert (same URL, new content), ON CONFLICT DO NOTHING
  will skip it — we treat the first ingestion as authoritative.
  Phase 3 can add "update detection" logic if needed.
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

# CDC MMWR (Morbidity and Mortality Weekly Report) RSS feed.
# MMWR is CDC's primary scientific publication for disease surveillance, outbreak
# investigations, and public health recommendations. It covers all infectious
# disease outbreaks, antimicrobial resistance, epidemiological surveillance, and
# emergency health advisories.
#
# Confirmed working: 2,275 items as of May 2026.
#
# Note: The old CDC Health Alert Network (HAN) URL
# emergency.cdc.gov/han/hcp_rss.asp is permanently redirected away.
# MMWR is the correct current machine-readable CDC outbreak source.
CDC_HAN_RSS_URL = "https://www.cdc.gov/mmwr/rss/mmwr.xml"

# Friendly User-Agent: identify ourselves to CDC's servers.
# Anonymous scrapers risk IP-level rate limiting.
_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (infectious disease intelligence; "
        "admin@pathogeniq.io)"
    )
}


# MMWR has 2,275+ items; prefetch 500 to ensure we find 150 outbreak-relevant
# articles after the date window and relevance filter.
_PREFETCH = 500


class CDCCollector(BaseCollector):
    """
    Collects CDC Morbidity and Mortality Weekly Reports (MMWR) via RSS.

    MMWR covers 2,000+ articles spanning outbreak investigations, AMR surveillance,
    vaccine-preventable diseases, and broader public health topics. We prefetch
    up to _PREFETCH entries and apply the outbreak relevance filter so only
    pathogen/outbreak articles reach the database.
    """

    @property
    def source_name(self) -> str:
        return "cdc"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 150,
    ) -> list[CollectedDocument]:
        log = logger.bind(source="cdc", url=CDC_HAN_RSS_URL)
        log.info("collector_start")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                response = await client.get(CDC_HAN_RSS_URL)
                response.raise_for_status()
        except Exception as e:
            log.error("collector_http_error", error=str(e))
            return []

        # feedparser.parse() accepts bytes — better encoding detection than str.
        feed = feedparser.parse(response.content)

        # feed.bozo is True when feedparser detected a malformed feed.
        # We still attempt to parse entries — feedparser is forgiving.
        if feed.bozo:
            log.warning("collector_feed_malformed", bozo_exception=str(feed.bozo_exception))

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
        """
        Map a feedparser entry dict to a CollectedDocument.

        feedparser normalizes RSS 1.0 / RSS 2.0 / Atom into a uniform dict.
        Key fields we use:
          entry.link     — canonical URL (our deduplication key)
          entry.id       — RSS <guid> (fallback for external_id)
          entry.title    — alert headline
          entry.summary  — alert description (may contain HTML)
          entry.published — date string from <pubDate>
        """
        # Prefer entry.link over entry.id as external_id — it's the stable
        # URL that humans can follow. Fall back to a hash of the title.
        link: str | None = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not link:
            title_text = getattr(entry, "title", "")
            if not title_text:
                return None
            # SHA-256 hash prefix as a deterministic fallback ID
            link = hashlib.sha256(title_text.encode()).hexdigest()[:40]

        title: str | None = getattr(entry, "title", None)
        summary: str | None = getattr(entry, "summary", None)

        # Some feeds put full content in entry.content[0].value instead of summary.
        raw_content = summary
        if hasattr(entry, "content") and entry.content:
            raw_content = entry.content[0].get("value") or summary

        # Published date — feedparser normalises to a string.
        pub_date: str | None = None
        if hasattr(entry, "published") and entry.published:
            pub_date = entry.published
        elif hasattr(entry, "updated") and entry.updated:
            pub_date = entry.updated

        # Tags / categories from the RSS feed
        tags: list[str] = [
            t.get("term", "") for t in getattr(entry, "tags", []) if t.get("term")
        ]

        return CollectedDocument(
            source=DocumentSource.CDC,
            external_id=link,
            title=title,
            abstract=summary,
            raw_content=raw_content,
            url=link if link.startswith("http") else None,
            published_date=pub_date,
            metadata={"feed_entry_id": getattr(entry, "id", None), "tags": tags},
        )
