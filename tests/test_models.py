import uuid

from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import Session

from app.models import (
    ArtworkAsset,
    CanonicalMediaFile,
    CatalogRow,
    CatalogRowItem,
    EntityAlias,
    MediaEntity,
    MediaFile,
    MediaItem,
    MetadataEvidence,
    MetadataIssue,
    MetadataJob,
    ProviderMatchCandidate,
    ProviderIdentity,
    SearchDocument,
)


def test_canonical_models_use_metadata_schema():
    models = [
        MediaEntity,
        CanonicalMediaFile,
        ArtworkAsset,
        ProviderIdentity,
        EntityAlias,
        MetadataEvidence,
        MetadataIssue,
        ProviderMatchCandidate,
    ]

    assert {model.__table__.schema for model in models} == {"metadata"}


def test_media_file_points_to_media_entity():
    assert CanonicalMediaFile.__table__.c.entity_id.foreign_keys
    foreign_key = next(iter(CanonicalMediaFile.__table__.c.entity_id.foreign_keys))

    assert foreign_key.target_fullname == "metadata.media_entity.id"


def test_legacy_media_file_size_bytes_uses_bigint():
    size_column = MediaFile.__table__.c.size_bytes

    assert isinstance(size_column.type, BigInteger)


def test_legacy_media_file_persists_large_size_bytes():
    large_size = 71_690_500_463
    engine = create_engine("sqlite:///:memory:")
    MediaItem.__table__.create(engine)
    MediaFile.__table__.create(engine)

    with Session(engine) as session:
        media_item = MediaItem(
            id=uuid.uuid4(),
            media_shape="film",
            library_category="movies",
            title="Large File",
            sort_title="Large File",
        )
        media_file = MediaFile(
            id=uuid.uuid4(),
            media_item=media_item,
            original_path="/media/Large File.mkv",
            original_filename="Large File.mkv",
            sanitized_name="Large File.mkv",
            extension=".mkv",
            size_bytes=large_size,
        )
        session.add(media_file)
        session.commit()

    with Session(engine) as session:
        stored = session.query(MediaFile).one()

    assert large_size > 2_147_483_647
    assert stored.size_bytes == large_size


def test_metadata_jobs_has_durable_queue_columns():
    columns = MetadataJob.__table__.c

    assert "job_type" in columns
    assert "requester" in columns
    assert "lock_key" in columns
    assert "retry_count" in columns
    assert "error_stage" in columns
    assert "error_reason" in columns
    assert "claimed_at" in columns
    assert "stale_detected_at" in columns


def test_provider_match_candidate_model_has_score_columns():
    columns = ProviderMatchCandidate.__table__.c

    assert ProviderMatchCandidate.__table__.schema == "metadata"
    assert "provider_name" in columns
    assert "provider_id" in columns
    assert "provider_media_type" in columns
    assert "raw_score_components" in columns
    assert "confidence_score" in columns
    assert "selected" in columns


def test_search_document_model_uses_catalog_schema():
    columns = SearchDocument.__table__.c

    assert SearchDocument.__table__.schema == "catalog"
    assert "entity_id" in columns
    assert "normalized_title" in columns
    assert "aliases" in columns
    assert "searchable_text" in columns
    assert "search_vector" in columns
    assert "visible" in columns


def test_catalog_row_models_use_catalog_schema():
    assert CatalogRow.__table__.schema == "catalog"
    assert CatalogRowItem.__table__.schema == "catalog"
    assert "row_key" in CatalogRow.__table__.c
    assert "catalog_row_id" in CatalogRowItem.__table__.c
    assert "entity_id" in CatalogRowItem.__table__.c
