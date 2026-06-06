"""
ResearchRepository — read/write for research_articles and pathogen_research_summaries.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.db.models.research import ArticleCategory, PathogenResearchSummary, ResearchArticle
from app.db.session import AsyncSession


class ResearchRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Articles ──────────────────────────────────────────────────────────────

    async def upsert_article(
        self,
        pathogen_id: uuid.UUID,
        pmid: str,
        title: str,
        authors: str | None,
        published_date: str | None,
        category: ArticleCategory,
        source_url: str | None,
        abstract: str | None,
        article_summary: str | None,
    ) -> ResearchArticle:
        """
        Insert or update a research article record.
        Match on (pathogen_id, pmid) — updates summary when re-running the agent.
        """
        result = await self._session.execute(
            select(ResearchArticle).where(
                ResearchArticle.pathogen_id == pathogen_id,
                ResearchArticle.pmid == pmid,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.title = title
            existing.authors = authors
            existing.published_date = published_date
            existing.article_category = category
            existing.source_url = source_url
            existing.abstract = abstract
            existing.article_summary = article_summary
            return existing

        article = ResearchArticle(
            pathogen_id=pathogen_id,
            pmid=pmid,
            title=title,
            authors=authors,
            published_date=published_date,
            article_category=category,
            source_url=source_url,
            abstract=abstract,
            article_summary=article_summary,
        )
        self._session.add(article)
        return article

    async def get_articles_for_pathogen(
        self,
        pathogen_id: uuid.UUID,
    ) -> list[ResearchArticle]:
        result = await self._session.execute(
            select(ResearchArticle)
            .where(ResearchArticle.pathogen_id == pathogen_id)
            .order_by(ResearchArticle.article_category, ResearchArticle.published_date.desc().nulls_last())
        )
        return list(result.scalars().all())

    async def count_articles_for_pathogen(self, pathogen_id: uuid.UUID) -> int:
        from sqlalchemy import func
        result = await self._session.execute(
            select(func.count()).where(ResearchArticle.pathogen_id == pathogen_id)
        )
        return result.scalar_one()

    # ── Landscape summaries ───────────────────────────────────────────────────

    async def upsert_summary(
        self,
        pathogen_id: uuid.UUID,
        overall_summary: str | None,
        article_count: int,
        # Phase 4 v1 legacy fields
        infection_mechanism_summary: str | None = None,
        wet_lab_summary: str | None = None,
        clinical_trial_summary: str | None = None,
        vaccine_therapy_summary: str | None = None,
        # Phase 4 v2 specialized sub-agent fields
        molecular_biology_summary: str | None = None,
        experiments_summary: str | None = None,
        therapeutics_summary: str | None = None,
        clinical_epi_summary: str | None = None,
    ) -> PathogenResearchSummary:
        result = await self._session.execute(
            select(PathogenResearchSummary).where(
                PathogenResearchSummary.pathogen_id == pathogen_id
            )
        )
        existing = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if existing:
            existing.overall_summary = overall_summary
            existing.article_count = article_count
            existing.last_researched_at = now
            # Only overwrite legacy fields when explicitly provided
            if infection_mechanism_summary is not None:
                existing.infection_mechanism_summary = infection_mechanism_summary
            if wet_lab_summary is not None:
                existing.wet_lab_summary = wet_lab_summary
            if clinical_trial_summary is not None:
                existing.clinical_trial_summary = clinical_trial_summary
            if vaccine_therapy_summary is not None:
                existing.vaccine_therapy_summary = vaccine_therapy_summary
            # Always overwrite v2 fields (they come from current run)
            existing.molecular_biology_summary = molecular_biology_summary
            existing.experiments_summary = experiments_summary
            existing.therapeutics_summary = therapeutics_summary
            existing.clinical_epi_summary = clinical_epi_summary
            return existing

        summary = PathogenResearchSummary(
            pathogen_id=pathogen_id,
            overall_summary=overall_summary,
            article_count=article_count,
            last_researched_at=now,
            infection_mechanism_summary=infection_mechanism_summary,
            wet_lab_summary=wet_lab_summary,
            clinical_trial_summary=clinical_trial_summary,
            vaccine_therapy_summary=vaccine_therapy_summary,
            molecular_biology_summary=molecular_biology_summary,
            experiments_summary=experiments_summary,
            therapeutics_summary=therapeutics_summary,
            clinical_epi_summary=clinical_epi_summary,
        )
        self._session.add(summary)
        return summary

    async def get_summary_for_pathogen(
        self, pathogen_id: uuid.UUID
    ) -> PathogenResearchSummary | None:
        result = await self._session.execute(
            select(PathogenResearchSummary).where(
                PathogenResearchSummary.pathogen_id == pathogen_id
            )
        )
        return result.scalar_one_or_none()

    async def get_all_summaries(
        self, limit: int = 100, offset: int = 0
    ) -> list[PathogenResearchSummary]:
        result = await self._session.execute(
            select(PathogenResearchSummary)
            .order_by(PathogenResearchSummary.last_researched_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
