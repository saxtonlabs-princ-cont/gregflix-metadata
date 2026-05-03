# GregFlix Metadata Service

GregFlix Metadata Service is a FastAPI-based metadata ingester for a private homelab media system. It scans configured library roots, queues unprocessed folders, fetches metadata and images from TMDB, writes canonical records to Postgres, and writes marker files back into media folders.

## What It Does

- Loads YAML configuration from `GREGFLIX_METADATA_CONFIG` or `./config.yaml`
- Scans enabled library roots on startup and via API
- Detects unprocessed top-level media folders
- Parses basic movie and episode naming patterns
- Looks up metadata from TMDB
- Downloads posters, backdrops, and episode stills when available
- Upserts media items, files, images, and job records into Postgres
- Writes success or failure marker files into media folders
- Runs exactly one metadata job at a time using `metadata_jobs` as a durable Postgres queue
- Owns its metadata database schema through explicit migrations

## What It Does Not Do

- Rename, move, delete, or rewrite media files
- Watch the filesystem for changes
- Retry failed folders automatically
- Provide playback, catalog, recommendation, or frontend features
- Use Redis, Celery, RQ, Kafka, or another external queue system

## Configuration

Set:

- `GREGFLIX_METADATA_CONFIG` to the YAML config path, or omit it to use `./config.yaml`
- `GREGFLIX_POSTGRES_PASSWORD` for the Postgres password
- `TMDB_API_KEY` for TMDB access

Use [config.example.yaml](/C:/Users/sdgre/PycharmProjects/gregflix-metadata/config.example.yaml) as the starting point.

## Marker Files

The service writes plain-text YAML marker files with no extension:

- `gf-meta-tag`: written only after metadata lookup, image retrieval, database upsert, and sanitized filename generation all succeed
- `gf-meta-failed`: written when processing fails at any stage

Postgres is the authoritative record of processed and failed state. Marker files are operational
breadcrumbs that help operators inspect a media folder, but they are reconciled against database
state during scans.

- A success marker is skipped only when its referenced job/entity or legacy DB records still exist.
- A stale success marker creates a `metadata.metadata_issue` and the folder is queued for repair.
- A failed marker is skipped while its corresponding open metadata issue exists.
- Failed folders can be retried with `POST /scans?retry_failed=true`.
- Folders can be explicitly reprocessed with `POST /scans?reprocess=true`.
- A single folder can be reconciled or retried with `POST /scans?path=/path/to/folder`.
- Folders containing both markers create or update an invalid-marker metadata issue.
- If no marker exists but Postgres already knows files or jobs for the folder, the scan reconciles
  the folder instead of queueing a duplicate ingestion.

Success markers include the metadata job ID and canonical entity IDs. Failure markers include the
metadata job ID and metadata issue ID when available.

## Local Artwork And Metadata

During ingestion, the service also scans the media folder for local artwork and metadata sidecar
files. Recognized artwork names include `poster`, `cover`, `folder`, `backdrop`, `fanart`,
`landscape`, `banner`, `logo`, `season01-poster`, `season1-poster`, and
`season-specials-poster` with `.jpg`, `.png`, or `.webp` extensions. Simple episode still names like
`Show.S01E02-still.jpg` are also recognized.

Local artwork is copied into the configured image storage root under a `local_file` source layout and
stored in `metadata.artwork_asset` with `source=local_file` and the original source path preserved.
The original media-folder files are never overwritten, renamed, moved, or deleted.

Sidecar `.nfo`, `.xml`, and `.json` files are recorded as `metadata.metadata_evidence`. Full NFO/XML
parsing is intentionally not implemented yet.

Artwork preference is configured with:

```yaml
artwork:
  preference: prefer_provider
```

Supported values are `prefer_local`, `prefer_provider`, `provider_only`, and `local_only`.

## Provider Matching

TMDB lookup results are stored as scored provider match candidates before the ingester selects a
match. The service no longer accepts the first TMDB result blindly.

Each candidate is written to `metadata.provider_match_candidate` with provider ID, media type,
title/original title, release year/date, provider rank, popularity, raw score components, and final
confidence score. The score combines title similarity, year match, media type match, library category
hint, series/episode evidence, and provider rank/popularity tie-breakers.

Selection is controlled by:

```yaml
matching:
  confidence_threshold: 0.72
  ambiguity_delta: 0.05
```

If the best candidate is below the threshold, or if top candidates are too close, the job creates a
`metadata.metadata_issue` requiring manual resolution and does not write a success marker.

## Search Substrate

The project owns a PostgreSQL-native search substrate for future `homelab_api` and client search.
Migrations enable `pg_trgm` and `unaccent`, then maintain `catalog.search_document`.

Search documents include entity type, display title, normalized title, aliases, release year,
library category, overview/description, combined searchable text, and a `tsvector`. The table has a
GIN full-text index, trigram indexes for normalized title and aliases, and a partial visible-entity
index for catalog-ready reads.

The metadata ingester refreshes search documents after canonical metadata changes. Internal
repository helpers support title autocomplete, full-text search, and fuzzy title lookup. This service
does not expose public search endpoints; `homelab_api` can consume the table later through direct DB
reads or its own API layer.

## Catalog Projections

The `catalog` schema also exposes database-level projections intended for `homelab_api` to adapt
into client JSON:

- `catalog.catalog_card_view`: compact card rows with title, subtitle, year/date, category, poster
  and backdrop/landscape references, catalog-ready flag, and playable availability.
- `catalog.media_detail_view`: richer entity detail rows with overview, release/start/end dates,
  runtime or season count, poster/backdrop/banner references, and provider identity summary.
- `catalog.series_episode_view`: series/season/episode rows with still image reference and playable
  file availability.

Global catalog grouping tables are also present:

- `catalog.catalog_row`
- `catalog.catalog_row_item`

These projections are not final Qt JSON documents and contain no user-specific, auth, playback, or
continue-watching state.

## Local Run

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Create config:

```powershell
Copy-Item config.example.yaml config.yaml
```

Run migrations:

```powershell
python -m app migrate
```

Start the service:

```powershell
uvicorn app.main:app --reload
```

## Migrations

Database schema changes are owned by this project through Alembic migrations in `alembic/versions`.
Migrations use explicit PostgreSQL DDL and Alembic records applied versions in Postgres through
the `alembic_version` table.

The first schema generation kept the original public compatibility tables:

- `media_items`
- `media_files`
- `media_images`
- `metadata_jobs`

The canonical metadata substrate now lives in the `metadata` schema:

- `metadata.media_entity`
- `metadata.media_file`
- `metadata.artwork_asset`
- `metadata.provider_identity`
- `metadata.entity_alias`
- `metadata.metadata_evidence`
- `metadata.metadata_issue`

`metadata.media_entity` is the canonical hierarchy for movies, series, seasons, episodes, and
collections. Episode files point to episode entities, movie files point to movie entities, and
provider IDs are stored separately in `metadata.provider_identity`. The service still writes the
legacy public tables for compatibility while ingestion is migrated forward.

Apply migrations locally:

```powershell
python -m app migrate
```

Apply migrations from the container image:

```powershell
docker run --rm --env-file .env -v ${PWD}/config.yaml:/app/config.yaml gregflix-metadata python -m app migrate
```

Normal FastAPI startup verifies the database is already at the project migration head before it scans
libraries. Startup does not create or mutate schema. If the schema is missing or behind, run the
migration command first.

This service owns only GregFlix metadata/catalog ingestion objects. It must not create auth schemas,
user tables, or homelab API tables.

## API Endpoints

- `GET /health`
- `POST /scans`
- `GET /scans/status`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /config/summary`
- `POST /metadata/index-path`
- `POST /metadata/retry-path`
- `POST /metadata/entities/{entity_id}/refresh-provider`
- `POST /metadata/entities/{entity_id}/refresh-artwork`
- `GET /metadata/issues`
- `GET /metadata/diagnostics`

## Jobs

`metadata_jobs` is the durable queue and job history table. Scans insert `pending` jobs directly into
Postgres. The worker claims one pending job at a time transactionally with row locking and marks it
`running`; the service-level runner lock still prevents parallel execution inside one process.

Supported queue statuses are:

- `pending`
- `running`
- `succeeded`
- `failed`
- `cancelled`

The active queue prevents duplicate pending/running jobs for the same folder with a partial unique
index on the job lock key. If the application restarts while a job is `running`, startup marks that
job `failed` with `error_stage=startup_recovery`; the folder can then be retried explicitly through
scan retry/reprocess controls.

Job rows store job type, requester, folder path, library/category, retry count, claim/start/finish
timestamps, and error stage/reason. `/scans/status` reports durable pending/running job counts.

## Service Triggers

Internal service-to-service trigger endpoints create durable `metadata_jobs` rows and return
immediately with the job ID and current status. They do not block until ingestion completes.

- `POST /metadata/index-path` with `{"path": "...", "requester": "homelab_api"}`
- `POST /metadata/retry-path` with `{"path": "...", "requester": "downloader"}`
- `POST /metadata/entities/{entity_id}/refresh-provider`
- `POST /metadata/entities/{entity_id}/refresh-artwork`
- `GET /metadata/issues`
- `GET /metadata/diagnostics?entity_id=...`
- `GET /metadata/diagnostics?path=...`

Path-trigger endpoints validate the requested path against configured enabled library roots and map
descendant paths back to the top-level media folder. Arbitrary filesystem paths are rejected. This
service remains internal cluster-facing; auth and authorization stay in `homelab_api`.

## Kubernetes Deployment

K3s manifests live under `deploy/k8s`.

Included resources:

- Namespace: `gregflix`
- ConfigMap: non-secret `config.yaml`
- Secret template: `secret.example.yaml`
- Migration Job: runs `python -m app migrate`
- Deployment: one replica, internal service only
- Service: ClusterIP `gregflix-metadata`

The default image is:

```text
registry.home.arpa/gregflix-metadata:latest
```

Create the secret from the template, then run the migration Job before deploying the service:

```powershell
kubectl apply -f deploy/k8s/namespace.yaml
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/migration-job.yaml
kubectl -n gregflix wait --for=condition=complete job/gregflix-metadata-migrate --timeout=120s
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/deployment.yaml
```

`secret.yaml` should be created locally from `secret.example.yaml` and not committed with real
values. The Deployment references `gregflix-metadata-secrets` keys:

- `GREGFLIX_POSTGRES_PASSWORD`
- `TMDB_API_KEY`

Media PVCs are mounted read-only:

- `gregflix-media-movies`
- `gregflix-media-series`
- `gregflix-media-anime`
- `gregflix-media-documentaries`

Image storage is mounted read-write through `gregflix-image-storage`.

No Ingress is included. The service is reachable only inside the cluster at
`http://gregflix-metadata.gregflix.svc.cluster.local`.

## Version-One Limitations

- TMDB is the only provider
- Filename parsing is intentionally basic
- No confidence scoring or disambiguation workflow
- No persistent queue or crash recovery beyond rescanning unmarked folders on startup
- No automatic rescan of folders changed after processing
