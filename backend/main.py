"""
Vietnamese-English Code-Switching Speech Translation Pipeline.

FastAPI Backend - Main Application Entry Point.

Stack:
    - PostgreSQL (database)
    - SQLModel (ORM)
    - FastAPI (REST API)
    - React + Wavesurfer.js (frontend - separate)

Run:
    uvicorn backend.main:app --reload --port 8000
"""

import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.db.engine import create_db_and_tables, DATA_ROOT
from backend.routers import users, videos, chunks, segments, queue, export


# =============================================================================
# LIFESPAN (Startup/Shutdown)
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle events.
    
    Startup: Create tables, ensure data directories exist
    Shutdown: Cleanup
    """
    # Startup
    print("=" * 60)
    print("Vietnamese-English CS Speech Translation Pipeline")
    print("FastAPI Backend Starting...")
    print("=" * 60)
    
    # Ensure data directories exist
    (DATA_ROOT / "raw").mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "chunks").mkdir(parents=True, exist_ok=True)
    (DATA_ROOT / "export").mkdir(parents=True, exist_ok=True)
    
    # Create tables (safe to call multiple times)
    create_db_and_tables()
    print(f"✓ Database ready")
    print(f"✓ Data root: {DATA_ROOT.absolute()}")
    print("=" * 60)
    
    yield  # Application runs here
    
    # Shutdown
    print("Backend shutting down...")


# =============================================================================
# APPLICATION
# =============================================================================

app = FastAPI(
    title="Speech Translation Pipeline API",
    description="REST API for Vietnamese-English Code-Switching Speech Translation",
    version="2.0.0",
    lifespan=lifespan,
)


# =============================================================================
# CORS (Cross-Origin Resource Sharing)
# =============================================================================

# Load CORS origins from environment (comma-separated)
# Default includes common frontend dev ports
CORS_ORIGINS_STR = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173,http://127.0.0.1:3000"
)
CORS_ORIGINS = [origin.strip() for origin in CORS_ORIGINS_STR.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# ROUTERS
# =============================================================================

app.include_router(users.router, prefix="/api", tags=["Users"])
app.include_router(videos.router, prefix="/api", tags=["Videos"])
app.include_router(chunks.router, prefix="/api", tags=["Chunks"])
app.include_router(segments.router, prefix="/api", tags=["Segments"])
app.include_router(queue.router, prefix="/api", tags=["Processing Queue"])
app.include_router(export.router, prefix="/api", tags=["Export"])


# =============================================================================
# STATIC FILES (Audio Serving)
# =============================================================================

# Mount data directory for audio file access
# Files served at: /api/static/{relative_path}
# Example: /api/static/chunks/video_1/chunk_000.wav
if DATA_ROOT.exists():
    app.mount("/api/static", StaticFiles(directory=str(DATA_ROOT)), name="static")


# =============================================================================
# HEALTH CHECK
# =============================================================================

@app.get("/health", tags=["System"])
def health_check():
    """Basic health check endpoint."""
    return {"status": "healthy", "version": "2.0.0"}


@app.get("/", tags=["System"])
def root():
    """API root - redirect to docs."""
    return {
        "message": "Speech Translation Pipeline API",
        "docs": "/docs",
        "health": "/health",
    }
