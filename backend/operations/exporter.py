"""
Dataset Exporter - Operations Layer (OPTIMIZED).

Exports approved segments as individual audio clips for training.
Uses the "300-Second Guillotine" rule to prevent duplicate data from overlaps.

Output:
    - Individual WAV clips: export/video_{id}/segment_{nnnnn}.wav
    - manifest.tsv: id, video_id, audio_path, duration, transcript, translation

OPTIMIZATIONS (v2):
    - In-memory audio slicing via soundfile (no FFmpeg subprocess)
    - Aggressive RAM caching (load all chunks into memory)
    - Parallel processing via ThreadPoolExecutor
    - Dry-run mode for manifest preview without cutting audio

Usage:
    python -m backend.operations.exporter --video-id 1
    python -m backend.operations.exporter --all
    python -m backend.operations.exporter --all --dry-run
    python -m backend.operations.exporter --all --workers 16
"""

import csv
import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import soundfile as sf
from sqlmodel import Session, select
from tqdm import tqdm

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Video, Chunk, Segment, ProcessingStatus


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

CHUNK_DURATION = 300  # 5 minutes in seconds (guillotine cutoff)
SAMPLE_RATE = 16000   # 16kHz (standard for ASR)
CHANNELS = 1          # Mono

EXPORT_DIR = DATA_ROOT / "export"

# Default parallelism level
DEFAULT_WORKERS = 8


# =============================================================================
# DATA STRUCTURES
# =============================================================================

@dataclass
class ExportedSegment:
    """Segment ready for export as individual audio clip."""
    segment_id: int
    video_id: int
    chunk_id: int
    chunk_audio_path: str   # Source chunk file (relative to DATA_ROOT)
    start_time_relative: float
    end_time_relative: float
    duration: float
    transcript: str
    translation: str
    export_path: str = ""   # Output clip path (set after cutting)


@dataclass
class ExportResult:
    """Result of an export operation."""
    videos_processed: int = 0
    segments_exported: int = 0
    segments_failed: int = 0
    total_hours: float = 0.0
    failed_segments: List[str] = field(default_factory=list)


@dataclass
class ChunkCache:
    """
    RAM cache for chunk audio data.
    
    Key benefit: Load each 5-min WAV once, slice many segments from it.
    A 5-min 16kHz mono WAV is ~29MB. With 20GB RAM, we can cache 600+ chunks.
    """
    data: Dict[str, Tuple[np.ndarray, int]] = field(default_factory=dict)
    
    def get(self, chunk_path: str) -> Optional[Tuple[np.ndarray, int]]:
        """Get cached audio data and sample rate."""
        return self.data.get(chunk_path)
    
    def load(self, chunk_path: str, full_path: Path) -> Tuple[np.ndarray, int]:
        """Load audio file into cache (or return from cache)."""
        if chunk_path in self.data:
            return self.data[chunk_path]
        
        data, sr = sf.read(full_path, dtype='int16')
        self.data[chunk_path] = (data, sr)
        logger.debug(f"Cached chunk: {chunk_path} ({len(data)/sr:.1f}s)")
        return data, sr
    
    def clear(self) -> None:
        """Clear the cache to free memory."""
        self.data.clear()
    
    def size_mb(self) -> float:
        """Return approximate size of cached data in MB."""
        total_bytes = sum(
            data.nbytes for data, _ in self.data.values()
        )
        return total_bytes / (1024 * 1024)


# Global cache instance (persists across export calls)
_chunk_cache = ChunkCache()


# =============================================================================
# AUDIO SLICING (IN-MEMORY)
# =============================================================================

def slice_audio_inmem(
    audio_data: np.ndarray,
    sample_rate: int,
    start_time: float,
    end_time: float,
    output_path: Path
) -> bool:
    """
    Slice audio from numpy array and write to file.
    
    Args:
        audio_data: Full chunk audio as numpy array
        sample_rate: Sample rate (should be 16kHz)
        start_time: Start time in seconds
        end_time: End time in seconds
        output_path: Path for output WAV file
        
    Returns:
        True if successful, False otherwise
    """
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Calculate sample indices
        start_sample = int(start_time * sample_rate)
        end_sample = int(end_time * sample_rate)
        
        # Clamp to valid range
        start_sample = max(0, start_sample)
        end_sample = min(len(audio_data), end_sample)
        
        if start_sample >= end_sample:
            logger.error(f"Invalid slice range: {start_sample}-{end_sample}")
            return False
        
        # Extract slice
        segment_data = audio_data[start_sample:end_sample]
        
        # Write output (16-bit PCM WAV, same as FFmpeg output)
        sf.write(output_path, segment_data, sample_rate, subtype='PCM_16')
        
        return True
        
    except Exception as e:
        logger.error(f"Slice failed for {output_path.name}: {e}")
        return False


# =============================================================================
# EXPORT FUNCTIONS
# =============================================================================

def collect_segments_for_video(
    video_id: int,
    session: Session
) -> Tuple[List[ExportedSegment], Dict[int, str]]:
    """
    Collect all exportable segments for a video.
    
    Returns:
        Tuple of (segments_list, chunk_id_to_path_map)
    """
    # Get all approved chunks
    chunks = session.exec(
        select(Chunk)
        .where(Chunk.video_id == video_id)
        .where(Chunk.status == ProcessingStatus.APPROVED)
        .order_by(Chunk.chunk_index)
    ).all()
    
    if not chunks:
        return [], {}
    
    chunk_paths: Dict[int, str] = {c.id: c.audio_path for c in chunks}
    segments: List[ExportedSegment] = []
    
    for chunk in chunks:
        # Query segments with:
        # 1. is_rejected == False (exclude rejected segments)
        # 2. start_time_relative < 300 (guillotine rule)
        chunk_segments = session.exec(
            select(Segment)
            .where(Segment.chunk_id == chunk.id)
            .where(Segment.is_rejected == False)  # noqa: E712
            .where(Segment.start_time_relative < CHUNK_DURATION)
            .order_by(Segment.start_time_relative)
        ).all()
        
        for seg in chunk_segments:
            exported = ExportedSegment(
                segment_id=seg.id,
                video_id=video_id,
                chunk_id=chunk.id,
                chunk_audio_path=chunk.audio_path,
                start_time_relative=seg.start_time_relative,
                end_time_relative=seg.end_time_relative,
                duration=seg.end_time_relative - seg.start_time_relative,
                transcript=seg.transcript,
                translation=seg.translation,
            )
            segments.append(exported)
    
    return segments, chunk_paths


def export_segment(
    seg: ExportedSegment,
    output_path: Path,
    cache: ChunkCache,
    dry_run: bool = False
) -> bool:
    """
    Export a single segment using cached chunk data.
    
    Args:
        seg: Segment to export
        output_path: Output file path
        cache: Chunk cache with preloaded audio
        dry_run: If True, skip actual audio cutting
        
    Returns:
        True if successful (or dry_run), False otherwise
    """
    if dry_run:
        return True
    
    cached = cache.get(seg.chunk_audio_path)
    if cached is None:
        logger.error(f"Chunk not in cache: {seg.chunk_audio_path}")
        return False
    
    audio_data, sample_rate = cached
    
    return slice_audio_inmem(
        audio_data=audio_data,
        sample_rate=sample_rate,
        start_time=seg.start_time_relative,
        end_time=seg.end_time_relative,
        output_path=output_path
    )


def export_video(
    video_id: int,
    session: Session,
    workers: int = DEFAULT_WORKERS,
    dry_run: bool = False,
    cache: Optional[ChunkCache] = None
) -> Tuple[List[ExportedSegment], List[str]]:
    """
    Export all approved segments for a video using parallel processing.
    
    Args:
        video_id: ID of the video to export
        session: Database session
        workers: Number of parallel workers
        dry_run: If True, skip actual audio cutting
        cache: Optional chunk cache (uses global if None)
        
    Returns:
        Tuple of (exported_segments, failed_segment_descriptions)
    """
    # Get video
    video = session.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    
    # Collect segments
    segments, chunk_paths = collect_segments_for_video(video_id, session)
    
    if not segments:
        logger.warning(f"No exportable segments for video {video_id}")
        return [], []
    
    logger.info(f"Exporting video {video_id}: {len(segments)} segments from {len(chunk_paths)} chunks")
    
    # Use provided cache or global
    if cache is None:
        cache = _chunk_cache
    
    # Pre-load all chunks into RAM (the speed magic happens here)
    if not dry_run:
        for chunk_id, chunk_path in chunk_paths.items():
            full_path = DATA_ROOT / chunk_path
            if full_path.exists():
                cache.load(chunk_path, full_path)
            else:
                logger.warning(f"Chunk file missing: {chunk_path}")
    
    # Prepare output paths
    video_export_dir = EXPORT_DIR / f"video_{video_id}"
    
    # Build work items: (segment, output_path, counter)
    work_items = []
    for idx, seg in enumerate(segments, start=1):
        output_path = video_export_dir / f"segment_{idx:05d}.wav"
        seg.export_path = str(output_path.relative_to(DATA_ROOT))
        work_items.append((seg, output_path, idx))
    
    # Process in parallel
    exported_segments: List[ExportedSegment] = []
    failed_segments: List[str] = []
    
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {}
        for seg, output_path, idx in work_items:
            future = executor.submit(
                export_segment, seg, output_path, cache, dry_run
            )
            futures[future] = (seg, idx)
        
        with tqdm(total=len(futures), desc=f"video_{video_id}", unit="seg") as pbar:
            for future in as_completed(futures):
                seg, idx = futures[future]
                try:
                    success = future.result()
                    if success:
                        exported_segments.append(seg)
                    else:
                        failed_desc = f"seg_id={seg.segment_id}, start={seg.start_time_relative:.2f}s"
                        failed_segments.append(failed_desc)
                except Exception as e:
                    failed_desc = f"seg_id={seg.segment_id}: {str(e)}"
                    failed_segments.append(failed_desc)
                pbar.update(1)
    
    # Sort by segment counter to maintain order
    exported_segments.sort(key=lambda s: s.segment_id)
    
    return exported_segments, failed_segments


def write_manifest(segments: List[ExportedSegment], output_path: Path) -> None:
    """
    Write segments to TSV manifest file.
    
    Format: id, video_id, audio_path, duration, transcript, translation
    (No start/end columns - each clip is self-contained)
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, delimiter='\t')
        
        # Header
        writer.writerow([
            'id', 'video_id', 'audio_path', 
            'duration', 'transcript', 'translation'
        ])
        
        # Data rows
        for seg in segments:
            writer.writerow([
                seg.segment_id,
                seg.video_id,
                seg.export_path,
                f"{seg.duration:.3f}",
                seg.transcript,
                seg.translation,
            ])
    
    logger.info(f"Wrote manifest: {output_path} ({len(segments)} entries)")


def export_all_approved(
    workers: int = DEFAULT_WORKERS,
    dry_run: bool = False
) -> ExportResult:
    """
    Export all videos with approved chunks.
    
    Args:
        workers: Number of parallel workers
        dry_run: If True, skip actual audio cutting (manifest only)
        
    Returns:
        ExportResult with statistics
    """
    result = ExportResult()
    
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Create a fresh cache for this export run
    cache = ChunkCache()
    
    with Session(engine) as session:
        # Find all videos with at least one approved chunk
        videos = session.exec(select(Video)).all()
        
        all_segments: List[ExportedSegment] = []
        
        for video in videos:
            try:
                segments, failed = export_video(
                    video.id, session, 
                    workers=workers, 
                    dry_run=dry_run,
                    cache=cache
                )
                if segments:
                    all_segments.extend(segments)
                    result.videos_processed += 1
                
                if failed:
                    result.failed_segments.extend(failed)
                    result.segments_failed += len(failed)
                    
            except Exception as e:
                logger.error(f"Failed to export video {video.id}: {e}")
                result.failed_segments.append(f"video_{video.id}: {str(e)}")
        
        # Write combined manifest
        if all_segments:
            manifest_path = EXPORT_DIR / "manifest.tsv"
            write_manifest(all_segments, manifest_path)
            result.segments_exported = len(all_segments)
            
            # Calculate total duration
            total_duration = sum(s.duration for s in all_segments)
            hours = total_duration / 3600
            result.total_hours = round(hours, 2)
            
            logger.info(f"Total exported: {result.total_hours:.2f} hours of audio")
            logger.info(f"Cache size: {cache.size_mb():.1f} MB")
    
    # Clear cache after export
    cache.clear()
    
    # Log any failures
    if result.failed_segments:
        logger.warning(f"Failed to export {result.segments_failed} segments:")
        for fail in result.failed_segments[:10]:  # Show first 10
            logger.warning(f"  - {fail}")
        if len(result.failed_segments) > 10:
            logger.warning(f"  ... and {len(result.failed_segments) - 10} more")
    
    return result


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import argparse
    import time
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )
    
    parser = argparse.ArgumentParser(
        description="Export approved segments to individual audio clips"
    )
    parser.add_argument("--video-id", type=int, help="Export specific video")
    parser.add_argument("--all", action="store_true", help="Export all approved videos")
    parser.add_argument("--output", type=str, default=str(EXPORT_DIR), help="Output directory")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS,
        help=f"Number of parallel workers (default: {DEFAULT_WORKERS})"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate manifest without cutting audio (for testing)"
    )
    args = parser.parse_args()
    
    start_time = time.time()
    
    if args.video_id:
        with Session(engine) as session:
            segments, failed = export_video(
                args.video_id, session,
                workers=args.workers,
                dry_run=args.dry_run
            )
            if segments:
                output_path = Path(args.output) / f"video_{args.video_id}_manifest.tsv"
                write_manifest(segments, output_path)
                print(f"✓ Exported {len(segments)} segments to {output_path}")
            if failed:
                print(f"✗ Failed to export {len(failed)} segments:")
                for f in failed:
                    print(f"  - {f}")
    elif args.all:
        result = export_all_approved(workers=args.workers, dry_run=args.dry_run)
        elapsed = time.time() - start_time
        
        print(f"\n{'='*50}")
        print(f"Export Complete {'(DRY RUN)' if args.dry_run else ''}")
        print(f"{'='*50}")
        print(f"  Videos processed: {result.videos_processed}")
        print(f"  Segments exported: {result.segments_exported}")
        print(f"  Segments failed: {result.segments_failed}")
        print(f"  Total duration: {result.total_hours:.2f} hours")
        print(f"  Time elapsed: {elapsed:.1f}s")
        print(f"  Workers used: {args.workers}")
        if result.failed_segments:
            print(f"\n  ⚠ Some segments failed - check logs for details")
    else:
        parser.print_help()
