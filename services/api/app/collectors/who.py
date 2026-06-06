"""
WHOCollector — polls the PAHO (Pan American Health Organization) RSS feed.

WHAT IS PAHO?
  PAHO is the WHO Regional Office for the Americas — the branch of WHO
  responsible for disease surveillance across North, Central, and South America.
  PAHO publishes:
    - Epidemiological alerts and updates for the Americas region
    - Weekly epidemiological reports
    - Disease outbreak news (aligned with WHO IHR framework)

NOTE ON WHO DON RSS:
  WHO's original Disease Outbreak News (DON) RSS feed at
  www.who.int/feeds/entity/don/lang__en/rss.xml was permanently removed
  when WHO redesigned their website in 2024. All alternate WHO RSS URLs
  (apps.who.int, news-room, mediacentre, hq) now return either 404 or
  a redirect to their HTML homepage with a 200 status (no XML body).

  WHO DON content remains available on their website as HTML only:
    https://www.who.int/emergencies/disease-outbreak-news
  A proper WHO DON scraper using BeautifulSoup will be added in Phase 3.

  For Phase 2, we use PAHO's RSS (confirmed working, 10+ items) as our
  WHO-affiliated global health source. PAHO documents are marked source=WHO
  in the database since PAHO is structurally a WHO office.
"""

import feedparser
import httpx
import structlog

from app.db.models.document import DocumentSource

from .base import BaseCollector
from .fetch import enrich_with_full_text
from .filter import filter_outbreak_relevant, filter_recent
from .schemas import CollectedDocument

logger = structlog.get_logger(__name__)

# PAHO (WHO Americas) general news RSS — confirmed HTTP 200, ~10 items.
# Covers epidemiological alerts, outbreak updates, and health emergencies
# across the Americas region.
WHO_DON_RSS_URL = "https://www.paho.org/en/rss.xml"

_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (infectious disease surveillance; "
        "admin@pathogeniq.io)"
    ),
    # WHO's CDN occasionally returns 406 for missing Accept headers.
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


_PREFETCH = 300


class WHOCollector(BaseCollector):
    """
    Collects global health alerts from PAHO (WHO Regional Office for the Americas).

    PAHO's RSS covers outbreak alerts and broader health news. Relevance filter
    applied to retain only pathogen/outbreak-relevant content.
    """

    @property
    def source_name(self) -> str:
        return "who"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 150,
    ) -> list[CollectedDocument]:
        log = logger.bind(source="who", url=WHO_DON_RSS_URL)
        log.info("collector_start")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers=_HEADERS,
            ) as client:
                response = await client.get(WHO_DON_RSS_URL)
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
        """
        Map a WHO DON feed entry to a CollectedDocument.

        WHO DON entries typically have:
          entry.link     — full URL to the DON page (e.g. https://www.who.int/emergencies/disease-outbreak-news/item/...)
          entry.title    — e.g. "Mpox – Democratic Republic of the Congo"
          entry.summary  — short description of the event
          entry.published — ISO date string
        """
        link: str | None = getattr(entry, "link", None) or getattr(entry, "id", None)
        if not link:
            return None

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
            metadata={"feed_entry_id": getattr(entry, "id", None)},
        )
