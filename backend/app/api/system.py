"""Health, configuration introspection and the one-click demo reset."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config import get_target_schema, settings
from ..database import get_db, reset_db
from ..models import Migration
from ..schemas import HealthOut
from ..services import migration_agent
from ..services.llm import llm_client

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    schema = get_target_schema()
    return HealthOut(
        status="ok",
        app=settings.app_name,
        environment=settings.environment,
        llm=llm_client.health(),
        autonomy={
            "high_confidence_threshold": settings.high_confidence_threshold,
            "medium_confidence_threshold": settings.medium_confidence_threshold,
            "min_confidence_margin": settings.min_confidence_margin,
            "max_auto_repair_attempts": settings.max_auto_repair_attempts,
            "max_push_attempts": settings.max_push_attempts,
        },
        target_schema_version=schema.get("version", "1.0.0"),
    )


@router.get("/target-schema")
def target_schema() -> dict:
    return get_target_schema()


@router.post("/demo/reset")
def reset_demo(db: Session = Depends(get_db)) -> dict:
    """Wipe every migration AND the mock target platform. Demo convenience."""
    db.close()
    reset_db()
    return {"status": "reset", "message": "All migrations and target data removed"}


@router.get("/demo/status")
def demo_status(db: Session = Depends(get_db)) -> dict:
    latest = db.query(Migration).order_by(Migration.id.desc()).first()
    return {
        "has_migration": latest is not None,
        "latest_migration_id": latest.migration_id if latest else None,
        "state": latest.state if latest else None,
        "agent_running": migration_agent.is_running(latest.migration_id) if latest else False,
        "demo_files": migration_agent.DEMO_FILES,
    }
