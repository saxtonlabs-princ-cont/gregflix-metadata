from app.models import (
    ArtworkAsset,
    CanonicalMediaFile,
    CatalogRow,
    CatalogRowItem,
    EntityAlias,
    MediaEntity,
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
