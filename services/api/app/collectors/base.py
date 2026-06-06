"""
BaseCollector — the contract every data-source collector must satisfy.

WHY an abstract base class?
  The IngestionService calls collector.collect() without knowing whether it's
  talking to PubMed's REST API, a CDC RSS feed, or a future WHO GOARN scraper.
  This is the Strategy pattern: the algorithm (ingestion) is fixed; the strategy
  (how to collect) is swappable.

  Adding a new source = write a new class that inherits BaseCollector.
  Zero changes to IngestionService, worker tasks, or API endpoints.

DESIGN CONTRACT:
  1. collect() MUST NOT raise. Catch all exceptions internally and return [].
     A failing collector must not crash the task that calls it.
  2. collect() MUST be idempotent — running it twice returns the same docs.
     The IngestionService deduplicates, but collectors shouldn't make this harder.
  3. Return empty list, never None.
"""

from abc import ABC, abstractmethod

from .schemas import CollectedDocument


class BaseCollector(ABC):

    @abstractmethod
    async def collect(
        self,
        query: str | None = None,
        max_results: int = 100,
    ) -> list[CollectedDocument]:
        """
        Fetch documents from the external source.

        Args:
            query:       Source-specific query string (search terms for PubMed;
                         ignored for RSS-based sources like CDC and WHO).
            max_results: Maximum number of documents to return.

        Returns:
            List of CollectedDocument objects. Empty list if unavailable.
        """
        ...

    @property
    @abstractmethod
    def source_name(self) -> str:
        """
        Machine-readable name matching the DocumentSource enum value.
        Used in log lines and IngestionResult.source.
        """
        ...
