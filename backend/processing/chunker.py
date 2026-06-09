"""
FFmpeg Audio Chunker for Video Processing.

Splits downloaded audio into 5-minute chunks with 5-second overlap.
Output: 16kHz, Mono, WAV format (standard for ASR models).

Algorithm:
    - Chunk 0: 00:00 - 05:05 (305 seconds)
    - Chunk 1: 05:00 - 10:05 (305 seconds)
    - Chunk N: N*300 - (N+1)*300+5 seconds
    
The 5-second overlap is handled during export (stitching algorithm).
"""

import subprocess
import logging
import platform
import shutil
from pathlib import Path
from typing import List, Tuple, Optional

from sqlmodel import Session

from backend.db.engine import get_session, DATA_ROOT, engine
from backend.db.models import Video, Chunk, ProcessingStatus


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS
# =============================================================================

CHUNK_DURATION = 300  # 5 minutes in seconds
OVERLAP = 5           # 5 second overlap
SAMPLE_RATE = 16000   # 16kHz (standard for ASR)
CHANNELS = 1          # Mono

# Windows needs full path for executables in subprocess
IS_WINDOWS = platform.system() == "Windows"

# Find ffmpeg/ffprobe executables
def _find_executable(name: str) -> str:
    """Find executable, checking PATH and common locations."""
    # Try direct PATH lookup
    path = shutil.which(name)
    if path:
        return path
    
    # On Windows, check same directory as ffmpeg
    if IS_WINDOWS:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            ffmpeg_dir = Path(ffmpeg_path).parent
            candidate = ffmpeg_dir / f"{name}.exe"
            if candidate.exists():
                return str(candidate)
    
    return name  # Fallback to just the name

FFPROBE = _find_executable("ffprobe")
FFMPEG = _find_executable("ffmpeg")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_audio_duration(file_path: Path) -> float:
    """
    Get audio duration using ffmpeg (fallback from ffprobe).
    
    Uses ffmpeg with -i to read metadata and extracts duration from stderr.
    Works even when ffprobe is not installed.
    
    Args:
        file_path: Path to audio file
        
    Returns:
        Duration in seconds
        
    Raises:
        RuntimeError: If ffmpeg fails or duration can't be parsed
    """
    import re
    
    cmd = [
        FFMPEG,
        "-i", str(file_path),
        "-f", "null",
        "-"
    ]
    
    # ffmpeg writes metadata to stderr, so we need to capture it
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    # Look for Duration: HH:MM:SS.ms in stderr
    duration_match = re.search(
        r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)',
        result.stderr
    )
    
    if not duration_match:
        raise RuntimeError(f"Could not parse duration from ffmpeg output: {result.stderr[:200]}")
    
    hours, minutes, seconds, ms = duration_match.groups()
    total_seconds = (
        int(hours) * 3600 +
        int(minutes) * 60 +
        int(seconds) +
        int(ms) / 100  # Centiseconds to seconds
    )
    
    return total_seconds


def calculate_chunk_ranges(total_duration: float) -> List[Tuple[float, float]]:
    """
    Calculate start/end times for all chunks.
    
    Args:
        total_duration: Total audio duration in seconds
        
    Returns:
        List of (start_time, duration) tuples
    """
    ranges = []
    current_start = 0.0
    
    while current_start < total_duration:
        # Duration is CHUNK_DURATION + OVERLAP unless near end
        remaining = total_duration - current_start
        duration = min(CHUNK_DURATION + OVERLAP, remaining)
        
        ranges.append((current_start, duration))
        
        # Move forward by CHUNK_DURATION (not duration) to create overlap
        current_start += CHUNK_DURATION
    
    return ranges


# =============================================================================
# MAIN CHUNKING FUNCTION
# =============================================================================

def chunk_video(video_id: int, session: Optional[Session] = None) -> int:
    """
    Split a video's audio into 5-minute chunks.
    
    Creates Chunk records in database and WAV files on disk.
    
    Args:
        video_id: ID of the video to chunk
        session: Optional database session (creates new if not provided)
        
    Returns:
        Number of chunks created
        
    Raises:
        ValueError: If video not found
        RuntimeError: If FFmpeg fails
    """
    # Get or create session
    own_session = session is None
    if own_session:
        session = Session(engine)
    
    try:
        # Get video
        video = session.get(Video, video_id)
        if not video:
            raise ValueError(f"Video {video_id} not found")
        
        # Resolve paths
        input_path = DATA_ROOT / video.file_path
        if not input_path.exists():
            raise FileNotFoundError(f"Audio file not found: {input_path}")
        
        output_dir = DATA_ROOT / "chunks" / f"video_{video_id}"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Get duration
        duration = get_audio_duration(input_path)
        logger.info(f"Video {video_id}: {duration:.1f}s duration")
        
        # Calculate chunk ranges
        ranges = calculate_chunk_ranges(duration)
        logger.info(f"Will create {len(ranges)} chunks")
        
        # Check for existing chunks
        from sqlmodel import select
        existing = session.exec(
            select(Chunk).where(Chunk.video_id == video_id)
        ).all()
        
        if existing:
            logger.warning(f"Video {video_id} already has {len(existing)} chunks, skipping")
            return 0
        
        # Process each chunk
        chunks_created = 0
        
        for chunk_index, (start_time, chunk_duration) in enumerate(ranges):
            output_filename = f"chunk_{chunk_index:03d}.wav"
            output_path = output_dir / output_filename
            relative_path = f"chunks/video_{video_id}/{output_filename}"
            
            # FFmpeg command
            # -ss: Start time
            # -t: Duration
            # -ac 1: Mono
            # -ar 16000: 16kHz sample rate
            cmd = [
                FFMPEG, "-y",
                "-i", str(input_path),
                "-ss", str(start_time),
                "-t", str(chunk_duration),
                "-ac", str(CHANNELS),
                "-ar", str(SAMPLE_RATE),
                "-acodec", "pcm_s16le",  # 16-bit PCM
                str(output_path)
            ]
            
            logger.info(f"  Chunk {chunk_index}: {start_time:.1f}s - {start_time + chunk_duration:.1f}s")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                logger.error(f"FFmpeg failed: {result.stderr}")
                raise RuntimeError(f"FFmpeg failed for chunk {chunk_index}")
            
            # Create database record
            chunk = Chunk(
                video_id=video_id,
                chunk_index=chunk_index,
                audio_path=relative_path,
                status=ProcessingStatus.PENDING,
            )
            session.add(chunk)
            chunks_created += 1
        
        session.commit()
        logger.info(f"Created {chunks_created} chunks for video {video_id}")
        
        return chunks_created
        
    finally:
        if own_session:
            session.close()


def chunk_all_pending() -> int:
    """
    Chunk all videos that don't have chunks yet.
    
    Returns:
        Total number of chunks created
    """
    from sqlmodel import select
    
    with Session(engine) as session:
        # Find videos without chunks
        videos = session.exec(select(Video)).all()
        
        total_created = 0
        
        for video in videos:
            chunks = session.exec(
                select(Chunk).where(Chunk.video_id == video.id)
            ).all()
            
            if not chunks:
                try:
                    created = chunk_video(video.id, session)
                    total_created += created
                except Exception as e:
                    logger.error(f"Failed to chunk video {video.id}: {e}")
        
        return total_created


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            # Process all pending videos
            total = chunk_all_pending()
            print(f"Created {total} chunks total")
        else:
            # Process specific video by ID
            video_id = int(sys.argv[1])
            chunk_video(video_id)
    else:
        print("Usage: python chunker.py <video_id>")
        print("       python chunker.py --all")

