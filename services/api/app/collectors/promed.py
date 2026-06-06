"""
ProMEDCollector — collects outbreak intelligence from CIDRAP.

ORIGINAL TARGET: ProMED-mail (promedmail.org)
  ProMED is the world's oldest outbreak intelligence network (since 1994),
  run by the International Society for Infectious Diseases. In early 2026
  they migrated to a new Next.js platform backed by a subscription model.
  Their RSS feed (promedmail.org/promed-rss.xml) now returns 404. Full
  content requires a paid account via Auth0.

CURRENT SOURCE: CIDRAP (Center for Infectious Disease Research and Policy)
  University of Minnesota's CIDRAP is among the most authoritative free
  sources for infectious disease outbreak journalism. Their news team
  covers outbreaks, AMR, pandemic preparedness, and vaccine-preventable
  diseases. Every article is editorially curated — no relevance filter
  needed (unlike general health news feeds).

  RSS URL: https://www.cidrap.umn.edu/rss.xml
  Confirmed HTTP 200 as of May 2026.

WHY source="promed"?
  DocumentSource.PROMED already exists in the DB schema and represents
  "expert-curated outbreak intelligence" — the semantic category that
  both ProMED and CIDRAP fill. Storing CIDRAP under PROMED keeps the
  existing indexes intact and avoids a migration. The actual source URL
  in metadata_json distinguishes these from true ProMED records if we
  restore ProMED access in the future.

NOTE:
  If ProMED restores free RSS access, replace CIDRAP_RSS_URL with the
  ProMED URL and update this docstring.
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

CIDRAP_RSS_URL = "https://www.cidrap.umn.edu/rss.xml"

_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (outbreak intelligence; "
        "admin@pathogeniq.io)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class ProMEDCollector(BaseCollector):
    """
    Collects CIDRAP infectious disease news (stored as source=promed).

    CIDRAP covers outbreaks, AMR, clinical research, and policy.
    Relevance filter applied to keep only active outbreak content.
    """

    @property
    def source_name(self) -> str:
        return "promed"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 150,
    ) -> list[CollectedDocument]:
        log = logger.bind(source="promed", url=CIDRAP_RSS_URL)
        log.info("collector_start")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                response = await client.get(CIDRAP_RSS_URL)
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
        for entry in feed.entries[:max_results]:
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
        Map a ProMED feed entry to a CollectedDocument.

        ProMED entry structure:
          entry.link      — permanent URL (e.g. https://promedmail.org/promed-post/?id=...)
          entry.id        — GUID (same as link or a numeric ID)
          entry.title     — disease + location headline
          entry.summary   — HTML excerpt of the alert text
          entry.published — date string
        """
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

        tags: list[str] = [
            t.get("term", "") for t in getattr(entry, "tags", []) if t.get("term")
        ]

        return CollectedDocument(
            source=DocumentSource.PROMED,
            external_id=link,
            title=title,
            abstract=summary,
            raw_content=raw_content,
            url=link if link.startswith("http") else None,
            published_date=pub_date,
            metadata={
                "feed_entry_id": getattr(entry, "id", None),
                "tags": tags,
                "feed_source": "cidrap",
            },
        )
