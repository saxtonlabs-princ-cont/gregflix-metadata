from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.jobs import router as jobs_router
from app.api.scans import router as scans_router
from app.config import get_config
from app.db import create_session_factory
from app.jobs.queue import JobQueue
from app.jobs.runner import ScanCoordinator
from app.logging_config import configure_logging
from app.services.image_store import ImageStore
from app.services.metadata_ingester import MetadataIngester
from app.services.scanner import LibraryScanner
from app.services.tmdb_client import TmdbClient


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    config = get_config()
    logger.info("config loaded", extra={"event": "config_loaded"})
    session_factory = create_session_factory(config)
    logger.info("database initialized", extra={"event": "database_initialized"})

    scanner = LibraryScanner(config)
    queue = JobQueue()
    tmdb_client = TmdbClient(config.providers.tmdb)
    image_store = ImageStore(config.image_storage.root_path)
    ingester = MetadataIngester(config, session_factory, tmdb_client, image_store)
    coordinator = ScanCoordinator(queue, scanner, session_factory, ingester)

    app.state.config = config
    app.state.session_factory = session_factory
    app.state.scan_coordinator = coordinator

    logger.info("startup scan triggered", extra={"event": "startup_scan_triggered"})
    await coordinator.trigger_scan()
    yield


app = FastAPI(title="GregFlix Metadata Service", lifespan=lifespan)
app.include_router(health_router)
app.include_router(scans_router)
app.include_router(jobs_router)


@app.get("/config/summary", tags=["config"])
def config_summary() -> dict[str, object]:
    config = get_config()
    return {
        "libraries": [
            {
                "name": library.name,
                "category": library.category,
                "path": str(library.path),
                "enabled": library.enabled,
            }
            for library in config.libraries
        ],
        "image_root": str(config.image_storage.root_path),
        "marker_names": {
            "success": config.scanner.success_marker,
            "failure": config.scanner.failure_marker,
        },
        "supported_extensions": config.scanner.supported_extensions,
    }
