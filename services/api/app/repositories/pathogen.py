from typing import Sequence

from sqlalchemy import select

from app.db.models.pathogen import Pathogen
from app.db.session import AsyncSession
from app.repositories.base import BaseRepository


class PathogenRepository(BaseRepository[Pathogen]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Pathogen)

    async def get_by_species_name(self, species_name: str) -> Pathogen | None:
        """Exact match on species name. Used to avoid duplicate pathogen records."""
        result = await self._session.execute(
            select(Pathogen).where(Pathogen.species_name == species_name)
        )
        return result.scalar_one_or_none()

    async def get_by_ncbi_taxonomy_id(self, taxonomy_id: str) -> Pathogen | None:
        """
        Look up by NCBI Taxonomy ID — the gold-standard unambiguous identifier.
        Prefer this over species name when available. NCBI ID 2697049 = SARS-CoV-2
        regardless of how the text refers to it.
        """
        result = await self._session.execute(
            select(Pathogen).where(Pathogen.ncbi_taxonomy_id == taxonomy_id)
        )
        return result.scalar_one_or_none()

    async def get_who_priority(self) -> Sequence[Pathogen]:
        """Return all pathogens flagged as WHO priority pathogens."""
        result = await self._session.execute(
            select(Pathogen)
            .where(Pathogen.who_priority.is_(True))
            .order_by(Pathogen.species_name)
        )
        return result.scalars().all()

    async def get_all(self, limit: int = 1000, offset: int = 0) -> Sequence[Pathogen]:
        result = await self._session.execute(
            select(Pathogen).order_by(Pathogen.species_name).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def search_by_name(self, query: str, limit: int = 20) -> Sequence[Pathogen]:
        """
        Case-insensitive partial match on species or common name.
        Full-text semantic search lives in Qdrant (Phase 3).
        This is the simple SQL fallback.
        """
        q = f"%{query.lower()}%"
        result = await self._session.execute(
            select(Pathogen)
            .where(
                Pathogen.species_name.ilike(q) | Pathogen.common_name.ilike(q)
            )
            .limit(limit)
        )
        return result.scalars().all()
