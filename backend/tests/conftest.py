import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

# Every test run gets its own throwaway database.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{BACKEND_DIR / 'test_migration.db'}")
os.environ.setdefault("AGENT_STEP_DELAY_SECONDS", "0")
os.environ.setdefault("RETRY_BASE_DELAY_SECONDS", "0")
os.environ.setdefault("LLM_PROVIDER", "none")

import pytest  # noqa: E402

from app.config import DATA_DIR  # noqa: E402
from app.database import SessionLocal, reset_db  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def demo_files():
    """Make sure the demo source files exist before any test runs."""
    csv_path = DATA_DIR / "employees_legacy.csv"
    xlsx_path = DATA_DIR / "employees_hr.xlsx"
    if not csv_path.exists() or not xlsx_path.exists():
        import seed_demo

        seed_demo.main()
    return csv_path, xlsx_path


@pytest.fixture
def db():
    reset_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
