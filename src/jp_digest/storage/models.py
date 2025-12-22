from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ContentItem(Base):
    """
    Normalized Reddit unit: post or comment.
    """

    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_content_source_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)  # reddit
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # post|comment

    url: Mapped[str] = mapped_column(Text, nullable=False)
    subreddit: Mapped[str] = mapped_column(String(64), nullable=False)
    author: Mapped[str | None] = mapped_column(String(64), nullable=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    raw_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_comments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_utc: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    experiences: Mapped[list["Experience"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
    )


class Experience(Base):
    """
    Extracted experience from content.
    """

    __tablename__ = "experiences"
    __table_args__ = (
        UniqueConstraint("content_item_id", "summary", name="uq_exp_content_summary"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.id"), index=True, nullable=False
    )

    polarity: Mapped[str] = mapped_column(String(16), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    place_mentions: Mapped[str] = mapped_column(Text, nullable=False, default="")

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    content_item: Mapped["ContentItem"] = relationship(back_populates="experiences")


class Poi(Base):
    """
    Canonical grounded place. For Phase 1 we use Nominatim.
    """

    __tablename__ = "pois"

    poi_id: Mapped[str] = mapped_column(String(160), primary_key=True)  # nominatim:...
    provider: Mapped[str] = mapped_column(String(32), nullable=False)  # nominatim
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)

    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class ExperiencePoi(Base):
    """
    Links an experience mention -> grounded POI.
    """

    __tablename__ = "experience_pois"
    __table_args__ = (
        UniqueConstraint(
            "experience_id", "poi_id", "mention_text", name="uq_exp_poi_mention"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experience_id: Mapped[int] = mapped_column(
        ForeignKey("experiences.id"), index=True, nullable=False
    )
    poi_id: Mapped[str] = mapped_column(
        ForeignKey("pois.poi_id"), index=True, nullable=False
    )

    mention_text: Mapped[str] = mapped_column(String(256), nullable=False)
    link_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.7)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class BaseAssignment(Base):
    """
    Assign a POI to a trip base with distance.
    """

    __tablename__ = "base_assignments"
    __table_args__ = (UniqueConstraint("base_name", "poi_id", name="uq_base_poi"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    poi_id: Mapped[str] = mapped_column(
        ForeignKey("pois.poi_id"), index=True, nullable=False
    )
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)

    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


Index("ix_content_items_subreddit", ContentItem.subreddit)
Index("ix_content_items_created_utc", ContentItem.created_utc)
