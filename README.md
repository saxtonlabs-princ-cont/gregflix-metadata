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
- Runs exactly one metadata job at a time with an in-memory queue

## What It Does Not Do

- Rename, move, delete, or rewrite media files
- Watch the filesystem for changes
- Retry failed folders automatically
- Provide playback, catalog, recommendation, or frontend features
- Persist the job queue across restarts

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

Normal scans skip folders containing either marker. Folders containing both markers are treated as invalid and skipped with an error log.

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
alembic upgrade head
```

Start the service:

```powershell
uvicorn app.main:app --reload
```

## Migrations

- Generate or review migration files under `alembic/versions`
- Apply with `alembic upgrade head`

## API Endpoints

- `GET /health`
- `POST /scans`
- `GET /scans/status`
- `GET /jobs`
- `GET /jobs/{job_id}`
- `GET /config/summary`

## Version-One Limitations

- TMDB is the only provider
- Filename parsing is intentionally basic
- No confidence scoring or disambiguation workflow
- No persistent queue or crash recovery beyond rescanning unmarked folders on startup
- No automatic rescan of folders changed after processing
