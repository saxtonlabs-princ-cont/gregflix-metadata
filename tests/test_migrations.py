from pathlib import Path

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from app.migrations import SchemaVersionError, alembic_config, assert_database_at_head, migration_head


def test_alembic_has_single_deterministic_head():
    script = ScriptDirectory.from_config(alembic_config())

    assert script.get_heads() == [migration_head()]
    assert migration_head() == "20260510_0007"


def test_initial_migration_uses_explicit_metadata_ddl_only():
    migration_path = Path("alembic/versions/20260501_0001_initial.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "op.execute" in content
    assert "create_table(" not in content
    assert "create table media_items" in content
    assert "create table media_files" in content
    assert "create table media_images" in content
    assert "create table metadata_jobs" in content
    assert "create table auth" not in content
    assert "create table users" not in content


def test_canonical_migration_uses_metadata_schema_without_auth_objects():
    migration_path = Path("alembic/versions/20260503_0002_canonical_metadata_schema.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "create schema if not exists metadata" in content
    assert "create schema if not exists catalog" in content
    assert "create table metadata.media_entity" in content
    assert "create table metadata.media_file" in content
    assert "create table metadata.artwork_asset" in content
    assert "create table metadata.provider_identity" in content
    assert "create table metadata.entity_alias" in content
    assert "create table metadata.metadata_evidence" in content
    assert "create table metadata.metadata_issue" in content
    assert "insert into metadata.media_entity" in content
    assert "insert into metadata.media_file" in content
    assert "insert into metadata.artwork_asset" in content
    assert "create table metadata.auth" not in content
    assert "create table metadata.users" not in content


def test_durable_queue_migration_adds_job_claiming_fields():
    migration_path = Path("alembic/versions/20260503_0003_metadata_jobs_durable_queue.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "add column job_type" in content
    assert "add column requester" in content
    assert "add column lock_key" in content
    assert "add column retry_count" in content
    assert "add column error_stage" in content
    assert "add column error_reason" in content
    assert "add column claimed_at" in content
    assert "uq_metadata_jobs_active_lock_key" in content
    assert "where status in ('pending', 'running')" in content
    assert "status = 'pending'" in content


def test_provider_match_candidate_migration_adds_scored_candidates():
    migration_path = Path("alembic/versions/20260503_0004_provider_match_candidates.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "create table metadata.provider_match_candidate" in content
    assert "provider_name" in content
    assert "provider_id" in content
    assert "provider_media_type" in content
    assert "raw_score_components jsonb" in content
    assert "confidence_score double precision" in content
    assert "selected boolean" in content


def test_search_document_migration_adds_postgres_search_substrate():
    migration_path = Path("alembic/versions/20260503_0005_search_documents.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "create extension if not exists pg_trgm" in content
    assert "create extension if not exists unaccent" in content
    assert "create table catalog.search_document" in content
    assert "search_vector tsvector" in content
    assert "using gin(search_vector)" in content
    assert "gin(normalized_title gin_trgm_ops)" in content
    assert "gin(aliases_text gin_trgm_ops)" in content
    assert "where visible = true" in content


def test_catalog_projection_migration_adds_views_and_rows():
    migration_path = Path("alembic/versions/20260503_0006_catalog_projections.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "create schema if not exists catalog" in content
    assert "create table catalog.catalog_row" in content
    assert "create table catalog.catalog_row_item" in content
    assert "create view catalog.catalog_card_view" in content
    assert "create view catalog.media_detail_view" in content
    assert "create view catalog.series_episode_view" in content
    assert "poster_artwork_path" in content
    assert "backdrop_artwork_path" in content
    assert "catalog_ready" in content
    assert "playable_available" in content
    assert "provider_identity_summary" in content
    assert "playable_file_available" in content


def test_media_files_size_bytes_bigint_migration_updates_legacy_table():
    migration_path = Path("alembic/versions/20260510_0007_media_files_size_bytes_bigint.py")
    content = migration_path.read_text(encoding="utf-8").lower()

    assert "alter table media_files alter column size_bytes type bigint" in content
    assert "drop table" not in content


def test_schema_check_rejects_empty_database():
    engine = create_engine("sqlite:///:memory:")
    with engine.connect() as connection:
        with pytest.raises(SchemaVersionError, match="not initialized"):
            assert_database_at_head(connection, "20260501_0001")
