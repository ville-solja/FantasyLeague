from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from pathlib import Path


def _default_database_url() -> str:
    # Docker / Linux container: bind mount is usually ./data -> /app/data
    # (Do not gate on os.name — WSL/Linux hosts may look like "nt" in edge setups.)
    app_data = Path("/app/data")
    if app_data.is_dir():
        return "sqlite:////app/data/fantasy.db"

    # Local checkout: backend/database.py -> repo root is parent of backend/
    backend_dir = Path(__file__).resolve().parent
    repo_root = backend_dir.parent
    db_path = (repo_root / "data" / "fantasy.db").resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = os.getenv("DATABASE_URL") or _default_database_url()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.close()


def get_db():
    """FastAPI dependency: yield a DB session and guarantee close even on exception."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
