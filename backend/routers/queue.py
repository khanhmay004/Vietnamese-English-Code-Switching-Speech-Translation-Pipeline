"""
Processing Queue Router - Centralized Job Queue Management.

This router manages the Gemini processing queue using a centralized
background worker pattern:

1. Users select videos and submit to queue
2. System deduplicates (skips if already QUEUED/PROCESSING)
3. Background worker processes one chunk at a time
4. SSE endpoint provides real-time status updates

Endpoints:
    POST /queue/add-videos   - Add videos to processing queue
    GET  /queue/summary      - Get current queue state
    GET  /queue/status       - SSE stream for real-time updates
    POST /queue/retry-failed - Retry failed jobs for a video
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlmodel import Session, select

from backend.db.engine import get_session, engine
from backend.db.models import (
    User, Video, Chunk, Channel,
    ProcessingJob, JobStatus, ProcessingStatus
)
from backend.auth.deps import get_current_user


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/queue", tags=["Processing Queue"])


# =============================================================================
# SCHEMAS
# =============================================================================

class AddVideosRequest(BaseModel):
    """Request to add videos to the processing queue."""
    video_ids: List[int]


class AddVideosResponse(BaseModel):
    """Response after adding videos to queue."""
    queued: int           # New jobs added
    skipped: int          # Already in queue (deduplicated)
    video_ids: List[int]  # Videos that were processed


class VideoQueueStatus(BaseModel):
    """Queue status for a single video."""
    video_id: int
    video_title: str
    channel_name: str
    duration_seconds: int
    total_chunks: int
    pending_chunks: int       # PENDING status in Chunk table (not yet queued)
    queued_chunks: int        # Distinct chunks with QUEUED job
    processing_chunks: int    # Distinct chunks currently PROCESSING (0 or 1)
    completed_chunks: int     # Distinct chunks with COMPLETED job
    failed_chunks: int        # Distinct chunks with FAILED job (latest status)


class RetryResponse(BaseModel):
    """Response after retrying failed jobs."""
    retried: int
    video_id: int


class CancelResponse(BaseModel):
    """Response after cancelling queued jobs."""
    cancelled: int
    video_id: int


class CancelBulkRequest(BaseModel):
    """Request to cancel jobs for multiple videos."""
    video_ids: List[int]


class CancelBulkResponse(BaseModel):
    """Response after bulk cancelling jobs."""
    cancelled: int
    video_ids: List[int]


# =============================================================================
# ADD VIDEOS TO QUEUE
# =============================================================================

@router.post("/add-videos", response_model=AddVideosResponse)
def add_videos_to_queue(
    request: AddVideosRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Add all pending chunks from selected videos to the processing queue.
    
    Deduplication rules:
    - Only adds chunks with status=PENDING in Chunk table
    - Skips chunks that already have QUEUED or PROCESSING jobs
    - Jobs with COMPLETED or FAILED status are ignored (chunk may have new job)
    
    Args:
        request: Video IDs to queue
        current_user: Authenticated user
        
    Returns:
        Count of queued and skipped chunks
    """
    queued_count = 0
    skipped_count = 0
    
    for video_id in request.video_ids:
        # Verify video exists
        video = session.get(Video, video_id)
        if not video:
            logger.warning(f"Video {video_id} not found, skipping")
            continue
        
        # Get all PENDING chunks for this video
        chunks = session.exec(
            select(Chunk)
            .where(Chunk.video_id == video_id)
            .where(Chunk.status == ProcessingStatus.PENDING)
        ).all()
        
        for chunk in chunks:
            # Check if already in active queue (QUEUED or PROCESSING)
            existing = session.exec(
                select(ProcessingJob)
                .where(ProcessingJob.chunk_id == chunk.id)
                .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
            ).first()
            
            if existing:
                skipped_count += 1
                continue
            
            # Add to queue
            job = ProcessingJob(
                chunk_id=chunk.id,
                video_id=video_id,
                status=JobStatus.QUEUED,
                requested_by_user_id=current_user.id
            )
            session.add(job)
            queued_count += 1
    
    session.commit()
    
    logger.info(
        f"User {current_user.username} queued {queued_count} chunks, "
        f"skipped {skipped_count} (already in queue)"
    )
    
    return AddVideosResponse(
        queued=queued_count,
        skipped=skipped_count,
        video_ids=request.video_ids
    )


# =============================================================================
# QUEUE SUMMARY
# =============================================================================

@router.get("/summary", response_model=List[VideoQueueStatus])
def get_queue_summary(session: Session = Depends(get_session)):
    """
    Get current queue state for all videos with pending work.
    
    Returns videos that have:
    - PENDING chunks (not yet queued)
    - QUEUED/PROCESSING jobs (in progress)
    - FAILED jobs (need retry)
    
    This is the main data source for the Preprocessing page.
    """
    # Use raw SQL for efficiency (complex aggregation)
    # NOTE: Cast enums to text AND use LOWER() because PostgreSQL stores enum values as UPPERCASE
    # IMPORTANT: Count DISTINCT chunks, not jobs (to avoid counting retries multiple times)
    query = text("""
        SELECT 
            v.id as video_id,
            v.title as video_title,
            c.name as channel_name,
            v.duration_seconds,
            COUNT(DISTINCT ch.id) as total_chunks,
            COUNT(DISTINCT CASE WHEN LOWER(ch.status::text) = 'pending' THEN ch.id END) as pending_chunks,
            COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) = 'queued' THEN ch.id END) as queued_chunks,
            COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) = 'processing' THEN ch.id END) as processing_chunks,
            COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) = 'completed' THEN ch.id END) as completed_chunks,
            COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) = 'failed' THEN ch.id END) as failed_chunks
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        JOIN chunks ch ON ch.video_id = v.id
        LEFT JOIN processing_jobs pj ON pj.chunk_id = ch.id
        GROUP BY v.id, v.title, c.name, v.duration_seconds
        HAVING 
            COUNT(DISTINCT CASE WHEN LOWER(ch.status::text) = 'pending' THEN ch.id END) > 0
            OR COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) IN ('queued', 'processing') THEN ch.id END) > 0
            OR COUNT(DISTINCT CASE WHEN LOWER(pj.status::text) = 'failed' THEN ch.id END) > 0
        ORDER BY c.name, v.title
    """)
    
    result = session.exec(query).mappings().all()
    
    return [
        VideoQueueStatus(
            video_id=row["video_id"],
            video_title=row["video_title"],
            channel_name=row["channel_name"],
            duration_seconds=row["duration_seconds"],
            total_chunks=row["total_chunks"],
            pending_chunks=row["pending_chunks"],
            queued_chunks=int(row["queued_chunks"]),
            processing_chunks=int(row["processing_chunks"]),
            completed_chunks=int(row["completed_chunks"]),
            failed_chunks=int(row["failed_chunks"])
        )
        for row in result
    ]


# =============================================================================
# REAL-TIME STATUS (Server-Sent Events)
# =============================================================================

@router.get("/status")
async def stream_queue_status():
    """
    SSE endpoint for real-time queue updates.
    
    Frontend subscribes to this endpoint to receive live updates
    when jobs start, complete, or fail.
    
    Events sent:
    - job_started: {"chunk_id": 123, "video_id": 1}
    - job_completed: {"chunk_id": 123, "video_id": 1}
    - job_failed: {"chunk_id": 123, "video_id": 1, "error": "..."}
    - heartbeat: {} (every 5 seconds to keep connection alive)
    """
    async def event_generator():
        last_check = datetime.utcnow()
        
        while True:
            await asyncio.sleep(2)  # Poll every 2 seconds
            
            try:
                with Session(engine) as sess:
                    # Check for jobs that changed since last check
                    # Processing started
                    started = sess.exec(
                        select(ProcessingJob)
                        .where(ProcessingJob.status == JobStatus.PROCESSING)
                        .where(ProcessingJob.started_at > last_check)
                    ).all()
                    
                    for job in started:
                        event = {
                            "event": "job_started",
                            "chunk_id": job.chunk_id,
                            "video_id": job.video_id
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                    
                    # Completed jobs
                    completed = sess.exec(
                        select(ProcessingJob)
                        .where(ProcessingJob.status == JobStatus.COMPLETED)
                        .where(ProcessingJob.completed_at > last_check)
                    ).all()
                    
                    for job in completed:
                        event = {
                            "event": "job_completed",
                            "chunk_id": job.chunk_id,
                            "video_id": job.video_id
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                    
                    # Failed jobs
                    failed = sess.exec(
                        select(ProcessingJob)
                        .where(ProcessingJob.status == JobStatus.FAILED)
                        .where(ProcessingJob.completed_at > last_check)
                    ).all()
                    
                    for job in failed:
                        event = {
                            "event": "job_failed",
                            "chunk_id": job.chunk_id,
                            "video_id": job.video_id,
                            "error": job.error_message or "Unknown error"
                        }
                        yield f"data: {json.dumps(event)}\n\n"
                    
                    last_check = datetime.utcnow()
                
            except Exception as e:
                logger.error(f"SSE error: {e}")
            
            # Send heartbeat to keep connection alive
            yield f"data: {json.dumps({'event': 'heartbeat'})}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"  # Disable nginx buffering
        }
    )


# =============================================================================
# RETRY FAILED JOBS
# =============================================================================

@router.post("/retry-failed/{video_id}", response_model=RetryResponse)
def retry_failed_jobs(
    video_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Retry all failed jobs for a video.
    
    Creates new QUEUED jobs for chunks that previously failed.
    The old FAILED jobs are left as-is for audit purposes.
    
    Args:
        video_id: Video to retry failed chunks for
        current_user: Authenticated user
        
    Returns:
        Count of retried chunks
    """
    # Verify video exists
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Find chunks with FAILED jobs (and no new QUEUED/PROCESSING job)
    failed_chunks = session.exec(
        select(ProcessingJob)
        .where(ProcessingJob.video_id == video_id)
        .where(ProcessingJob.status == JobStatus.FAILED)
    ).all()
    
    retried = 0
    for old_job in failed_chunks:
        # Check if chunk already has a new active job
        existing = session.exec(
            select(ProcessingJob)
            .where(ProcessingJob.chunk_id == old_job.chunk_id)
            .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.PROCESSING]))
        ).first()
        
        if existing:
            continue  # Already being retried
        
        # Create new job
        new_job = ProcessingJob(
            chunk_id=old_job.chunk_id,
            video_id=video_id,
            status=JobStatus.QUEUED,
            requested_by_user_id=current_user.id
        )
        session.add(new_job)
        retried += 1
    
    session.commit()
    
    logger.info(f"User {current_user.username} retried {retried} failed chunks for video {video_id}")
    
    return RetryResponse(retried=retried, video_id=video_id)


# =============================================================================
# CANCEL QUEUED JOBS
# =============================================================================

@router.delete("/videos/{video_id}/jobs", response_model=CancelResponse)
def cancel_video_jobs(
    video_id: int,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Cancel all QUEUED jobs for a video.
    
    Does NOT cancel jobs that are currently PROCESSING.
    This allows users to remove videos from the queue without
    affecting work in progress.
    
    Args:
        video_id: Video ID to cancel jobs for
        current_user: Authenticated user
        
    Returns:
        Count of cancelled jobs
    """
    # Verify video exists
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    
    # Find and delete QUEUED jobs for this video
    queued_jobs = session.exec(
        select(ProcessingJob)
        .where(ProcessingJob.video_id == video_id)
        .where(ProcessingJob.status == JobStatus.QUEUED)
    ).all()
    
    cancelled = 0
    for job in queued_jobs:
        session.delete(job)
        cancelled += 1
    
    session.commit()
    
    logger.info(f"User {current_user.username} cancelled {cancelled} queued jobs for video {video_id}")
    
    return CancelResponse(cancelled=cancelled, video_id=video_id)


@router.delete("/jobs/bulk", response_model=CancelBulkResponse)
def cancel_bulk_jobs(
    request: CancelBulkRequest,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session)
):
    """
    Cancel all QUEUED jobs for multiple videos.
    
    Does NOT cancel jobs that are currently PROCESSING.
    
    Args:
        request: List of video IDs to cancel jobs for
        current_user: Authenticated user
        
    Returns:
        Total count of cancelled jobs
    """
    total_cancelled = 0
    
    for video_id in request.video_ids:
        # Find and delete QUEUED jobs for this video
        queued_jobs = session.exec(
            select(ProcessingJob)
            .where(ProcessingJob.video_id == video_id)
            .where(ProcessingJob.status == JobStatus.QUEUED)
        ).all()
        
        for job in queued_jobs:
            session.delete(job)
            total_cancelled += 1
    
    session.commit()
    
    logger.info(
        f"User {current_user.username} cancelled {total_cancelled} queued jobs "
        f"for {len(request.video_ids)} videos"
    )
    
    return CancelBulkResponse(cancelled=total_cancelled, video_ids=request.video_ids)


# =============================================================================
# QUEUE STATS (Simple endpoint for dashboard)
# =============================================================================

@router.get("/stats")
def get_queue_stats(session: Session = Depends(get_session)):
    """
    Get overall queue statistics.
    
    Returns counts of jobs in each status for dashboard display.
    """
    stats = {}
    
    for status in JobStatus:
        count = session.exec(
            select(ProcessingJob)
            .where(ProcessingJob.status == status)
        ).all()
        stats[status.value] = len(count)
    
    # Also count pending chunks (not in queue)
    pending_chunks = session.exec(
        select(Chunk)
        .where(Chunk.status == ProcessingStatus.PENDING)
    ).all()
    stats["pending_chunks"] = len(pending_chunks)
    
    return stats


@router.get("/logs")
def get_worker_logs(
    lines: int = Query(100, ge=10, le=1000, description="Number of lines to return"),
    current_user: User = Depends(get_current_user)
):
    """
    Get the last N lines from the Gemini worker log file.
    
    Used by the Preprocessing page to monitor worker activity.
    """
    from pathlib import Path
    
    # Log file location relative to backend directory
    log_file = Path(__file__).parent.parent.parent / "logs" / "gemini_worker.log"
    
    if not log_file.exists():
        return {
            "log_file": str(log_file),
            "exists": False,
            "lines": [],
            "message": "Log file not found. The worker may not have started yet."
        }
    
    try:
        # Read last N lines efficiently
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            last_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
        
        return {
            "log_file": str(log_file),
            "exists": True,
            "total_lines": len(all_lines),
            "lines": [line.rstrip('\n\r') for line in last_lines]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read log file: {str(e)}")

