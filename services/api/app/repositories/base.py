"""
Generic async repository pattern for SQLAlchemy 2.0.

WHY the Repository Pattern?
───────────────────────────
Without repositories, database logic leaks everywhere:

  # In an endpoint — BAD
  @router.get("/outbreaks/{id}")
  async def get_outbreak(id: UUID, session: AsyncSession = Depends(get_session)):
      result = await session.execute(select(Outbreak).where(Outbreak.id == id))
      outbreak = result.scalar_one_or_none()
      ...

Problems with this:
  1. If you change the ORM query, you must find and update every endpoint.
  2. You can't easily test the query logic without an HTTP client.
  3. The endpoint function knows too much about the database layer.

With repositories:
  # In the endpoint — GOOD
  outbreak = await outbreak_repo.get_by_id(id)

  # In the repository — isolated, testable
  async def get_by_id(self, id: UUID) -> Outbreak | None:
      result = await self._session.execute(select(Outbreak).where(Outbreak.id == id))
      return result.scalar_one_or_none()

Benefits:
  - One place to change query logic
  - Repository can be mocked in unit tests without a real DB
  - Business logic (endpoints) is decoupled from persistence logic

HOW Generics Work Here:
───────────────────────
  BaseRepository[T] is a generic class where T is a SQLAlchemy model.
  When you write `class DocumentRepository(BaseRepository[Document])`,
  Python substitutes Document for every T in the base class.
  This gives you type-safe CRUD methods without duplicating code.
"""

import uuid
from typing import Generic, Sequence, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseRepository(Generic[ModelType]):
    """
    Generic CRUD repository.

    Usage:
        class DocumentRepository(BaseRepository[Document]):
            def __init__(self, session: AsyncSession):
                super().__init__(session, Document)

            async def get_by_external_id(self, source: str, external_id: str):
                result = await self._session.execute(
                    select(Document).where(
                        Document.source == source,
                        Document.external_id == external_id,
                    )
                )
                return result.scalar_one_or_none()
    """

    def __init__(self, session: AsyncSession, model: Type[ModelType]) -> None:
        self._session = session
        self._model = model

    async def get_by_id(self, id: uuid.UUID) -> ModelType | None:
        """Fetch a single record by primary key. Returns None if not found."""
        result = await self._session.execute(
            select(self._model).where(self._model.id == id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def get_all(self, limit: int = 100, offset: int = 0) -> Sequence[ModelType]:
        """
        Fetch a page of records.

        Why paginate? Never do SELECT * without LIMIT in production.
        A table with 10 million documents would transfer gigabytes of data
        and likely crash your app. Always paginate.

        limit: max records to return (default 100, never more than 1000)
        offset: how many records to skip (for page 2: offset=100)
        """
        limit = min(limit, 1000)  # hard cap — prevent runaway queries
        result = await self._session.execute(
            select(self._model).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """Return total number of records. Used for pagination metadata."""
        from sqlalchemy import func
        result = await self._session.execute(
            select(func.count()).select_from(self._model)
        )
        return result.scalar_one()

    async def create(self, **kwargs) -> ModelType:
        """
        Create and persist a new record.

        Why flush instead of commit?
          flush() sends the INSERT to the database (so the DB assigns the
          generated UUID) but doesn't commit the transaction. This lets the
          caller decide whether to commit or rollback. The HTTP session
          dependency (get_session) will commit at the end of the request
          or rollback on exception.

          If we committed here, a later failure in the same request would
          leave orphaned data in the DB.
        """
        instance = self._model(**kwargs)
        self._session.add(instance)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def update(self, instance: ModelType, **kwargs) -> ModelType:
        """Update fields on an existing record."""
        for key, value in kwargs.items():
            if hasattr(instance, key):
                setattr(instance, key, value)
        self._session.add(instance)
        await self._session.flush()
        await self._session.refresh(instance)
        return instance

    async def delete(self, instance: ModelType) -> None:
        """
        Soft note: consider soft deletes (is_deleted flag) over hard deletes
        for any scientifically significant record. You might need the audit trail.
        For now, this is a hard delete.
        """
        await self._session.delete(instance)
        await self._session.flush()

    async def save(self) -> None:
        """Explicitly commit the current transaction."""
        await self._session.commit()
