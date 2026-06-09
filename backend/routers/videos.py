"""
Videos Router - Upload, duplicate check, and list videos.

Upload flow:
1. Validate URL not duplicate
2. Save audio file to data/raw/
3. Create Video record
4. Auto-chunk into 5-minute segments (non-blocking)
"""

import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.db.engine import get_session, DATA_ROOT
from backend.db.models import Video, Channel, User
from backend.auth.deps import get_current_user


logger = logging.getLogger(__name__)


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class VideoResponse(BaseModel):
    """Video response schema."""
    id: int
    title: str
    duration_seconds: int
    original_url: str
    file_path: str
    channel_id: int
    uploaded_by_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class VideoCheckResponse(BaseModel):
    """Response for duplicate check."""
    exists: bool
    video_id: Optional[int] = None
    message: str


class VideoUploadResponse(BaseModel):
    """Response after video upload."""
    video_id: int
    title: str
    file_path: str
    chunks_created: int = 0  # Number of chunks created (0 if failed)
    jobs_queued: int = 0  # Number of chunks auto-queued for Gemini processing
    message: str


# =============================================================================
# ENDPOINTS
# =============================================================================

@router.get("/videos", response_model=List[VideoResponse])
def list_videos(
    channel_id: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    session: Session = Depends(get_session)
):
    """
    List all videos, optionally filtered by channel.
    """
    stmt = select(Video).order_by(Video.created_at.desc()).limit(limit)
    if channel_id:
        stmt = stmt.where(Video.channel_id == channel_id)
    
    videos = session.exec(stmt).all()
    return videos


@router.get("/videos/check", response_model=VideoCheckResponse)
def check_video_exists(
    url: str = Query(..., description="YouTube video URL to check"),
    session: Session = Depends(get_session)
):
    """
    Check if a video URL already exists in the database.
    
    Used by ingestion GUI to prevent duplicate downloads.
    
    Returns:
        exists: True if URL already in database
        video_id: ID of existing video if found
        message: Human-readable status
    """
    # Normalize URL (strip whitespace)
    url = url.strip()
    
    video = session.exec(
        select(Video).where(Video.original_url == url)
    ).first()
    
    if video:
        return VideoCheckResponse(
            exists=True,
            video_id=video.id,
            message=f"Video already exists: '{video.title}'"
        )
    
    return VideoCheckResponse(
        exists=False,
        video_id=None,
        message="Video not found, OK to download"
    )


@router.get("/videos/{video_id}", response_model=VideoResponse)
def get_video(video_id: int, session: Session = Depends(get_session)):
    """Get a specific video by ID."""
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@router.post("/videos/upload", response_model=VideoUploadResponse)
async def upload_video(
    audio: UploadFile = File(...),
    title: str = Form(...),
    duration_seconds: int = Form(...),
    original_url: str = Form(...),
    channel_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Upload a video/audio file.
    
    Stores file in data/raw/ and creates Video record.
    
    Args:
        audio: The audio file (.m4a, .wav, etc.)
        title: Video title
        duration_seconds: Total duration
        original_url: YouTube URL (must be unique)
        channel_id: Channel ID
        
    Returns:
        Created video info
    """
    # Check for duplicate URL
    existing = session.exec(
        select(Video).where(Video.original_url == original_url)
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Video with URL already exists (ID: {existing.id})"
        )
    
    # Check channel exists
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    # Generate unique filename
    # Use timestamp + part of URL hash for uniqueness
    import hashlib
    url_hash = hashlib.md5(original_url.encode()).hexdigest()[:8]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    # Keep original extension
    original_ext = Path(audio.filename).suffix or ".m4a"
    filename = f"video_{timestamp}_{url_hash}{original_ext}"
    
    # Save file
    raw_dir = DATA_ROOT / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_path = raw_dir / filename
    
    with open(file_path, "wb") as f:
        shutil.copyfileobj(audio.file, f)
    
    # Create database record
    video = Video(
        title=title,
        duration_seconds=duration_seconds,
        original_url=original_url,
        file_path=f"raw/{filename}",  # Store relative path
        channel_id=channel_id,
        uploaded_by_id=current_user.id,
    )
    session.add(video)
    session.commit()
    session.refresh(video)
    
    # Auto-chunk the video (non-blocking - errors don't fail upload)
    chunks_created = 0
    jobs_queued = 0
    try:
        from backend.processing.chunker import chunk_video
        chunks_created = chunk_video(video.id, session)
        logger.info(f"Auto-chunked video {video.id}: {chunks_created} chunks created")
        
        # Auto-queue for Gemini processing
        if chunks_created > 0:
            from backend.db.models import Chunk, ProcessingJob, JobStatus, ProcessingStatus
            chunks = session.exec(
                select(Chunk)
                .where(Chunk.video_id == video.id)
                .where(Chunk.status == ProcessingStatus.PENDING)
            ).all()
            
            for chunk in chunks:
                job = ProcessingJob(
                    chunk_id=chunk.id,
                    video_id=video.id,
                    status=JobStatus.QUEUED,
                    requested_by_user_id=current_user.id
                )
                session.add(job)
                jobs_queued += 1
            
            session.commit()
            logger.info(f"Auto-queued {jobs_queued} chunks for Gemini processing (video {video.id})")
            
    except Exception as e:
        logger.error(f"Auto-chunk/queue failed for video {video.id}: {e}")
        # Don't fail the upload, just log the error
    
    return VideoUploadResponse(
        video_id=video.id,
        title=video.title,
        file_path=video.file_path,
        chunks_created=chunks_created,
        jobs_queued=jobs_queued,
        message=f"Video uploaded successfully. {chunks_created} chunks created, {jobs_queued} queued for processing."
    )


@router.post("/videos/{video_id}/chunk")
def trigger_manual_chunking(
    video_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Manually trigger chunking for a video.
    
    Use this when:
    - Auto-chunking failed during upload
    - Video was uploaded before auto-chunking was implemented
    
    Args:
        video_id: ID of video to chunk
        current_user: Authenticated user
        
    Returns:
        Number of chunks created
        
    Raises:
        404: Video not found
        400: Video already has chunks
    """
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Check if already has chunks
    from backend.db.models import Chunk
    existing_chunks = session.exec(
        select(Chunk).where(Chunk.video_id == video_id)
    ).all()
    
    if len(existing_chunks) > 0:
        raise HTTPException(
            status_code=400, 
            detail=f"Video already has {len(existing_chunks)} chunks. Delete them first if you want to re-chunk."
        )
    
    # Run chunking
    try:
        from backend.processing.chunker import chunk_video
        chunks_created = chunk_video(video_id, session)
        logger.info(f"Manual chunking for video {video_id}: {chunks_created} chunks created")
    except Exception as e:
        logger.error(f"Manual chunking failed for video {video_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Chunking failed: {str(e)}"
        )
    
    return {
        "video_id": video_id,
        "chunks_created": chunks_created,
        "message": f"Successfully created {chunks_created} chunks"
    }

