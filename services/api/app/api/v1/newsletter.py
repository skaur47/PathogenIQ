import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.db.session import AsyncSessionLocal
from app.repositories.newsletter import NewsletterRepository

router = APIRouter(prefix="/newsletter", tags=["newsletter"])


class SubscribeRequest(BaseModel):
    name: str
    email: str


class UnsubscribeRequest(BaseModel):
    token: uuid.UUID


class MessageResponse(BaseModel):
    message: str


@router.post("/subscribe", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def subscribe(body: SubscribeRequest) -> MessageResponse:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            repo = NewsletterRepository(session)
            await repo.subscribe(name=body.name.strip(), email=body.email.lower())
    return MessageResponse(message="Subscribed successfully. You will receive your first digest tomorrow.")


@router.post("/unsubscribe", response_model=MessageResponse)
async def unsubscribe(body: UnsubscribeRequest) -> MessageResponse:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            repo = NewsletterRepository(session)
            ok = await repo.unsubscribe_by_token(body.token)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found or already unsubscribed.")
    return MessageResponse(message="You have been unsubscribed successfully.")
