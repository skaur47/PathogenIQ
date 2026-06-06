"""
IngestionService — orchestrates the collector → PostgreSQL pipeline.

RESPONSIBILITY:
  1. Call a collector to get raw documents from an external source.
  2. Bulk-insert them into PostgreSQL, silently skipping duplicates.
  3. Return an IngestionResult with stats (new / duplicates / errors).

WHY BULK INSERT WITH ON CONFLICT DO NOTHING?
  Naive approach (bad):
    for doc in documents:
        if not db.query(Document).filter(...).first():   # SELECT
            db.add(Document(...))                        # INSERT
    # Problems:
    #   • N+1 queries (100 docs = 100 SELECTs + up to 100 INSERTs)
    #   • Race condition: two workers can both see "not exists" and both INSERT,
    #     causing an IntegrityError on the second one

  Our approach (good):
    INSERT INTO documents (...) VALUES (...), (...), (...)
    ON CONFLICT (source, external_id) DO NOTHING
    # One round-trip. PostgreSQL handles deduplication atomically.
    # result.rowcount = number of rows actually inserted (conflicts excluded)

WHY USE SQLALCHEMY CORE (pg_insert) INSTEAD OF ORM?
  The ORM's session.add() calls flush() per object and doesn't support
  ON CONFLICT natively (without additional plugins). SQLAlchemy Core's
  pg_insert() maps directly to the PostgreSQL INSERT statement, giving us
  full control over conflict handling with a single SQL call.

  Trade-off: Core inserts bypass ORM event hooks (like @validates). We don't
  use any ORM events on Document, so this is safe here.

SESSION OWNERSHIP:
  IngestionService does NOT commit. The caller (worker task or API handler)
  owns the transaction. This keeps IngestionService testable in isolation:
  tests can pass a session, call ingest(), inspect the unflushed state, then
  rollback without touching the real database.
"""

import time
from datetime import datetime, timezone

import structlog
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import BaseCollector
from app.collectors.schemas import CollectedDocument, IngestionResult
from app.db.models.document import Document, DocumentStatus

logger = structlog.get_logger(__name__)


class IngestionService:
    """
    Persists collected documents into PostgreSQL with deduplication.

    Args:
        session: An open AsyncSession. The caller must commit/rollback.

    Example (in a worker task):
        async with AsyncSessionLocal() as session:
            async with session.begin():           # auto-commit on success
                service = IngestionService(session)
                result = await service.ingest(PubMedCollector())
        print(result.new_documents)  # how many new papers landed
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def ingest(
        self,
        collector: BaseCollector,
        query: str | None = None,
        max_results: int = 100,
    ) -> IngestionResult:
        """
        Run a collector and persist results.

        Steps:
          1. collector.collect() → list[CollectedDocument]
          2. _bulk_upsert() → INSERT ON CONFLICT DO NOTHING
          3. Return stats in IngestionResult

        Always returns an IngestionResult even on failure — never raises.
        Errors are counted in result.errors.
        """
        started_at = time.perf_counter()
        result = IngestionResult(
            source=collector.source_name,
            query=query,
            collected_at=datetime.now(timezone.utc),
        )

        # Step 1: collect from external source
        try:
            documents = await collector.collect(query=query, max_results=max_results)
        except Exception as e:
            logger.error(
                "ingestion_collect_failed",
                source=collector.source_name,
                error=str(e),
            )
            result.errors = 1
            result.duration_seconds = round(time.perf_counter() - started_at, 3)
            return result

        if not documents:
            result.duration_seconds = round(time.perf_counter() - started_at, 3)
            return result

        # Step 2: bulk insert with deduplication
        new_count, dup_count, error_count = await self._bulk_upsert(documents)

        result.new_documents = new_count
        result.duplicates = dup_count
        result.errors = error_count
        result.duration_seconds = round(time.perf_counter() - started_at, 3)

        logger.info(
            "ingestion_complete",
            source=collector.source_name,
            new=new_count,
            duplicates=dup_count,
            errors=error_count,
            duration_s=result.duration_seconds,
        )

        return result

    async def _bulk_upsert(
        self, documents: list[CollectedDocument]
    ) -> tuple[int, int, int]:
        """
        Bulk-insert documents with conflict-free deduplication.

        Returns:
            (new_count, duplicate_count, error_count)

        PostgreSQL behaviour:
            INSERT INTO documents (...) VALUES (row1), (row2), ...
            ON CONFLICT (source, external_id) DO NOTHING
            ↑ The unique index ix_documents_source_external_id handles this.

        After execution, result.rowcount = rows actually inserted.
        Rows that conflicted (duplicates) are silently skipped.

        UUID and timestamps:
            We don't provide `id`, `created_at`, or `updated_at` in the values
            dict. PostgreSQL fills them via server_default (gen_random_uuid()
            and now() respectively) — defined in UUIDMixin and TimestampMixin.
        """
        if not documents:
            return 0, 0, 0

        rows = [self._document_to_row(doc) for doc in documents]

        try:
            stmt = (
                pg_insert(Document)
                .values(rows)
                .on_conflict_do_nothing(
                    # These two columns form the unique index that defines
                    # "duplicate". Same as ix_documents_source_external_id.
                    index_elements=["source", "external_id"]
                )
            )
            db_result = await self._session.execute(stmt)

            new_count: int = db_result.rowcount
            dup_count: int = len(documents) - new_count
            return new_count, dup_count, 0

        except Exception as e:
            logger.error(
                "ingestion_bulk_insert_error",
                error=str(e),
                document_count=len(documents),
            )
            return 0, 0, len(documents)

    @staticmethod
    def _document_to_row(doc: CollectedDocument) -> dict:
        """
        Convert a CollectedDocument to a plain dict for the Core INSERT.

        Why enum members (not .value) for source/status?
            SQLAlchemy's asyncpg dialect type processor for native PostgreSQL
            enums (Enum(..., name="document_source_enum")) maps Python enum
            members to their correct lowercase DB labels. Passing a plain string
            (doc.source.value = "cdc") causes asyncpg to process the string
            through the enum's NAME attribute ("CDC"), triggering
            InvalidTextRepresentationError: invalid input value for enum
            document_source_enum: "CDC".

        Why `authors or None`?
            An empty list `[]` is valid JSON but semantically meaningless here.
            We store None to distinguish "no authors known" from "empty array".
        """
        return {
            "source": doc.source,
            "external_id": doc.external_id,
            "title": doc.title,
            "abstract": doc.abstract,
            "raw_content": doc.raw_content,
            "url": doc.url,
            "doi": doc.doi,
            "authors": doc.authors if doc.authors else None,
            "published_date": doc.published_date,
            "status": DocumentStatus.PENDING,
            "metadata_json": doc.metadata if doc.metadata else None,
        }
