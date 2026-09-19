"""FastAPI application entry point."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import escalations, migrations, system, target
from .config import settings
from .database import init_db
from .services import migration_agent
from .utils.errors import AppError
from .utils.logging import configure_logging, get_logger

log = get_logger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging()
    init_db()
    # Sync endpoints run in a worker thread; give the agent a handle on the
    # main loop so it can still be scheduled as an ordinary asyncio task.
    migration_agent.bind_event_loop(asyncio.get_running_loop())
    log.info(
        "application_started",
        environment=settings.environment,
        llm_provider=settings.llm_provider,
        mode="demo" if not settings.llm_enabled else "llm-assisted",
    )
    yield
    log.info("application_stopped")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description=(
        "An AI agent that migrates messy employee data into a new HR platform. "
        "Autonomous where it is confident and the action is reversible; escalates "
        "to a human where it is not."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
async def app_error_handler(_: Request, exc: AppError):
    log.warn("app_error", code=exc.code, message=exc.message)
    return JSONResponse(status_code=exc.status_code, content={"error": exc.to_dict()})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "request_validation_error",
                "message": "The request body or query parameters are invalid",
                "details": {"errors": exc.errors()},
            }
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception):  # pragma: no cover
    log.exception("unhandled_error", error=type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "internal_error",
                "message": "Unexpected server error",
                "details": {"type": type(exc).__name__},
            }
        },
    )


app.include_router(system.router)
app.include_router(migrations.router)
app.include_router(escalations.router)
app.include_router(target.router)


@app.get("/api/info", tags=["system"])
def info() -> dict:
    return {
        "app": settings.app_name,
        "docs": "/docs",
        "health": "/api/health",
        "mode": "demo (deterministic)" if not settings.llm_enabled else settings.llm_provider,
    }


# ---------------------------------------------------------------------------
# Single-service deployment
#
# In production the built React app is copied to backend/static and served from
# the same origin as the API, so there is one URL and no CORS. In local
# development that directory does not exist and Vite serves the UI on :5173
# instead - hence the guard.
#
# Mounted LAST: Starlette matches routes in registration order, so every /api
# and /target route above still wins.
# ---------------------------------------------------------------------------
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
    log.info("serving_bundled_ui", path=str(STATIC_DIR))
else:

    @app.get("/", tags=["system"], include_in_schema=False)
    def root() -> dict:
        return {
            **info(),
            "ui": "not bundled - run the Vite dev server on http://localhost:5173",
        }
