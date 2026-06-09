"""
SQLModel ORM Definitions for Vietnamese-English Code-Switching Pipeline.

This module defines the database schema using SQLModel (SQLAlchemy + Pydantic).
All timestamps in the Segment table are RELATIVE to chunk start (not absolute video time).

Tables:
    - User: Annotators with honor-system auth
    - Channel: YouTube source channels
    - Video: Downloaded episodes
    - Chunk: 5-minute audio segments (unit of work)
    - Segment: Individual transcription entries (training data)
    - ProcessingJob: Centralized queue for Gemini processing
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List

from sqlmodel import SQLModel, Field, Relationship


# =============================================================================
# ENUMS (State Machine)
# =============================================================================

class UserRole(str, Enum):
    """User permission levels."""
    ADMIN = "admin"          # Can delete data / manage users
    ANNOTATOR = "annotator"  # Can only edit/review


class ProcessingStatus(str, Enum):
    """Chunk workflow states."""
    PENDING = "pending"            # Just created/uploaded
    PROCESSING = "processing"      # Gemini/FFmpeg running
    REVIEW_READY = "review_ready"  # AI finished, waiting for human
    IN_REVIEW = "in_review"        # Currently locked by a user
    APPROVED = "approved"          # Human verified, ready for export
    REJECTED = "rejected"          # Audio unusable


class JobStatus(str, Enum):
    """Processing job queue states (for Gemini worker)."""
    QUEUED = "queued"         # Waiting in queue
    PROCESSING = "processing" # Currently being processed by worker
    COMPLETED = "completed"   # Successfully finished
    FAILED = "failed"         # Error occurred, can retry


# =============================================================================
# USER & CHANNEL TABLES
# =============================================================================

class User(SQLModel, table=True):
    """
    Annotator accounts using honor-system auth.
    
    Auth: Frontend sends X-User-ID header with user.id.
    No passwords - trusted team environment.
    """
    __tablename__ = "users"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=100)
    role: UserRole = Field(default=UserRole.ANNOTATOR)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    uploaded_videos: List["Video"] = Relationship(back_populates="uploader")
    locked_chunks: List["Chunk"] = Relationship(back_populates="locker")


class Channel(SQLModel, table=True):
    """
    YouTube source channel (e.g., "Vietcetera").
    
    Constraint: url is UNIQUE to prevent duplicate channels.
    """
    __tablename__ = "channels"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=200)
    url: str = Field(unique=True, max_length=500)  # YouTube channel URL
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    videos: List["Video"] = Relationship(back_populates="channel")


# =============================================================================
# VIDEO TABLE (Ingestion Layer)
# =============================================================================

class Video(SQLModel, table=True):
    """
    Downloaded YouTube video/podcast episode.
    
    Constraint: original_url is UNIQUE - duplicate prevention.
    Path: file_path is RELATIVE (e.g., "raw/video_101.m4a").
    """
    __tablename__ = "videos"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    channel_id: int = Field(foreign_key="channels.id")
    uploaded_by_id: int = Field(foreign_key="users.id")
    
    # Metadata
    title: str = Field(max_length=500)
    duration_seconds: int = Field(ge=0)
    
    # Duplicate Prevention: If URL exists, reject download
    original_url: str = Field(unique=True, max_length=1000)
    
    # File Path (RELATIVE to data root, e.g., "raw/video_101.m4a")
    file_path: str = Field(max_length=500)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    channel: Channel = Relationship(back_populates="videos")
    uploader: User = Relationship(back_populates="uploaded_videos")
    chunks: List["Chunk"] = Relationship(back_populates="video")


# =============================================================================
# CHUNK TABLE (Workflow Layer)
# =============================================================================

class Chunk(SQLModel, table=True):
    """
    5-minute audio segment - the "unit of work" for annotators.
    
    Concurrency: locked_by_user_id + lock_expires_at for "Ghost Lock" pattern.
    Path: audio_path is RELATIVE (e.g., "chunks/video_101/chunk_000.wav").
    """
    __tablename__ = "chunks"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key="videos.id")
    
    # Ordering (used for absolute time calculation during export)
    chunk_index: int = Field(ge=0)
    
    # File Path (RELATIVE, e.g., "chunks/video_101/chunk_000.wav")
    audio_path: str = Field(max_length=500)
    
    # State Management
    status: ProcessingStatus = Field(default=ProcessingStatus.PENDING)
    
    # Concurrency Control ("Ghost Lock")
    # If locked_by_user_id is set and lock_expires_at > now(), chunk is locked
    locked_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    lock_expires_at: Optional[datetime] = Field(default=None)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    video: Video = Relationship(back_populates="chunks")
    locker: Optional[User] = Relationship(back_populates="locked_chunks")
    segments: List["Segment"] = Relationship(back_populates="chunk")


# =============================================================================
# SEGMENT TABLE (Data Layer)
# =============================================================================

class Segment(SQLModel, table=True):
    """
    Individual transcription entry - the training data.
    
    CRITICAL: All timestamps are RELATIVE to chunk start (0.0s - 305.0s).
    Absolute time is calculated ONLY during export:
        AbsoluteTime = (ChunkIndex * 300) + RelativeTime
    """
    __tablename__ = "segments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: int = Field(foreign_key="chunks.id")
    
    # Timestamps (RELATIVE to chunk file start)
    # 0.0s = Start of the 5-minute .wav file
    # Example: start=4.5 means 4.5 seconds into the chunk
    start_time_relative: float = Field(ge=0.0)
    end_time_relative: float = Field(ge=0.0)
    
    # The Content
    transcript: str  # Original code-switched text
    translation: str  # Vietnamese translation
    
    # Quality Control
    is_verified: bool = Field(default=False)  # Green checkmark - segment is good
    is_rejected: bool = Field(default=False)  # Red X - segment is bad, exclude from export
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    chunk: Chunk = Relationship(back_populates="segments")


# =============================================================================
# PROCESSING JOB TABLE (Queue Layer)
# =============================================================================

class ProcessingJob(SQLModel, table=True):
    """
    Centralized job queue for Gemini processing.
    
    One job = one chunk to process.
    Worker polls this table, processes QUEUED jobs one-by-one.
    
    Deduplication: Before inserting, check if chunk already has 
    a QUEUED or PROCESSING job. If so, skip.
    """
    __tablename__ = "processing_jobs"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    
    # Links to the chunk being processed
    chunk_id: int = Field(foreign_key="chunks.id", index=True)
    video_id: int = Field(foreign_key="videos.id", index=True)  # Denormalized for fast queries
    
    # Job state
    status: JobStatus = Field(default=JobStatus.QUEUED, index=True)
    
    # Tracking timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    
    # Error tracking (for FAILED jobs)
    error_message: Optional[str] = Field(default=None, max_length=1000)
    
    # Who requested this job
    requested_by_user_id: int = Field(foreign_key="users.id")
