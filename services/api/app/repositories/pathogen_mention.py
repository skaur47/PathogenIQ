"""
PathogenMentionRepository — persistence layer for Sentinel Agent outputs.

The key query here is get_aggregate_counts(), which collapses per-document
mention records into a single leaderboard: pathogen → total mentions across
all documents in the database. This is the "frequency table" the user sees.
"""

import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.db.models.pathogen_mention import PathogenMention
from app.db.session import AsyncSession
from app.repositories.base import BaseRepository


class PathogenMentionRepository(BaseRepository[PathogenMention]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, PathogenMention)

    async def upsert_mention(
        self,
        document_id: uuid.UUID,
        pathogen_name: str,
        mention_count: int,
        source_spans: list[str] | None = None,
    ) -> None:
        """
        Insert or update a (document, pathogen) mention record.

        Uses ON CONFLICT DO UPDATE so re-running the Sentinel on a document
        that was already processed updates the count rather than erroring.
        The unique constraint on (document_id, pathogen_name) is the conflict
        target.
        """
        stmt = (
            insert(PathogenMention)
            .values(
                document_id=document_id,
                pathogen_name=pathogen_name,
                mention_count=mention_count,
                source_spans=source_spans,
            )
            .on_conflict_do_update(
                index_elements=["document_id", "pathogen_name"],
                set_={
                    "mention_count": mention_count,
                    "source_spans": source_spans,
                },
            )
        )
        await self._session.execute(stmt)

    async def get_aggregate_counts(self) -> list[dict]:
        """
        Return total mention counts per pathogen across all documents.

        Groups by pathogen_name and sums mention_count, ordered by frequency
        descending. Also returns how many distinct documents mention each pathogen.

        Example result:
            [
                {"pathogen_name": "SARS-CoV-2", "total_mentions": 17, "document_count": 5},
                {"pathogen_name": "Influenza A H5N1", "total_mentions": 9, "document_count": 4},
            ]
        """
        result = await self._session.execute(
            select(
                PathogenMention.pathogen_name,
                func.sum(PathogenMention.mention_count).label("total_mentions"),
                func.count(PathogenMention.document_id).label("document_count"),
            )
            .group_by(PathogenMention.pathogen_name)
            .order_by(func.sum(PathogenMention.mention_count).desc())
        )
        return [
            {
                "pathogen_name": row.pathogen_name,
                "total_mentions": int(row.total_mentions),
                "document_count": int(row.document_count),
            }
            for row in result.all()
        ]

    async def get_for_document(self, document_id: uuid.UUID) -> Sequence[PathogenMention]:
        """Return all mention records for a single document."""
        result = await self._session.execute(
            select(PathogenMention).where(
                PathogenMention.document_id == document_id
            )
        )
        return result.scalars().all()
