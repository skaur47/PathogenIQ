"""
NewsCollector — aggregates outbreak-relevant articles from major free news RSS feeds.

SOURCES (all free, no API key required):
  STAT News           https://www.statnews.com/feed/
    Best single source for infectious disease and public health journalism.
    Dedicated science reporters; often breaks outbreak stories first.

  BBC Health          https://feeds.bbci.co.uk/news/health/rss.xml
    Broad international health coverage; strong on WHO/UN outbreak events.

  NPR Health          https://feeds.npr.org/1128/rss.xml
    US public health focus; good CDC/NIH coverage.

  Outbreak News Today https://outbreaknewstoday.com/feed/
    Dedicated outbreak news aggregator — already highly curated. Low false
    positive rate even before the relevance filter.

  ScienceDaily Health https://www.sciencedaily.com/rss/health_medicine.xml
    Research-oriented; covers outbreak studies and epidemiology papers
    before they reach PubMed indexing.

STRATEGY:
  1. Fetch all feeds concurrently (asyncio.gather).
  2. Deduplicate by URL across feeds (same story can appear in multiple).
  3. Apply outbreak relevance filter (collectors/filter.py).
  4. Return the most recent max_results after filtering.

  Fetching more than max_results per feed before filtering ensures we
  don't run out of relevant articles when most feed content is general health.
  Each feed pre-fetches up to _PREFETCH_PER_FEED entries; after filtering
  and deduplication we trim to max_results.

DEDUPLICATION KEY:
  Entry URL (entry.link). Cross-feed duplicates are removed in _deduplicate()
  before the relevance filter runs. Within-source duplicates (same URL seen
  in a later run) are handled by IngestionService ON CONFLICT DO NOTHING.
"""

import asyncio
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

_FEED_URLS: list[str] = [
    "https://www.statnews.com/feed/",
    "https://feeds.bbci.co.uk/news/health/rss.xml",
    "https://feeds.npr.org/1128/rss.xml",
    "https://outbreaknewstoday.com/feed/",
    "https://www.sciencedaily.com/rss/health_medicine.xml",
]

_PREFETCH_PER_FEED = 100

_HEADERS = {
    "User-Agent": (
        "PathogenIQ/0.2 Biosurveillance (news monitoring; "
        "admin@pathogeniq.io)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class NewsCollector(BaseCollector):
    """
    Aggregates outbreak-relevant articles from multiple free news RSS feeds.

    Applies a keyword relevance filter — general health stories (diet, mental
    health, drug approvals unrelated to infectious disease) are discarded.
    Only pathogen/outbreak content reaches the database.
    """

    @property
    def source_name(self) -> str:
        return "news"

    async def collect(
        self,
        query: str | None = None,
        max_results: int = 150,
    ) -> list[CollectedDocument]:
        log = logger.bind(source="news", feed_count=len(_FEED_URLS))
        log.info("collector_start")

        async with httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers=_HEADERS,
        ) as client:
            fetch_tasks = [self._fetch_feed(client, url) for url in _FEED_URLS]
            results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        raw_docs: list[CollectedDocument] = []
        for url, result in zip(_FEED_URLS, results):
            if isinstance(result, Exception):
                log.warning("feed_fetch_failed", url=url, error=str(result))
                continue
            raw_docs.extend(result)

        deduped = self._deduplicate(raw_docs)
        relevant = filter_outbreak_relevant(deduped)
        recent = filter_recent(relevant, days=14)
        to_enrich = recent[:max_results]
        enriched = await enrich_with_full_text(to_enrich)

        log.info(
            "collector_done",
            raw=len(raw_docs),
            after_dedup=len(deduped),
            relevant=len(relevant),
            recent=len(recent),
            returned=len(enriched),
        )
        return enriched

    async def _fetch_feed(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> list[CollectedDocument]:
        """Fetch one RSS feed and parse it into CollectedDocuments."""
        try:
            response = await client.get(url)
            response.raise_for_status()
        except Exception as e:
            logger.warning("news_feed_http_error", url=url, error=str(e))
            return []

        feed = feedparser.parse(response.content)
        if not feed.entries:
            return []

        docs: list[CollectedDocument] = []
        for entry in feed.entries[:_PREFETCH_PER_FEED]:
            doc = self._entry_to_document(entry, feed_url=url)
            if doc:
                docs.append(doc)
        return docs

    @staticmethod
    def _deduplicate(docs: list[CollectedDocument]) -> list[CollectedDocument]:
        """Remove cross-feed duplicates, keeping first occurrence (newest feed)."""
        seen: set[str] = set()
        unique: list[CollectedDocument] = []
        for doc in docs:
            if doc.external_id not in seen:
                seen.add(doc.external_id)
                unique.append(doc)
        return unique

    def _entry_to_document(
        self,
        entry,
        feed_url: str,
    ) -> CollectedDocument | None:
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
            source=DocumentSource.NEWS,
            external_id=link,
            title=title,
            abstract=summary,
            raw_content=raw_content,
            url=link if link.startswith("http") else None,
            published_date=pub_date,
            metadata={
                "feed_url": feed_url,
                "feed_entry_id": getattr(entry, "id", None),
                "tags": tags,
            },
        )
