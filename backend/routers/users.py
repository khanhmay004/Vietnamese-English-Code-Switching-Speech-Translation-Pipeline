"""
Users Router - List and manage annotators.
Channels Router - CRUD for YouTube source channels.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from pydantic import BaseModel

from backend.db.engine import get_session
from backend.db.models import User, UserRole, Channel


router = APIRouter()


# =============================================================================
# SCHEMAS
# =============================================================================

class UserResponse(BaseModel):
    """User response schema."""
    id: int
    username: str
    role: UserRole
    
    class Config:
        from_attributes = True


class ChannelResponse(BaseModel):
    """Channel response schema."""
    id: int
    name: str
    url: str
    
    class Config:
        from_attributes = True


class ChannelCreate(BaseModel):
    """Schema for creating a new channel."""
    name: str
    url: str


# =============================================================================
# USER ENDPOINTS
# =============================================================================

@router.get("/users", response_model=List[UserResponse])
def list_users(session: Session = Depends(get_session)):
    """
    List all annotator users.
    
    Used by ingestion GUI dropdown and frontend user selector.
    """
    users = session.exec(select(User).order_by(User.username)).all()
    return users


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int, session: Session = Depends(get_session)):
    """Get a specific user by ID."""
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# =============================================================================
# CHANNEL ENDPOINTS
# =============================================================================

@router.get("/channels", response_model=List[ChannelResponse])
def list_channels(session: Session = Depends(get_session)):
    """
    List all YouTube source channels.
    
    Used by ingestion GUI dropdown for channel selection.
    """
    channels = session.exec(select(Channel).order_by(Channel.name)).all()
    return channels


@router.get("/channels/by-url", response_model=ChannelResponse)
def get_channel_by_url(
    url: str = Query(..., description="YouTube channel URL"),
    session: Session = Depends(get_session)
):
    """
    Find a channel by its YouTube URL.
    
    Used by ingestion GUI to check if a channel already exists before creating.
    
    Returns:
        Channel if found
        
    Raises:
        404 if channel URL not found
    """
    # Normalize URL (strip whitespace)
    url = url.strip()
    
    channel = session.exec(
        select(Channel).where(Channel.url == url)
    ).first()
    
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    return channel


# =============================================================================
# CHANNEL STATISTICS - MUST BE BEFORE /{channel_id} TO AVOID ROUTE CONFLICT
# =============================================================================

class ChannelStatsResponse(BaseModel):
    """Statistics for a single channel."""
    channel_id: int
    total_videos: int
    total_chunks: int
    pending_chunks: int
    approved_chunks: int


class SystemStatsResponse(BaseModel):
    """System-wide statistics for Dashboard."""
    total_channels: int
    total_videos: int
    total_chunks: int
    total_segments: int
    approved_segments: int
    total_hours: float
    # Project Progress
    verified_hours: float
    target_hours: float = 50.0
    completion_percentage: float
    # Workflow Status
    chunks_pending_review: int
    active_locks: int


@router.get("/channels/stats", response_model=List[ChannelStatsResponse])
def get_channels_stats(session: Session = Depends(get_session)):
    """
    Get statistics for all channels.
    
    Returns count of videos, chunks, and chunk status breakdown per channel.
    Used by Dashboard to show channel cards with stats.
    """
    from sqlalchemy import func
    from backend.db.models import Video, Chunk, ProcessingStatus
    
    channels = session.exec(select(Channel)).all()
    
    results = []
    for channel in channels:
        video_count = session.exec(
            select(func.count(Video.id)).where(Video.channel_id == channel.id)
        ).one()
        
        video_ids = session.exec(
            select(Video.id).where(Video.channel_id == channel.id)
        ).all()
        
        if video_ids:
            total_chunks = session.exec(
                select(func.count(Chunk.id)).where(Chunk.video_id.in_(video_ids))
            ).one()
            
            pending_chunks = session.exec(
                select(func.count(Chunk.id)).where(
                    Chunk.video_id.in_(video_ids),
                    Chunk.status.in_([ProcessingStatus.PENDING, ProcessingStatus.REVIEW_READY, ProcessingStatus.IN_REVIEW])
                )
            ).one()
            
            approved_chunks = session.exec(
                select(func.count(Chunk.id)).where(
                    Chunk.video_id.in_(video_ids),
                    Chunk.status == ProcessingStatus.APPROVED
                )
            ).one()
        else:
            total_chunks = pending_chunks = approved_chunks = 0
        
        results.append(ChannelStatsResponse(
            channel_id=channel.id,
            total_videos=video_count,
            total_chunks=total_chunks,
            pending_chunks=pending_chunks,
            approved_chunks=approved_chunks
        ))
    
    return results


@router.get("/stats", response_model=SystemStatsResponse)
def get_system_stats(session: Session = Depends(get_session)):
    """
    Get system-wide statistics.
    
    Used by Dashboard header to show total channels, videos, hours, etc.
    """
    from datetime import datetime
    from sqlalchemy import func
    from backend.db.models import Video, Chunk, Segment, ProcessingStatus
    
    total_channels = session.exec(select(func.count(Channel.id))).one()
    total_videos = session.exec(select(func.count(Video.id))).one()
    total_chunks = session.exec(select(func.count(Chunk.id))).one()
    total_segments = session.exec(select(func.count(Segment.id))).one()
    
    approved_segments = session.exec(
        select(func.count(Segment.id)).where(Segment.is_verified == True)
    ).one()
    
    total_seconds = session.exec(
        select(func.coalesce(func.sum(Video.duration_seconds), 0))
    ).one()
    total_hours = total_seconds / 3600.0 if total_seconds else 0.0
    
    # Project Progress: Verified Hours
    verified_duration = session.exec(
        select(func.coalesce(
            func.sum(Segment.end_time_relative - Segment.start_time_relative),
            0
        )).where(Segment.is_verified == True)
    ).one()
    verified_hours = verified_duration / 3600.0 if verified_duration else 0.0
    
    # Completion percentage (target: 50 hours)
    target_hours = 50.0
    completion_percentage = min((verified_hours / target_hours) * 100, 100.0) if target_hours > 0 else 0.0
    
    # Workflow Status: Chunks Pending Review
    chunks_pending_review = session.exec(
        select(func.count(Chunk.id)).where(Chunk.status == ProcessingStatus.REVIEW_READY)
    ).one()
    
    # Workflow Status: Active Locks (not expired)
    now = datetime.utcnow()
    active_locks = session.exec(
        select(func.count(Chunk.id)).where(
            Chunk.locked_by_user_id.isnot(None),
            Chunk.lock_expires_at > now
        )
    ).one()
    
    return SystemStatsResponse(
        total_channels=total_channels,
        total_videos=total_videos,
        total_chunks=total_chunks,
        total_segments=total_segments,
        approved_segments=approved_segments,
        total_hours=round(total_hours, 1),
        verified_hours=round(verified_hours, 2),
        target_hours=target_hours,
        completion_percentage=round(completion_percentage, 1),
        chunks_pending_review=chunks_pending_review,
        active_locks=active_locks
    )


# =============================================================================
# CHANNEL CRUD - Dynamic routes AFTER static routes
# =============================================================================

@router.post("/channels", response_model=ChannelResponse, status_code=201)
def create_channel(
    data: ChannelCreate,
    session: Session = Depends(get_session)
):
    """
    Create a new YouTube source channel.
    """
    url = data.url.strip()
    name = data.name.strip()
    
    existing = session.exec(
        select(Channel).where(Channel.url == url)
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Channel with URL already exists (ID: {existing.id}, Name: {existing.name})"
        )
    
    channel = Channel(name=name, url=url)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    
    return channel


@router.get("/channels/{channel_id}", response_model=ChannelResponse)
def get_channel(channel_id: int, session: Session = Depends(get_session)):
    """Get a specific channel by ID."""
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    return channel


# =============================================================================
# CHANNEL VIDEO ENDPOINTS - These use {channel_id} but have longer paths
# =============================================================================

class VideoStatsResponse(BaseModel):
    """Statistics for a single video."""
    video_id: int
    total_chunks: int
    pending_chunks: int
    approved_chunks: int
    total_segments: int
    verified_segments: int


class VideoListResponse(BaseModel):
    """Video response with duration for channel page."""
    id: int
    title: str
    channel_id: int
    duration_seconds: int
    original_url: str
    status: str = "active"
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.get("/channels/{channel_id}/videos", response_model=List[VideoListResponse])
def get_channel_videos(
    channel_id: int,
    session: Session = Depends(get_session)
):
    """
    List all videos for a specific channel.
    """
    from backend.db.models import Video
    
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    videos = session.exec(
        select(Video)
        .where(Video.channel_id == channel_id)
        .order_by(Video.created_at.desc())
    ).all()
    
    return videos


@router.get("/channels/{channel_id}/videos/stats", response_model=List[VideoStatsResponse])
def get_channel_videos_stats(
    channel_id: int,
    session: Session = Depends(get_session)
):
    """
    Get statistics for all videos in a channel.
    """
    from sqlalchemy import func
    from backend.db.models import Video, Chunk, Segment, ProcessingStatus
    
    channel = session.get(Channel, channel_id)
    if not channel:
        raise HTTPException(status_code=404, detail="Channel not found")
    
    videos = session.exec(
        select(Video).where(Video.channel_id == channel_id)
    ).all()
    
    results = []
    for video in videos:
        total_chunks = session.exec(
            select(func.count(Chunk.id)).where(Chunk.video_id == video.id)
        ).one()
        
        pending_chunks = session.exec(
            select(func.count(Chunk.id)).where(
                Chunk.video_id == video.id,
                Chunk.status.in_([ProcessingStatus.PENDING, ProcessingStatus.REVIEW_READY, ProcessingStatus.IN_REVIEW])
            )
        ).one()
        
        approved_chunks = session.exec(
            select(func.count(Chunk.id)).where(
                Chunk.video_id == video.id,
                Chunk.status == ProcessingStatus.APPROVED
            )
        ).one()
        
        chunk_ids = session.exec(
            select(Chunk.id).where(Chunk.video_id == video.id)
        ).all()
        
        if chunk_ids:
            total_segments = session.exec(
                select(func.count(Segment.id)).where(Segment.chunk_id.in_(chunk_ids))
            ).one()
            
            verified_segments = session.exec(
                select(func.count(Segment.id)).where(
                    Segment.chunk_id.in_(chunk_ids),
                    Segment.is_verified == True
                )
            ).one()
        else:
            total_segments = verified_segments = 0
        
        results.append(VideoStatsResponse(
            video_id=video.id,
            total_chunks=total_chunks,
            pending_chunks=pending_chunks,
            approved_chunks=approved_chunks,
            total_segments=total_segments,
            verified_segments=verified_segments
        ))
    
    return results
