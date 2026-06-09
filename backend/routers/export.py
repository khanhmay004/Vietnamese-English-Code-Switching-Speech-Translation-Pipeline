"""
Export Router - API endpoints for dataset export.

Provides preview statistics and triggers export operations.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select, func
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import Chunk, Segment, Video, Channel, ProcessingStatus, User
from backend.auth.deps import get_current_user


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class ExportPreviewResponse(BaseModel):
    """Preview statistics for export."""
    total_approved_chunks: int
    total_verified_segments: int
    estimated_duration_hours: float


class ExportRunRequest(BaseModel):
    """Request body for export run."""
    workers: int = 8
    dry_run: bool = False


class ExportRunResponse(BaseModel):
    """Response after running export."""
    success: bool
    manifest_path: str
    clips_count: int
    total_hours: float
    elapsed_seconds: float = 0.0
    dry_run: bool = False


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/export/preview", response_model=ExportPreviewResponse)
def get_export_preview(
    channel_id: Optional[int] = Query(None, description="Filter by channel ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get preview statistics for export.
    
    Returns count of approved chunks and verified segments,
    with estimated duration in hours.
    """
    # Base query for approved chunks
    chunks_query = select(func.count(Chunk.id)).where(
        Chunk.status == ProcessingStatus.APPROVED
    )
    
    # Base query for verified segments (in approved chunks only)
    # We need to join through chunks to filter by channel
    segments_query = (
        select(func.count(Segment.id))
        .join(Chunk, Segment.chunk_id == Chunk.id)
        .where(
            Chunk.status == ProcessingStatus.APPROVED,
            Segment.is_verified == True,
            Segment.is_rejected == False
        )
    )
    
    # Duration query - sum of segment durations
    duration_query = (
        select(func.sum(Segment.end_time_relative - Segment.start_time_relative))
        .join(Chunk, Segment.chunk_id == Chunk.id)
        .where(
            Chunk.status == ProcessingStatus.APPROVED,
            Segment.is_verified == True,
            Segment.is_rejected == False
        )
    )
    
    # Apply channel filter if specified
    if channel_id:
        # Need to join with Video to filter by channel
        chunks_query = (
            select(func.count(Chunk.id))
            .join(Video, Chunk.video_id == Video.id)
            .where(
                Chunk.status == ProcessingStatus.APPROVED,
                Video.channel_id == channel_id
            )
        )
        
        segments_query = (
            select(func.count(Segment.id))
            .join(Chunk, Segment.chunk_id == Chunk.id)
            .join(Video, Chunk.video_id == Video.id)
            .where(
                Chunk.status == ProcessingStatus.APPROVED,
                Segment.is_verified == True,
                Segment.is_rejected == False,
                Video.channel_id == channel_id
            )
        )
        
        duration_query = (
            select(func.sum(Segment.end_time_relative - Segment.start_time_relative))
            .join(Chunk, Segment.chunk_id == Chunk.id)
            .join(Video, Chunk.video_id == Video.id)
            .where(
                Chunk.status == ProcessingStatus.APPROVED,
                Segment.is_verified == True,
                Segment.is_rejected == False,
                Video.channel_id == channel_id
            )
        )
    
    # Execute queries
    approved_chunks = session.exec(chunks_query).one() or 0
    verified_segments = session.exec(segments_query).one() or 0
    total_duration_seconds = session.exec(duration_query).one() or 0.0
    
    # Convert to hours
    estimated_hours = total_duration_seconds / 3600 if total_duration_seconds else 0.0
    
    return ExportPreviewResponse(
        total_approved_chunks=approved_chunks,
        total_verified_segments=verified_segments,
        estimated_duration_hours=round(estimated_hours, 2)
    )


@router.post("/export/run", response_model=ExportRunResponse)
def run_export(
    request: ExportRunRequest = None,
    channel_id: Optional[int] = Query(None, description="Filter by channel ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Run the export process.
    
    Exports all approved chunks with verified segments to individual audio clips.
    
    Args:
        workers: Number of parallel workers (default: 8)
        dry_run: If True, generate manifest without cutting audio
    """
    import time
    from backend.operations.exporter import export_all_approved, EXPORT_DIR
    
    # Handle missing request body
    if request is None:
        request = ExportRunRequest()
    
    start_time = time.time()
    
    try:
        # Run export with new parameters
        results = export_all_approved(
            workers=request.workers,
            dry_run=request.dry_run
        )
        
        elapsed = time.time() - start_time
        manifest_path = str(EXPORT_DIR / "manifest.tsv")
        
        return ExportRunResponse(
            success=True,
            manifest_path=manifest_path,
            clips_count=results.segments_exported,
            total_hours=results.total_hours,
            elapsed_seconds=round(elapsed, 1),
            dry_run=request.dry_run
        )
    except Exception as e:
        elapsed = time.time() - start_time
        return ExportRunResponse(
            success=False,
            manifest_path="",
            clips_count=0,
            total_hours=0.0,
            elapsed_seconds=round(elapsed, 1),
            dry_run=request.dry_run
        )

