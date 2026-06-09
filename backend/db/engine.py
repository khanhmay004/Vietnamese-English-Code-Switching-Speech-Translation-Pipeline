"""
PostgreSQL Database Engine with Connection Pooling.

Uses SQLModel with psycopg2 for synchronous PostgreSQL access.
Configuration via environment variables for security.
"""

import os
from pathlib import Path
from typing import Generator

from sqlmodel import SQLModel, Session, create_engine


# =============================================================================
# CONFIGURATION
# =============================================================================

# Database connection string from environment
# Format: postgresql://user:password@host:port/database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/speech_translation_db"
)

# Data root for file paths (relative paths are resolved against this)
DATA_ROOT = Path(os.getenv("DATA_ROOT", "./data"))


# =============================================================================
# ENGINE SETUP
# =============================================================================

# Create engine with connection pooling
# pool_size: number of connections to keep open
# max_overflow: number of additional connections allowed beyond pool_size
engine = create_engine(
    DATABASE_URL,
    echo=False,  # Set True for SQL debugging
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
)


def get_session() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints.
    
    Yields a database session and ensures cleanup.
    
    Usage:
        @router.get("/users")
        def get_users(session: Session = Depends(get_session)):
            return session.exec(select(User)).all()
    """
    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    """
    Create all tables defined in models.py.
    
    Called during application startup.
    """
    SQLModel.metadata.create_all(engine)


def resolve_path(relative_path: str) -> Path:
    """
    Resolve a relative path against DATA_ROOT.
    
    Args:
        relative_path: Path stored in database (e.g., "raw/video_101.m4a")
        
    Returns:
        Absolute path to the file.
    """
    return DATA_ROOT / relative_path


def get_relative_path(absolute_path: Path) -> str:
    """
    Convert absolute path to relative path for database storage.
    
    Args:
        absolute_path: Full filesystem path
        
    Returns:
        Relative path string for database (e.g., "raw/video_101.m4a")
    """
    return str(absolute_path.relative_to(DATA_ROOT))
