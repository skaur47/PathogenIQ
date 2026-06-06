"""
HypothesisRepository — read/write for pathogen_hypotheses.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.models.hypothesis import PathogenHypothesis
from app.db.session import AsyncSession


class HypothesisRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_hypothesis(
        self,
        pathogen_id: uuid.UUID,
        research_gap: str | None,
        proposed_strategy: str | None,
        wetlab_experiments: str | None,
        clinical_approaches: str | None,
        rationale: str | None,
        overall_recommendation: str | None,
    ) -> PathogenHypothesis:
        result = await self._session.execute(
            select(PathogenHypothesis).where(
                PathogenHypothesis.pathogen_id == pathogen_id
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            existing.research_gap = research_gap
            existing.proposed_strategy = proposed_strategy
            existing.wetlab_experiments = wetlab_experiments
            existing.clinical_approaches = clinical_approaches
            existing.rationale = rationale
            existing.overall_recommendation = overall_recommendation
            existing.last_synthesized_at = now
            return existing

        hyp = PathogenHypothesis(
            pathogen_id=pathogen_id,
            research_gap=research_gap,
            proposed_strategy=proposed_strategy,
            wetlab_experiments=wetlab_experiments,
            clinical_approaches=clinical_approaches,
            rationale=rationale,
            overall_recommendation=overall_recommendation,
            last_synthesized_at=now,
        )
        self._session.add(hyp)
        return hyp

    async def get_hypothesis_for_pathogen(
        self, pathogen_id: uuid.UUID
    ) -> PathogenHypothesis | None:
        result = await self._session.execute(
            select(PathogenHypothesis).where(
                PathogenHypothesis.pathogen_id == pathogen_id
            )
        )
        return result.scalar_one_or_none()

    async def get_all_hypotheses(
        self, limit: int = 100, offset: int = 0
    ) -> list[PathogenHypothesis]:
        result = await self._session.execute(
            select(PathogenHypothesis)
            .order_by(PathogenHypothesis.last_synthesized_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
