"""Persistence models for the manual-input vertical slice."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ProfileModel(Base):
    __tablename__ = "profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    data_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="synthetic")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observations: Mapped[list["ObservationModel"]] = relationship(back_populates="profile")
    check_ins: Mapped[list["CheckInModel"]] = relationship(back_populates="profile")


class ObservationModel(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    profile: Mapped[ProfileModel] = relationship(back_populates="observations")


class CheckInModel(Base):
    __tablename__ = "check_ins"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("profiles.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    corrected_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    profile: Mapped[ProfileModel] = relationship(back_populates="check_ins")
    symptom_facts: Mapped[list["SymptomFactModel"]] = relationship(
        back_populates="check_in", cascade="all, delete-orphan"
    )


class SymptomFactModel(Base):
    __tablename__ = "symptom_facts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    check_in_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("check_ins.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    temporal_context: Mapped[str | None] = mapped_column(String(256), nullable=True)
    evidence: Mapped[str] = mapped_column(String(500), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_in: Mapped[CheckInModel] = relationship(back_populates="symptom_facts")
