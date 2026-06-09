"""
Chunks Router - Work queue and locking.
"""

import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, or_
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import Chunk, User, Video, ProcessingStatus
from backend.auth.deps import get_current_user


router = APIRouter()


# =============================================================================
# CONSTANTS (from environment)
# =============================================================================

LOCK_DURATION_MINUTES = int(os.getenv("LOCK_DURATION_MINUTES", "30"))


# =============================================================================
# SCHEMAS
# =============================================================================

class ChunkResponse(BaseModel):
    """Chunk response schema."""
    id: int
    video_id: int
    chunk_index: int
    audio_path: str
    status: ProcessingStatus
    locked_by_user_id: Optional[int]
    lock_expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class ChunkDetailResponse(ChunkResponse):
    """Chunk with video info."""
    video_title: str
    total_chunks: int


class LockResponse(BaseModel):
    """Lock acquisition response."""
    success: bool
    chunk_id: int
    locked_by_user_id: int
    lock_expires_at: datetime
    message: str


class ChunkListResponse(BaseModel):
    """Chunk response for video chunk list with lock owner info."""
    id: int
    video_id: int
    chunk_index: int
    audio_path: str
    status: ProcessingStatus
    locked_by_user_id: Optional[int]
    locked_by_username: Optional[str] = None
    lock_expires_at: Optional[datetime]
    segment_count: int = 0
    
    class Config:
        from_attributes = True


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_lock_expired(chunk: Chunk) -> bool:
    """Check if a chunk's lock has expired."""
    if chunk.locked_by_user_id is None:
        return True
    if chunk.lock_expires_at is None:
        return True
    return chunk.lock_expires_at < datetime.utcnow()


def clear_expired_lock(chunk: Chunk) -> None:
    """Clear expired lock from chunk."""
    if is_lock_expired(chunk):
        chunk.locked_by_user_id = None
        chunk.lock_expires_at = None


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/chunks", response_model=List[ChunkResponse])
def list_chunks(
    video_id: Optional[int] = Query(None),
    status: Optional[ProcessingStatus] = Query(None),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_session)
):
    """
    List chunks, optionally filtered by video or status.
    """
    stmt = select(Chunk).order_by(Chunk.video_id, Chunk.chunk_index).limit(limit)
    
    if video_id:
        stmt = stmt.where(Chunk.video_id == video_id)
    if status:
        stmt = stmt.where(Chunk.status == status)
    
    chunks = session.exec(stmt).all()
    return chunks


@router.get("/videos/{video_id}/chunks", response_model=List[ChunkListResponse])
def get_video_chunks(
    video_id: int,
    session: Session = Depends(get_session)
):
    """
    List all chunks for a specific video with lock owner info.
    
    Used by ChannelPage accordion to show chunk list with status/lock details.
    """
    from sqlalchemy import func
    from backend.db.models import Segment
    
    # Check video exists
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    chunks = session.exec(
        select(Chunk)
        .where(Chunk.video_id == video_id)
        .order_by(Chunk.chunk_index)
    ).all()
    
    now = datetime.utcnow()
    results = []
    
    for chunk in chunks:
        # Get lock owner username if locked and not expired
        locked_username = None
        if chunk.locked_by_user_id and chunk.lock_expires_at and chunk.lock_expires_at > now:
            locker = session.get(User, chunk.locked_by_user_id)
            locked_username = locker.username if locker else None
        
        # Count segments
        seg_count = session.exec(
            select(func.count(Segment.id)).where(Segment.chunk_id == chunk.id)
        ).one()
        
        results.append(ChunkListResponse(
            id=chunk.id,
            video_id=chunk.video_id,
            chunk_index=chunk.chunk_index,
            audio_path=chunk.audio_path,
            status=chunk.status,
            locked_by_user_id=chunk.locked_by_user_id if locked_username else None,
            locked_by_username=locked_username,
            lock_expires_at=chunk.lock_expires_at if locked_username else None,
            segment_count=seg_count
        ))
    
    return results


@router.get("/chunks/next", response_model=Optional[ChunkDetailResponse])
def get_next_chunk(
    video_id: Optional[int] = Query(None, description="Filter by video ID"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Get the next available chunk for annotation.
    
    Args:
        video_id: Optional filter to get chunks only from a specific video.
    
    Priority:
    1. Return user's currently locked chunk (resume work) - respects video_id filter
    2. Return first unlocked REVIEW_READY chunk
    
    Ghost Lock: Treats expired locks as NULL.
    """
    now = datetime.utcnow()
    
    # 1. Check if user has an existing lock (unfinished work)
    existing_stmt = select(Chunk).where(
        Chunk.locked_by_user_id == current_user.id,
        Chunk.lock_expires_at > now
    )
    # Filter by video_id if specified
    if video_id is not None:
        existing_stmt = existing_stmt.where(Chunk.video_id == video_id)
    
    existing = session.exec(existing_stmt).first()
    
    if existing:
        video = session.get(Video, existing.video_id)
        total = session.exec(
            select(Chunk).where(Chunk.video_id == existing.video_id)
        ).all()
        
        return ChunkDetailResponse(
            **existing.model_dump(),
            video_title=video.title if video else "Unknown",
            total_chunks=len(total)
        )
    
    # 2. Find next available chunk
    # Status is REVIEW_READY or IN_REVIEW (for resuming), and Lock is NULL (or expired)
    stmt = (
        select(Chunk)
        .where(
            or_(
                Chunk.status == ProcessingStatus.REVIEW_READY,
                Chunk.status == ProcessingStatus.IN_REVIEW
            )
        )
        .where(
            or_(
                Chunk.locked_by_user_id == None,
                Chunk.lock_expires_at < now
            )
        )
    )
    
    # Filter by video_id if specified
    if video_id is not None:
        stmt = stmt.where(Chunk.video_id == video_id)
    
    stmt = stmt.order_by(Chunk.video_id, Chunk.chunk_index)
    
    chunk = session.exec(stmt).first()
    
    if not chunk:
        return None
    
    video = session.get(Video, chunk.video_id)
    total = session.exec(
        select(Chunk).where(Chunk.video_id == chunk.video_id)
    ).all()
    
    return ChunkDetailResponse(
        **chunk.model_dump(),
        video_title=video.title if video else "Unknown",
        total_chunks=len(total)
    )


@router.get("/chunks/{chunk_id}", response_model=ChunkDetailResponse)
def get_chunk(chunk_id: int, session: Session = Depends(get_session)):
    """Get a specific chunk by ID with video info."""
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    video = session.get(Video, chunk.video_id)
    total = session.exec(
        select(Chunk).where(Chunk.video_id == chunk.video_id)
    ).all()
    
    return ChunkDetailResponse(
        **chunk.model_dump(),
        video_title=video.title if video else "Unknown",
        total_chunks=len(total)
    )


@router.post("/chunks/{chunk_id}/lock", response_model=LockResponse)
def lock_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Acquire lock on a chunk for editing.
    
    Concurrency Control:
    - If unlocked or lock expired: Grant lock
    - If locked by same user: Refresh lock
    - If locked by other user: Return 409 Conflict
    
    Status Handling:
    - REVIEW_READY → IN_REVIEW (new work)
    - APPROVED → IN_REVIEW (re-review, destructive)
    - IN_REVIEW → IN_REVIEW (refresh, no change)
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    now = datetime.utcnow()
    
    # Clear expired locks
    clear_expired_lock(chunk)
    
    # Check current lock state
    if chunk.locked_by_user_id is not None and chunk.locked_by_user_id != current_user.id:
        # Locked by another user
        locker = session.get(User, chunk.locked_by_user_id)
        locker_name = locker.username if locker else f"User {chunk.locked_by_user_id}"
        raise HTTPException(
            status_code=409,
            detail=f"Chunk is locked by {locker_name} until {chunk.lock_expires_at}"
        )
    
    # Grant or refresh lock
    chunk.locked_by_user_id = current_user.id
    chunk.lock_expires_at = now + timedelta(minutes=LOCK_DURATION_MINUTES)
    
    # Only change status to IN_REVIEW if it's REVIEW_READY or APPROVED
    # If already IN_REVIEW (refresh by same user), don't touch status
    if chunk.status in (ProcessingStatus.REVIEW_READY, ProcessingStatus.APPROVED):
        chunk.status = ProcessingStatus.IN_REVIEW
    
    session.add(chunk)
    session.commit()
    session.refresh(chunk)
    
    return LockResponse(
        success=True,
        chunk_id=chunk.id,
        locked_by_user_id=current_user.id,
        lock_expires_at=chunk.lock_expires_at,
        message="Lock acquired successfully"
    )


@router.post("/chunks/{chunk_id}/unlock")
def unlock_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Release lock on a chunk.
    
    Only the lock owner can release.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You don't own the lock on this chunk"
        )
    
    chunk.locked_by_user_id = None
    chunk.lock_expires_at = None
    chunk.status = ProcessingStatus.REVIEW_READY
    
    session.add(chunk)
    session.commit()
    
    return {"message": "Lock released"}


@router.post("/chunks/{chunk_id}/approve")
def approve_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark a chunk as approved (ready for export).
    
    Releases lock and sets status to APPROVED.
    """
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    # Must own the lock
    if chunk.locked_by_user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You must lock the chunk before approving"
        )
    
    chunk.status = ProcessingStatus.APPROVED
    chunk.locked_by_user_id = None
    chunk.lock_expires_at = None
    
    session.add(chunk)
    session.commit()
    
    return {"message": "Chunk approved", "status": ProcessingStatus.APPROVED}


@router.post("/chunks/{chunk_id}/retranscript")
def retranscript_chunk(
    chunk_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Mark a chunk for re-transcription by Gemini.
    
    This will:
    1. Delete all existing segments for this chunk
    2. Reset chunk status to PENDING
    3. Release any lock
    4. Create a new ProcessingJob to queue for Gemini
    
    Use when AI transcription was poor and needs to be redone.
    """
    from backend.db.models import Segment, ProcessingJob, JobStatus
    
    chunk = session.get(Chunk, chunk_id)
    if not chunk:
        raise HTTPException(status_code=404, detail="Chunk not found")
    
    # Delete existing segments
    segments = session.exec(
        select(Segment).where(Segment.chunk_id == chunk_id)
    ).all()
    segments_deleted = len(segments)
    for seg in segments:
        session.delete(seg)
    
    # Reset chunk status
    chunk.status = ProcessingStatus.PENDING
    chunk.locked_by_user_id = None
    chunk.lock_expires_at = None
    session.add(chunk)
    
    # Delete old FAILED/COMPLETED jobs for this chunk (prevents stale status in UI)
    old_jobs = session.exec(
        select(ProcessingJob)
        .where(ProcessingJob.chunk_id == chunk_id)
        .where(ProcessingJob.status.in_([JobStatus.FAILED, JobStatus.COMPLETED]))
    ).all()
    for old_job in old_jobs:
        session.delete(old_job)
    
    # Check if already has a QUEUED/PROCESSING job
    existing_job = session.exec(
        select(ProcessingJob)
        .where(ProcessingJob.chunk_id == chunk_id)
        .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
    ).first()
    
    job_created = False
    if not existing_job:
        # Create new ProcessingJob
        job = ProcessingJob(
            chunk_id=chunk_id,
            video_id=chunk.video_id,
            status=JobStatus.QUEUED,
            requested_by_user_id=current_user.id
        )
        session.add(job)
        job_created = True
    
    session.commit()
    
    return {
        "message": "Chunk queued for re-transcription",
        "chunk_id": chunk_id,
        "segments_deleted": segments_deleted,
        "job_created": job_created
    }

