from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class MediaItem(Base):
    __tablename__ = "media_items"
    __table_args__ = (
        UniqueConstraint(
            "external_provider",
            "external_provider_id",
            "media_shape",
            name="uq_media_items_provider_shape",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_shape: Mapped[str] = mapped_column(String(32), nullable=False)
    library_category: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(512))
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    release_year: Mapped[int | None] = mapped_column(Integer)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("media_items.id"))
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    external_provider: Mapped[str | None] = mapped_column(String(64))
    external_provider_id: Mapped[str | None] = mapped_column(String(128))
    external_imdb_id: Mapped[str | None] = mapped_column(String(64))
    metadata_fetched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped["MediaItem | None"] = relationship(remote_side=[id])
    files: Mapped[list["MediaFile"]] = relationship(back_populates="media_item")
    images: Mapped[list["MediaImage"]] = relationship(back_populates="media_item")


class MediaFile(Base):
    __tablename__ = "media_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_items.id"), nullable=False)
    original_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sanitized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    media_item: Mapped[MediaItem] = relationship(back_populates="files")


class MediaImage(Base):
    __tablename__ = "media_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    media_item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("media_items.id"), nullable=False)
    image_type: Mapped[str] = mapped_column(String(32), nullable=False)
    absolute_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    source_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    source_provider_id: Mapped[str | None] = mapped_column(String(128))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    media_item: Mapped[MediaItem] = relationship(back_populates="images")


class MetadataJob(Base):
    __tablename__ = "metadata_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, default="metadata_ingest", server_default="metadata_ingest")
    requester: Mapped[str] = mapped_column(String(128), nullable=False, default="scanner", server_default="scanner")
    lock_key: Mapped[str] = mapped_column(String(2048), nullable=False)
    folder_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    library_name: Mapped[str] = mapped_column(String(255), nullable=False)
    library_category: Mapped[str] = mapped_column(String(32), nullable=False)
    media_shape: Mapped[str | None] = mapped_column(String(32))
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    error_stage: Mapped[str | None] = mapped_column(String(128))
    error_reason: Mapped[str | None] = mapped_column(Text)
    stale_detected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class MediaEntity(Base):
    __tablename__ = "media_entity"
    __table_args__ = (
        Index("ix_media_entity_parent_id", "parent_id"),
        Index("ix_media_entity_type", "entity_type"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"))
    library_category: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    sort_title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(512))
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    release_year: Mapped[int | None] = mapped_column(Integer)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    metadata_fetched: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    parent: Mapped["MediaEntity | None"] = relationship(remote_side=[id])
    files: Mapped[list["CanonicalMediaFile"]] = relationship(back_populates="entity")
    artwork: Mapped[list["ArtworkAsset"]] = relationship(back_populates="entity")
    provider_identities: Mapped[list["ProviderIdentity"]] = relationship(back_populates="entity")
    aliases: Mapped[list["EntityAlias"]] = relationship(back_populates="entity")


class ProviderIdentity(Base):
    __tablename__ = "provider_identity"
    __table_args__ = (
        UniqueConstraint("provider_name", "provider_media_type", "provider_id", name="uq_provider_identity"),
        Index("ix_provider_identity_entity_id", "entity_id"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    external_url: Mapped[str | None] = mapped_column(String(2048))
    primary_identity: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped[MediaEntity] = relationship(back_populates="provider_identities")


class EntityAlias(Base):
    __tablename__ = "entity_alias"
    __table_args__ = (
        UniqueConstraint("entity_id", "normalized_alias", "source", name="uq_entity_alias"),
        Index("ix_entity_alias_normalized_alias", "normalized_alias"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False)
    locale: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    entity: Mapped[MediaEntity] = relationship(back_populates="aliases")


class CanonicalMediaFile(Base):
    __tablename__ = "media_file"
    __table_args__ = (
        Index("ix_media_file_entity_id", "entity_id"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), nullable=False)
    original_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    original_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    sanitized_name: Mapped[str] = mapped_column(String(512), nullable=False)
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    season_number: Mapped[int | None] = mapped_column(Integer)
    episode_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped[MediaEntity] = relationship(back_populates="files")


class ArtworkAsset(Base):
    __tablename__ = "artwork_asset"
    __table_args__ = (
        Index("ix_artwork_asset_entity_id", "entity_id"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), nullable=False)
    artwork_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_provider_id: Mapped[str | None] = mapped_column(String(128))
    original_path: Mapped[str | None] = mapped_column(String(2048))
    stored_path: Mapped[str] = mapped_column(String(2048), nullable=False, unique=True)
    preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    fallback_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    entity: Mapped[MediaEntity] = relationship(back_populates="artwork")


class MetadataEvidence(Base):
    __tablename__ = "metadata_evidence"
    __table_args__ = (
        Index("ix_metadata_evidence_entity_id", "entity_id"),
        Index("ix_metadata_evidence_job_id", "metadata_job_id"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"))
    metadata_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata_jobs.id"))
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class MetadataIssue(Base):
    __tablename__ = "metadata_issue"
    __table_args__ = (
        Index("ix_metadata_issue_entity_id", "entity_id"),
        Index("ix_metadata_issue_status", "status"),
        Index("ix_metadata_issue_job_id", "metadata_job_id"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"))
    metadata_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata_jobs.id"))
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open", server_default="open")
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    folder_path: Mapped[str | None] = mapped_column(String(2048))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProviderMatchCandidate(Base):
    __tablename__ = "provider_match_candidate"
    __table_args__ = (
        UniqueConstraint(
            "metadata_job_id",
            "provider_name",
            "provider_media_type",
            "provider_id",
            name="uq_provider_match_candidate_job_provider",
        ),
        Index("ix_provider_match_candidate_job_id", "metadata_job_id"),
        Index("ix_provider_match_candidate_score", "confidence_score"),
        {"schema": "metadata"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metadata_job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata_jobs.id"), nullable=False)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_media_type: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    original_title: Mapped[str | None] = mapped_column(String(512))
    release_date: Mapped[date | None] = mapped_column(Date)
    release_year: Mapped[int | None] = mapped_column(Integer)
    popularity: Mapped[float | None] = mapped_column(Float)
    provider_rank: Mapped[int | None] = mapped_column(Integer)
    raw_score_components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class SearchDocument(Base):
    __tablename__ = "search_document"
    __table_args__ = (
        Index("ix_search_document_visible_title", "entity_type", "library_category", "release_year"),
        {"schema": "catalog"},
    )

    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    display_title: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_title: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    aliases_text: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    release_year: Mapped[int | None] = mapped_column(Integer)
    library_category: Mapped[str | None] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text)
    searchable_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CatalogRow(Base):
    __tablename__ = "catalog_row"
    __table_args__ = (
        Index("ix_catalog_row_visible_sort", "sort_order", "title"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    row_key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CatalogRowItem(Base):
    __tablename__ = "catalog_row_item"
    __table_args__ = (
        UniqueConstraint("catalog_row_id", "entity_id", name="uq_catalog_row_item"),
        Index("ix_catalog_row_item_row_visible_sort", "catalog_row_id", "sort_order"),
        Index("ix_catalog_row_item_entity_id", "entity_id"),
        {"schema": "catalog"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalog_row_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("catalog.catalog_row.id"), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("metadata.media_entity.id"), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
