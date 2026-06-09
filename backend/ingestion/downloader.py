"""
YouTube Audio Downloader with yt-dlp.

Downloads audio from YouTube videos/playlists with strict configuration
to avoid dubbed audio tracks.

Configuration enforces:
    - Vietnamese audio priority (lang=vi)
    - Original audio fallback (orig)
    - m4a output format
    - Metadata JSON export
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

import yt_dlp


logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

def get_yt_dlp_config(output_dir: Path, video_id: str) -> Dict[str, Any]:
    """
    Get strict yt-dlp configuration for Vietnamese audio.
    
    Args:
        output_dir: Directory to save downloaded files
        video_id: YouTube video ID for filename
        
    Returns:
        yt-dlp options dictionary
        
    Note:
        format_sort uses colon syntax for preferences (field:value).
        See: https://github.com/yt-dlp/yt-dlp#sorting-formats
    """
    return {
        # Format Selection:
        # Prioritize Vietnamese audio, then best audio codec
        # format_sort syntax: field:preference (COLON, not equals!)
        'format': 'bestaudio/best',
        'format_sort': ['lang:vi', 'acodec:aac', 'abr'],
        
        # Output Template:
        'outtmpl': str(output_dir / f'{video_id}.%(ext)s'),
        
        # Post-Processing:
        # Convert to standardized m4a (AAC)
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'm4a',
            'preferredquality': '128',
        }],
        
        # Metadata:
        'writeinfojson': True,
        'writethumbnail': False,
        
        # Silence & Safety:
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': True,  # Skip private videos without crashing
        
        # Network:
        'socket_timeout': 30,  # 30 second timeout to prevent hanging
        'retries': 3,          # Retry failed downloads
        'fragment_retries': 3, # Retry failed fragments
        
        # Progress:
        'progress_hooks': [],
    }


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class VideoMetadata:
    """Metadata extracted from YouTube video."""
    video_id: str
    title: str
    duration_seconds: int
    channel_name: str
    channel_url: str
    original_url: str
    file_path: Optional[Path] = None


# =============================================================================
# DOWNLOAD FUNCTIONS
# =============================================================================

def extract_video_id(url: str) -> str:
    """
    Extract video ID from various YouTube URL formats.
    
    Supports:
        - https://www.youtube.com/watch?v=VIDEO_ID
        - https://youtu.be/VIDEO_ID
        - https://www.youtube.com/embed/VIDEO_ID
    """
    import re
    
    patterns = [
        r'(?:v=|/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be/)([0-9A-Za-z_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    # Fallback: assume URL is the ID itself
    return url.strip()


def fetch_metadata(url: str) -> Optional[VideoMetadata]:
    """
    Fetch video metadata without downloading.
    
    Args:
        url: YouTube video URL
        
    Returns:
        VideoMetadata or None if failed
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return None
            
            return VideoMetadata(
                video_id=info.get('id', ''),
                title=info.get('title', 'Unknown'),
                duration_seconds=int(info.get('duration', 0)),
                channel_name=info.get('channel', info.get('uploader', 'Unknown')),
                channel_url=info.get('channel_url', ''),
                original_url=info.get('webpage_url', url),
            )
            
    except Exception as e:
        logger.error(f"Failed to fetch metadata: {e}")
        return None


def _build_video_url(video_id: str) -> str:
    """
    Build a full YouTube watch URL from a video ID.
    
    Args:
        video_id: 11-character YouTube video ID
        
    Returns:
        Full YouTube watch URL
    """
    return f"https://www.youtube.com/watch?v={video_id}"


def fetch_playlist_metadata(url: str) -> List[VideoMetadata]:
    """
    Fetch metadata for all videos in a playlist or channel.
    
    Args:
        url: YouTube playlist/channel URL
        
    Returns:
        List of VideoMetadata objects
        
    Note:
        When using extract_flat mode, individual entries often lack channel info.
        We extract channel info from the parent playlist/channel metadata and
        apply it to all entries.
        
        CRITICAL: extract_flat returns video IDs, not full URLs. We must
        construct proper YouTube watch URLs for downloads to work.
    """
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
        'ignoreerrors': True,
        'socket_timeout': 30,  # Prevent hanging on network issues
    }
    
    results = []
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return []
            
            # Extract channel info from the parent playlist/channel metadata
            # This is reliable even when individual entries lack channel info
            parent_channel_name = (
                info.get('channel') or 
                info.get('uploader') or 
                info.get('channel_id') or  # Fallback to ID if name missing
                'Unknown'
            )
            parent_channel_url = (
                info.get('channel_url') or 
                info.get('uploader_url') or 
                ''
            )
            
            # Single video
            if 'entries' not in info:
                meta = fetch_metadata(url)
                if meta:
                    results.append(meta)
            else:
                # Playlist/channel
                for entry in info.get('entries', []):
                    if entry:
                        # Prefer entry-level channel info, fallback to parent
                        entry_channel = entry.get('channel') or entry.get('uploader')
                        entry_channel_url = entry.get('channel_url') or entry.get('uploader_url')
                        
                        # CRITICAL: extract_flat returns video IDs in 'url' field,
                        # not full URLs. We must build proper watch URLs.
                        video_id = entry.get('id', '')
                        
                        # Determine the proper URL: prefer webpage_url if present,
                        # otherwise build from video ID
                        raw_url = entry.get('webpage_url') or entry.get('url', '')
                        if raw_url and 'youtube.com' not in raw_url and 'youtu.be' not in raw_url:
                            # raw_url is just a video ID, build full URL
                            original_url = _build_video_url(video_id) if video_id else raw_url
                        else:
                            original_url = raw_url
                        
                        results.append(VideoMetadata(
                            video_id=video_id,
                            title=entry.get('title', 'Unknown'),
                            duration_seconds=int(entry.get('duration', 0) or 0),
                            channel_name=entry_channel if entry_channel else parent_channel_name,
                            channel_url=entry_channel_url if entry_channel_url else parent_channel_url,
                            original_url=original_url,
                        ))
                        
    except Exception as e:
        logger.error(f"Failed to fetch playlist: {e}")
    
    return results


def download_audio(
    url: str,
    output_dir: Path,
    progress_callback: Optional[callable] = None
) -> Optional[VideoMetadata]:
    """
    Download audio from YouTube video.
    
    Args:
        url: YouTube video URL
        output_dir: Directory to save the file
        progress_callback: Optional callback for progress updates
        
    Returns:
        VideoMetadata with file_path set, or None if failed
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Get video ID
    video_id = extract_video_id(url)
    
    # Configure yt-dlp
    config = get_yt_dlp_config(output_dir, video_id)
    
    # CRITICAL: Disable ignoreerrors for single video downloads
    # We need to know if the download actually failed
    config['ignoreerrors'] = False
    
    # Track if download actually completed
    download_completed = False
    download_error = None
    
    if progress_callback:
        def hook(d):
            nonlocal download_completed, download_error
            if d['status'] == 'downloading':
                percent = d.get('_percent_str', '0%')
                progress_callback(f"Downloading: {percent}")
            elif d['status'] == 'finished':
                download_completed = True
                progress_callback("Processing...")
            elif d['status'] == 'error':
                download_error = d.get('error', 'Unknown error')
        config['progress_hooks'] = [hook]
    else:
        # Still need to track completion even without callback
        def hook(d):
            nonlocal download_completed, download_error
            if d['status'] == 'finished':
                download_completed = True
            elif d['status'] == 'error':
                download_error = d.get('error', 'Unknown error')
        config['progress_hooks'] = [hook]
    
    try:
        with yt_dlp.YoutubeDL(config) as ydl:
            info = ydl.extract_info(url, download=True)
            
            if not info:
                logger.error(f"Download returned no info for {url}")
                return None
            
            # Check for download error
            if download_error:
                logger.error(f"Download error for {url}: {download_error}")
                return None
            
            # Find the downloaded file - check multiple possible filenames
            # yt-dlp might use the actual video ID from info, not our extracted one
            actual_video_id = info.get('id', video_id)
            
            file_path = None
            # Try both our extracted ID and the actual ID from yt-dlp
            for vid in [actual_video_id, video_id]:
                for ext in ['m4a', 'mp3', 'wav', 'opus', 'webm', 'mp4']:
                    candidate = output_dir / f"{vid}.{ext}"
                    if candidate.exists():
                        file_path = candidate
                        break
                if file_path:
                    break
            
            if not file_path or not file_path.exists():
                logger.error(f"Download completed but file not found for {url}")
                logger.error(f"  Searched for: {actual_video_id}.* and {video_id}.* in {output_dir}")
                return None
            
            return VideoMetadata(
                video_id=actual_video_id,
                title=info.get('title', 'Unknown'),
                duration_seconds=int(info.get('duration', 0)),
                channel_name=info.get('channel', info.get('uploader', 'Unknown')),
                channel_url=info.get('channel_url', ''),
                original_url=info.get('webpage_url', url),
                file_path=file_path,
            )
            
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Download failed for {url}: {error_msg}")
        if progress_callback:
            progress_callback(f"Error: {error_msg[:50]}")
        return None
    except Exception as e:
        logger.error(f"Download failed for {url}: {e}")
        return None


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    if len(sys.argv) < 2:
        print("Usage: python downloader.py <youtube_url> [output_dir]")
        sys.exit(1)
    
    url = sys.argv[1]
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("./downloads")
    
    print(f"Downloading: {url}")
    result = download_audio(url, output_dir, lambda msg: print(f"  {msg}"))
    
    if result and result.file_path:
        print(f"✓ Downloaded: {result.title}")
        print(f"  File: {result.file_path}")
        print(f"  Duration: {result.duration_seconds}s")
    else:
        print("✗ Download failed")
