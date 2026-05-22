"""
Repository layer tests.

These tests verify the database query logic in isolation,
without going through the HTTP layer. They test the repository
methods directly with a real (in-memory) database.

This is valuable because:
  - Logic bugs in repositories won't always surface in endpoint tests
  - Repositories contain the most complex query logic (filtering, pagination)
  - Testing at this layer is faster than full HTTP round-trips
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.document import Document, DocumentSource, DocumentStatus
from app.db.models.pathogen import Pathogen, PathogenCategory
from app.repositories.document import DocumentRepository
from app.repositories.pathogen import PathogenRepository


# ── Document repository tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_document_create_and_retrieve(db_session: AsyncSession) -> None:
    """Create a document and retrieve it by ID."""
    repo = DocumentRepository(db_session)

    doc = await repo.create(
        source=DocumentSource.PUBMED,
        external_id="PMID123456",
        title="SARS-CoV-2 transmission dynamics",
        status=DocumentStatus.PENDING,
    )
    await db_session.commit()

    retrieved = await repo.get_by_id(doc.id)
    assert retrieved is not None
    assert retrieved.external_id == "PMID123456"
    assert retrieved.source == DocumentSource.PUBMED
    assert retrieved.status == DocumentStatus.PENDING


@pytest.mark.asyncio
async def test_document_get_by_external_id(db_session: AsyncSession) -> None:
    """Look up a document by its (source, external_id) natural key."""
    repo = DocumentRepository(db_session)

    await repo.create(
        source=DocumentSource.CDC,
        external_id="cdc-alert-2024-001",
        title="Novel H5N1 cluster detected",
        status=DocumentStatus.PENDING,
    )
    await db_session.commit()

    doc = await repo.get_by_external_id(DocumentSource.CDC, "cdc-alert-2024-001")
    assert doc is not None
    assert doc.title == "Novel H5N1 cluster detected"


@pytest.mark.asyncio
async def test_document_not_found_returns_none(db_session: AsyncSession) -> None:
    """Missing document returns None, not an exception."""
    repo = DocumentRepository(db_session)
    import uuid
    result = await repo.get_by_id(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_document_get_pending(db_session: AsyncSession) -> None:
    """Only PENDING documents appear in the processing queue."""
    repo = DocumentRepository(db_session)

    await repo.create(source=DocumentSource.PUBMED, external_id="p1", status=DocumentStatus.PENDING)
    await repo.create(source=DocumentSource.PUBMED, external_id="p2", status=DocumentStatus.PROCESSED)
    await repo.create(source=DocumentSource.PUBMED, external_id="p3", status=DocumentStatus.PENDING)
    await db_session.commit()

    pending = await repo.get_pending()
    assert len(pending) == 2
    for doc in pending:
        assert doc.status == DocumentStatus.PENDING


@pytest.mark.asyncio
async def test_document_mark_processed(db_session: AsyncSession) -> None:
    """Marking a document as processed updates its status and content."""
    repo = DocumentRepository(db_session)

    doc = await repo.create(
        source=DocumentSource.WHO,
        external_id="who-sit-rep-001",
        status=DocumentStatus.PENDING,
    )
    await db_session.commit()

    await repo.mark_processed(doc.id, processed_content="Extracted text here", embedding_id="vec_abc123")
    await db_session.commit()

    updated = await repo.get_by_id(doc.id)
    assert updated.status == DocumentStatus.PROCESSED
    assert updated.processed_content == "Extracted text here"
    assert updated.embedding_id == "vec_abc123"


# ── Pathogen repository tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pathogen_create_and_retrieve(db_session: AsyncSession) -> None:
    """Create a pathogen and retrieve by species name."""
    repo = PathogenRepository(db_session)

    pathogen = await repo.create(
        species_name="SARS-CoV-2",
        common_name="COVID-19 virus",
        category=PathogenCategory.VIRUS,
        ncbi_taxonomy_id="2697049",
        who_priority=True,
    )
    await db_session.commit()

    retrieved = await repo.get_by_species_name("SARS-CoV-2")
    assert retrieved is not None
    assert retrieved.ncbi_taxonomy_id == "2697049"
    assert retrieved.who_priority is True


@pytest.mark.asyncio
async def test_pathogen_search_by_name(db_session: AsyncSession) -> None:
    """Partial name search returns matching pathogens."""
    repo = PathogenRepository(db_session)

    await repo.create(species_name="Influenza A H5N1", category=PathogenCategory.VIRUS)
    await repo.create(species_name="Influenza B", category=PathogenCategory.VIRUS)
    await repo.create(species_name="Vibrio cholerae", category=PathogenCategory.BACTERIUM)
    await db_session.commit()

    results = await repo.search_by_name("influenza")
    assert len(results) == 2
    names = [p.species_name for p in results]
    assert "Influenza A H5N1" in names
    assert "Influenza B" in names


@pytest.mark.asyncio
async def test_pathogen_who_priority_filter(db_session: AsyncSession) -> None:
    """Only WHO-priority pathogens are returned by get_who_priority()."""
    repo = PathogenRepository(db_session)

    await repo.create(species_name="SARS-CoV-2", category=PathogenCategory.VIRUS, who_priority=True)
    await repo.create(species_name="Rhinovirus", category=PathogenCategory.VIRUS, who_priority=False)
    await db_session.commit()

    priority = await repo.get_who_priority()
    assert len(priority) == 1
    assert priority[0].species_name == "SARS-CoV-2"
