"""ORM-модели SQLAlchemy 2.x."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ApplicationStatus(str, enum.Enum):
    draft = "draft"
    new = "new"
    in_progress = "in_progress"
    done = "done"
    rejected = "rejected"


class Direction(str, enum.Enum):
    job = "job"
    psy = "psy"
    law = "law"
    other = "other"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    max_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    applications: Mapped[list[Application]] = relationship(back_populates="user")
    consultations: Mapped[list[Consultation]] = relationship(back_populates="user")

    @property
    def has_consent(self) -> bool:
        return self.consent_given_at is not None


class Application(Base):
    """Заявка на вступление."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    fio: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_svo_participant: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=20),
        default=ApplicationStatus.new,
        server_default=ApplicationStatus.new.value,
        nullable=False,
    )
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="applications")


class Consultation(Base):
    """Заявка на консультацию."""

    __tablename__ = "consultations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    direction: Mapped[Direction] = mapped_column(
        Enum(Direction, native_enum=False, length=10), nullable=False
    )
    fio: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    free_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[ApplicationStatus] = mapped_column(
        Enum(ApplicationStatus, native_enum=False, length=20),
        default=ApplicationStatus.new,
        server_default=ApplicationStatus.new.value,
        nullable=False,
    )
    is_repeat: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="consultations")


class Event(Base):
    """Аудит-лог действий."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, server_default=func.now())
