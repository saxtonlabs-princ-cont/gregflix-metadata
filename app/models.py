from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
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
    folder_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    library_name: Mapped[str] = mapped_column(String(255), nullable=False)
    library_category: Mapped[str] = mapped_column(String(32), nullable=False)
    media_shape: Mapped[str | None] = mapped_column(String(32))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
