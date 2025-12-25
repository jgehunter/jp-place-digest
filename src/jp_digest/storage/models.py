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

    mentions: Mapped[list["ExperienceMention"]] = relationship(
        back_populates="content_item",
        cascade="all, delete-orphan",
    )


class ExperienceMention(Base):
    """
    Extracted experience mention, base-aware and entity-focused.
    """

    __tablename__ = "experience_mentions"
    __table_args__ = (
        UniqueConstraint(
            "content_item_id",
            "entity_name",
            "experience_text",
            name="uq_mention_content_entity_text",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_item_id: Mapped[int] = mapped_column(
        ForeignKey("content_items.id"), index=True, nullable=False
    )

    entity_name: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    experience_text: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    location_hint: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )

    evidence_spans: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_or_caution: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonicalization_hint: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_base: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    assigned_base_confidence: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.5
    )

    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    content_item: Mapped["ContentItem"] = relationship(back_populates="mentions")


class ExperienceCluster(Base):
    """
    Clustered experience entity for ranking and digest.
    """

    __tablename__ = "experience_clusters"
    __table_args__ = (
        UniqueConstraint(
            "base_name",
            "normalized_key",
            "entity_type",
            name="uq_cluster_base_key_type",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_name: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(256), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    normalized_key: Mapped[str] = mapped_column(String(256), nullable=False)

    support_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    engagement_sum: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recency_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    mentions: Mapped[list["ExperienceClusterMention"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan",
    )


class ExperienceClusterMention(Base):
    """
    Join table for cluster <-> mention.
    """

    __tablename__ = "experience_cluster_mentions"
    __table_args__ = (
        UniqueConstraint("cluster_id", "mention_id", name="uq_cluster_mention"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("experience_clusters.id"), index=True, nullable=False
    )
    mention_id: Mapped[int] = mapped_column(
        ForeignKey("experience_mentions.id"), index=True, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    cluster: Mapped["ExperienceCluster"] = relationship(back_populates="mentions")
    mention: Mapped["ExperienceMention"] = relationship()


Index("ix_content_items_subreddit", ContentItem.subreddit)
Index("ix_content_items_created_utc", ContentItem.created_utc)
