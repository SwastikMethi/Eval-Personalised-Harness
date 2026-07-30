from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid4().hex


class Base(DeclarativeBase):
    pass


class IdTimestampMixin:
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
