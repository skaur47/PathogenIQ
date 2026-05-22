import uuid
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.models.outbreak import Outbreak, OutbreakStatus, RiskLevel
from app.db.session import AsyncSession
from app.repositories.base import BaseRepository


class OutbreakRepository(BaseRepository[Outbreak]):

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Outbreak)

    async def get_with_relations(self, outbreak_id: uuid.UUID) -> Outbreak | None:
        """
        Fetch an outbreak with its pathogen and location already loaded.

        Why selectinload?
          SQLAlchemy lazy-loads relationships by default: accessing
          outbreak.pathogen would trigger a new SQL query. In async code,
          that would require an extra `await`. selectinload tells SQLAlchemy
          to load the relations in a second query upfront, so they're available
          without a second await. This is the recommended approach for async.

          (joinedload would use a SQL JOIN, which works but can produce
          cartesian products with multiple list relationships.)
        """
        result = await self._session.execute(
            select(Outbreak)
            .where(Outbreak.id == outbreak_id)
            .options(
                selectinload(Outbreak.pathogen),
                selectinload(Outbreak.location),
                selectinload(Outbreak.evidence_scores),
            )
        )
        return result.scalar_one_or_none()

    async def get_active(self, limit: int = 50) -> Sequence[Outbreak]:
        """
        Return currently active outbreaks (suspected, confirmed, monitoring, escalating).
        This is the primary query for the main dashboard.
        """
        active_statuses = [
            OutbreakStatus.SUSPECTED,
            OutbreakStatus.CONFIRMED,
            OutbreakStatus.MONITORING,
            OutbreakStatus.ESCALATING,
        ]
        result = await self._session.execute(
            select(Outbreak)
            .where(Outbreak.status.in_(active_statuses))
            .options(
                selectinload(Outbreak.pathogen),
                selectinload(Outbreak.location),
            )
            .order_by(Outbreak.risk_score.desc().nulls_last())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_by_pathogen(
        self, pathogen_id: uuid.UUID, limit: int = 50
    ) -> Sequence[Outbreak]:
        """All outbreaks involving a specific pathogen, most recent first."""
        result = await self._session.execute(
            select(Outbreak)
            .where(Outbreak.pathogen_id == pathogen_id)
            .order_by(Outbreak.detected_at.desc().nulls_last())
            .limit(limit)
        )
        return result.scalars().all()

    async def get_by_risk_level(self, risk_level: RiskLevel) -> Sequence[Outbreak]:
        """Filter outbreaks by risk level. Used for alert generation."""
        result = await self._session.execute(
            select(Outbreak)
            .where(Outbreak.risk_level == risk_level)
            .order_by(Outbreak.detected_at.desc())
        )
        return result.scalars().all()

    async def get_critical_unalerted(self) -> Sequence[Outbreak]:
        """
        Find CRITICAL outbreaks that have no acknowledged alert.
        Used by the Alert Agent to trigger notifications.
        Requires a JOIN, so we use a subquery approach.
        """
        from app.db.models.evidence import Alert
        from sqlalchemy import exists

        has_ack_alert = exists().where(
            Alert.outbreak_id == Outbreak.id,
            Alert.acknowledged.is_(True),
        )
        result = await self._session.execute(
            select(Outbreak)
            .where(
                Outbreak.risk_level == RiskLevel.CRITICAL,
                ~has_ack_alert,
            )
        )
        return result.scalars().all()
