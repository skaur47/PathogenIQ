"""
Tests for IngestionService.

IMPORTANT NOTE ON DATABASE COMPATIBILITY:
  IngestionService._bulk_upsert() uses SQLAlchemy Core's pg_insert() (PostgreSQL
  dialect INSERT ... ON CONFLICT DO NOTHING). This is PostgreSQL-specific syntax
  and does NOT work with SQLite, which is used in the conftest test fixtures.

  For this reason, IngestionService tests are structured in two layers:

  1. Unit tests (this file): test the collect() → _document_to_row() pipeline
     using a mocked session. No real DB required.

  2. Integration tests (tests/integration/test_ingestion_pg.py):
     Use a real PostgreSQL instance to test _bulk_upsert() with ON CONFLICT.
     These run in CI when Docker Compose is available.

WHAT WE TEST HERE:
  - IngestionResult is populated correctly
  - _document_to_row() maps all fields
  - Collector errors are caught and counted in result.errors
  - Empty collector output returns zero counts
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedDocument, IngestionResult
from app.db.models.document import DocumentSource, DocumentStatus
from app.services.ingestion import IngestionService


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_document(
    source=DocumentSource.PUBMED,
    external_id="12345678",
    title="Test Article on Influenza",
    abstract="An abstract about influenza surveillance.",
    authors=None,
    doi="10.1234/test",
    url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
    published_date="2025-Mar",
    metadata=None,
) -> CollectedDocument:
    """Factory for CollectedDocument test fixtures."""
    return CollectedDocument(
        source=source,
        external_id=external_id,
        title=title,
        abstract=abstract,
        raw_content=abstract,
        authors=["Smith Alice", "Jones Bob"] if authors is None else authors,
        doi=doi,
        url=url,
        published_date=published_date,
        metadata={"mesh_terms": ["Influenza"]} if metadata is None else metadata,
    )


class AlwaysSuccessCollector(BaseCollector):
    """Test double: returns a fixed list of documents."""

    def __init__(self, documents: list[CollectedDocument]):
        self._documents = documents

    @property
    def source_name(self) -> str:
        return "test_source"

    async def collect(self, query=None, max_results=100) -> list[CollectedDocument]:
        return self._documents


class AlwaysFailCollector(BaseCollector):
    """Test double: raises on collect() to simulate external API failure."""

    @property
    def source_name(self) -> str:
        return "failing_source"

    async def collect(self, query=None, max_results=100) -> list[CollectedDocument]:
        raise ConnectionError("External API is down")


class EmptyCollector(BaseCollector):
    """Test double: returns no documents (source has nothing new)."""

    @property
    def source_name(self) -> str:
        return "empty_source"

    async def collect(self, query=None, max_results=100) -> list[CollectedDocument]:
        return []


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestIngestionServiceDocumentToRow:
    """
    Test the _document_to_row() mapping.
    This is pure Python (no DB) — fast and exhaustive.
    """

    def test_maps_all_fields(self):
        doc = make_document()
        row = IngestionService._document_to_row(doc)

        assert row["source"] == "pubmed"
        assert row["external_id"] == "12345678"
        assert row["title"] == "Test Article on Influenza"
        assert row["abstract"] == "An abstract about influenza surveillance."
        assert row["doi"] == "10.1234/test"
        assert row["url"] == "https://pubmed.ncbi.nlm.nih.gov/12345678/"
        assert row["published_date"] == "2025-Mar"
        assert row["status"] == DocumentStatus.PENDING.value
        assert row["authors"] == ["Smith Alice", "Jones Bob"]

    def test_source_is_string_value(self):
        """Core inserts need the .value string, not the Enum member."""
        doc = make_document(source=DocumentSource.CDC)
        row = IngestionService._document_to_row(doc)
        assert row["source"] == "cdc"
        assert isinstance(row["source"], str)

    def test_empty_authors_stored_as_none(self):
        """Empty list → None, to distinguish 'no authors' from 'empty array'."""
        doc = make_document(authors=[])
        row = IngestionService._document_to_row(doc)
        assert row["authors"] is None

    def test_empty_metadata_stored_as_none(self):
        doc = make_document(metadata={})
        row = IngestionService._document_to_row(doc)
        assert row["metadata_json"] is None

    def test_non_empty_metadata_preserved(self):
        doc = make_document(metadata={"mesh_terms": ["Influenza", "Epidemics"]})
        row = IngestionService._document_to_row(doc)
        assert row["metadata_json"]["mesh_terms"] == ["Influenza", "Epidemics"]

    def test_status_is_always_pending(self):
        """Ingested documents always start as PENDING for agent processing."""
        doc = make_document()
        row = IngestionService._document_to_row(doc)
        assert row["status"] == "pending"


class TestIngestionServiceIngest:
    """
    Test IngestionService.ingest() with mocked session.

    We mock _bulk_upsert() to avoid needing PostgreSQL. The goal is to verify
    that:
      - IngestionResult is populated from both collector and bulk_upsert output
      - Errors from collector.collect() are counted correctly
      - Duration is recorded
    """

    def _make_service_with_mock_upsert(self, new=5, dup=2, err=0):
        """Create IngestionService with a mocked session and _bulk_upsert."""
        mock_session = MagicMock()
        service = IngestionService(session=mock_session)
        service._bulk_upsert = AsyncMock(return_value=(new, dup, err))
        return service

    @pytest.mark.asyncio
    async def test_ingest_counts_new_documents(self):
        docs = [make_document(external_id=str(i)) for i in range(5)]
        service = self._make_service_with_mock_upsert(new=5, dup=0)
        result = await service.ingest(AlwaysSuccessCollector(docs))

        assert result.new_documents == 5
        assert result.duplicates == 0
        assert result.errors == 0

    @pytest.mark.asyncio
    async def test_ingest_counts_duplicates(self):
        docs = [make_document(external_id=str(i)) for i in range(7)]
        service = self._make_service_with_mock_upsert(new=5, dup=2)
        result = await service.ingest(AlwaysSuccessCollector(docs))

        assert result.new_documents == 5
        assert result.duplicates == 2

    @pytest.mark.asyncio
    async def test_ingest_handles_collector_failure(self):
        """When collector.collect() raises, result.errors=1 and no DB call."""
        mock_session = MagicMock()
        service = IngestionService(session=mock_session)
        service._bulk_upsert = AsyncMock()

        result = await service.ingest(AlwaysFailCollector())

        assert result.errors == 1
        assert result.new_documents == 0
        service._bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_empty_collector_returns_zeros(self):
        """No documents collected → no DB call, zero counts."""
        mock_session = MagicMock()
        service = IngestionService(session=mock_session)
        service._bulk_upsert = AsyncMock()

        result = await service.ingest(EmptyCollector())

        assert result.new_documents == 0
        assert result.duplicates == 0
        assert result.errors == 0
        service._bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_ingest_records_source_name(self):
        service = self._make_service_with_mock_upsert()
        result = await service.ingest(AlwaysSuccessCollector([make_document()]))
        assert result.source == "test_source"

    @pytest.mark.asyncio
    async def test_ingest_records_query(self):
        service = self._make_service_with_mock_upsert()
        result = await service.ingest(
            AlwaysSuccessCollector([make_document()]),
            query="influenza outbreak",
        )
        assert result.query == "influenza outbreak"

    @pytest.mark.asyncio
    async def test_ingest_records_duration(self):
        service = self._make_service_with_mock_upsert()
        result = await service.ingest(AlwaysSuccessCollector([make_document()]))
        assert result.duration_seconds >= 0
        assert result.duration_seconds < 10  # should complete in under 10s

    @pytest.mark.asyncio
    async def test_ingest_result_is_json_serialisable(self):
        """IngestionResult must be serialisable (ARQ stores it as JSON)."""
        service = self._make_service_with_mock_upsert(new=3, dup=1)
        result = await service.ingest(AlwaysSuccessCollector([make_document()]))

        # model_dump(mode="json") converts datetime → ISO string
        data = result.model_dump(mode="json")
        assert isinstance(data["collected_at"], str)
        assert isinstance(data["new_documents"], int)
        assert isinstance(data["duration_seconds"], float)
