import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 declarative base for all PathogenIQ models.

    Why DeclarativeBase instead of the old declarative_base()?
      - DeclarativeBase is the SQLAlchemy 2.0 style (released 2023).
      - It enables full Python typing: `Mapped[str]` instead of `Column(String)`.
      - Mypy and IDEs understand the types — you get autocomplete on model fields.
      - The old `declarative_base()` still works but is legacy style.

    All models that inherit from Base are automatically registered in
    Base.metadata, which Alembic reads to generate migrations.
    """
    pass


class TimestampMixin:
    """
    Adds created_at and updated_at to any model.

    Why a mixin instead of putting these on Base?
      - Not every table needs timestamps (e.g., pure join tables).
      - Explicit inheritance makes it visible which models track time.

    server_default=func.now(): the database sets the default, not Python.
    This is safer — it's immune to clock drift between app servers.

    onupdate=func.now(): PostgreSQL updates this column automatically
    whenever the row changes. No need to remember to set it in code.
    """
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UUIDMixin:
    """
    Adds a UUID primary key to any model.

    Why UUID instead of auto-incrementing integers?
      1. Security: integer IDs leak record counts (e.g., /outbreaks/1 tells you
         there is only 1 outbreak). UUIDs do not.
      2. Distributed systems: UUIDs can be generated client-side before
         inserting into the DB, enabling optimistic inserts without a round-trip.
      3. Merging data: if you ever shard the DB or merge datasets, integer IDs
         collide; UUIDs don't.

    server_default=func.gen_random_uuid(): PostgreSQL generates the UUID,
    which is slightly faster than generating it in Python and avoids
    importing uuid in every model.
    """
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        nullable=False,
    )
