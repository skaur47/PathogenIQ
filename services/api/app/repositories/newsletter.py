import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.newsletter import NewsletterSubscriber


class NewsletterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def subscribe(self, name: str, email: str) -> NewsletterSubscriber:
        existing = await self.get_by_email(email)
        if existing:
            # Re-activate if they had previously unsubscribed
            existing.name = name
            existing.is_active = True
            existing.unsubscribed_at = None
            return existing
        subscriber = NewsletterSubscriber(name=name, email=email)
        self.session.add(subscriber)
        await self.session.flush()
        return subscriber

    async def unsubscribe_by_token(self, token: uuid.UUID) -> bool:
        result = await self.session.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.unsubscribe_token == token)
        )
        sub = result.scalar_one_or_none()
        if not sub or not sub.is_active:
            return False
        sub.is_active = False
        sub.unsubscribed_at = datetime.now(timezone.utc)
        return True

    async def get_by_email(self, email: str) -> NewsletterSubscriber | None:
        result = await self.session.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.email == email)
        )
        return result.scalar_one_or_none()

    async def get_active_subscribers(self) -> list[NewsletterSubscriber]:
        result = await self.session.execute(
            select(NewsletterSubscriber).where(NewsletterSubscriber.is_active == True)
        )
        return list(result.scalars().all())
