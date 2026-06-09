"""
Segments Router - CRUD for transcription segments.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import Segment, Chunk, User
from backend.auth.deps import get_current_user
from backend.utils.time_parser import parse_timestamp, validate_segment_times


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class SegmentResponse(BaseModel):
    """Segment response schema."""
    id: int
    chunk_id: int
    start_time_relative: float
    end_time_relative: float
    transcript: str
    translation: str
    is_verified: bool
    is_rejected: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SegmentUpdate(BaseModel):
    """Schema for updating a segment."""
    start_time_relative: Optional[float] = None
    end_time_relative: Optional[float] = None
    transcript: Optional[str] = None
    translation: Optional[str] = None
    is_verified: Optional[bool] = None
    is_rejected: Optional[bool] = None


class SegmentCreate(BaseModel):
    """Schema for creating a segment."""
    chunk_id: int
    start_time_relative: float
    end_time_relative: float
    transcript: str
    translation: str
    is_verified: bool = False
    is_rejected: bool = False


class BulkSegmentResponse(BaseModel):
    """Response for bulk operations."""
    count: int
    segments: List[SegmentResponse]


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/segments", response_model=List[SegmentResponse])
def list_segments(
    chunk_id: Optional[int] = Query(None),
    verified_only: bool = Query(False),
    limit: int = Query(500, le=1000),
    session: Session = Depends(get_session)
):
    """
    List segments, optionally filtered by chunk.
    """
    stmt = select(Segment).order_by(Segment.chunk_id, Segment.start_time_relative).limit(limit)
    
    if chunk_id:
        stmt = stmt.where(Segment.chunk_id == chunk_id)
    if verified_only:
        stmt = stmt.where(Segment.is_verified == True)
    
    segments = session.exec(stmt).all()
    return segments


@router.get("/chunks/{chunk_id}/segments", response_model=List[SegmentResponse])
def get_chunk_segments(chunk_id: int, session: Session = Depends(get_session)):
    """
    Get all segments for a specific chunk.
    
    Ordered by start_time_relative for display.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    segments = session.exec(
        select(Segment)
        .where(Segment.chunk_id == chunk_id)
        .order_by(Segment.start_time_relative)
    ).all()
    
    return segments


@router.get("/segments/{segment_id}", response_model=SegmentResponse)
def get_segment(segment_id: int, session: Session = Depends(get_session)):
    """Get a specific segment by ID."""
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    return segment


@router.put("/segments/{segment_id}", response_model=SegmentResponse)
def update_segment(
    segment_id: int,
    update: SegmentUpdate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Update a segment's timestamps, text, or verification status.
    
    User must have lock on the parent chunk.
    """
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    # Check chunk lock
    chunk = session.get(Chunk, segment.chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Parent chunk not found")
    
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You must lock the chunk before editing segments"
        )
    
    # Apply updates
    update_data = update.model_dump(exclude_unset=True)
    
    # Validate timestamps if being updated
    new_start = update_data.get("start_time_relative", segment.start_time_relative)
    new_end = update_data.get("end_time_relative", segment.end_time_relative)
    
    try:
        validate_segment_times(new_start, new_end)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    for key, value in update_data.items():
        setattr(segment, key, value)
    
    segment.updated_at = datetime.utcnow()
    
    session.add(segment)
    session.commit()
    session.refresh(segment)
    
    return segment


@router.post("/segments", response_model=SegmentResponse)
def create_segment(
    data: SegmentCreate,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Create a new segment.
    
    User must have lock on the parent chunk.
    """
    # Check chunk exists and user has lock
    chunk = session.get(Chunk, data.chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You must lock the chunk before adding segments"
        )
    
    # Validate timestamps
    try:
        validate_segment_times(data.start_time_relative, data.end_time_relative)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    segment = Segment(**data.model_dump())
    session.add(segment)
    session.commit()
    session.refresh(segment)
    
    return segment


@router.delete("/segments/{segment_id}")
def delete_segment(
    segment_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Delete a segment.
    
    User must have lock on the parent chunk.
    """
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    # Check chunk lock
    chunk = session.get(Chunk, segment.chunk_id)
    if chunk and chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You must lock the chunk before deleting segments"
        )
    
    session.delete(segment)
    session.commit()
    
    return {"message": "Segment deleted", "id": segment_id}


@router.post("/segments/{segment_id}/verify", response_model=SegmentResponse)
def verify_segment(
    segment_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """Toggle verification status of a segment."""
    segment = session.get(Segment, segment_id)
    if not segment:
        raise HTTPException(status_code=404, detail="Segment not found")
    
    segment.is_verified = not segment.is_verified
    segment.updated_at = datetime.utcnow()
    
    session.add(segment)
    session.commit()
    session.refresh(segment)
    
    return segment


class BulkActionRequest(BaseModel):
    """Request body for bulk segment operations."""
    segment_ids: List[int]


@router.post("/segments/bulk-verify")
def bulk_verify_segments(
    data: BulkActionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark multiple segments as verified.
    Sets is_verified=True and is_rejected=False.
    """
    count = 0
    for segment_id in data.segment_ids:
        segment = session.get(Segment, segment_id)
        if segment:
            segment.is_verified = True
            segment.is_rejected = False  # Clear rejection when verifying
            segment.updated_at = datetime.utcnow()
            session.add(segment)
            count += 1
    
    session.commit()
    return {"message": f"Verified {count} segments", "count": count}


@router.post("/segments/bulk-reject")
def bulk_reject_segments(
    data: BulkActionRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark multiple segments as rejected.
    Sets is_rejected=True and is_verified=False.
    Rejected segments will be excluded from export.
    """
    count = 0
    for segment_id in data.segment_ids:
        segment = session.get(Segment, segment_id)
        if segment:
            segment.is_rejected = True
            segment.is_verified = False  # Clear verification when rejecting
            segment.updated_at = datetime.utcnow()
            session.add(segment)
            count += 1
    
    session.commit()
    return {"message": f"Rejected {count} segments", "count": count}

