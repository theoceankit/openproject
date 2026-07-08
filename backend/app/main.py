import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, facts, health, project_resolutions, projects
from app.core.config import settings
from app.core.logging import request_id_var, setup_logging

setup_logging()

logger = logging.getLogger("app.requests")

app = FastAPI(title="OpenProject backend")

cors_origins = [origin.strip() for origin in settings.cors_allow_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    token = request_id_var.set(request_id)
    start = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.monotonic() - start) * 1000
        logger.exception("%s %s -> error after %.1f ms", request.method, request.url.path, duration_ms)
        raise
    else:
        duration_ms = (time.monotonic() - start) * 1000
        logger.info("%s %s -> %s in %.1f ms", request.method, request.url.path, response.status_code, duration_ms)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


app.include_router(health.router)
app.include_router(documents.router)
app.include_router(projects.router)
app.include_router(project_resolutions.router)
app.include_router(facts.router)
app.include_router(chat.router)
