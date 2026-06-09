"""
Timestamp Parser for MM:SS.mmm and H:MM:SS.mmm Formats.

Bidirectional conversion between string timestamps and float seconds.
Handles multiple formats commonly output by Gemini API.

Supported formats:
    - "1:23.456"     -> 83.456 seconds (M:SS.mmm)
    - "0:01:23.456"  -> 83.456 seconds (H:MM:SS.mmm)
    - "01:23.456"    -> 83.456 seconds (MM:SS.mmm)
    - 83.456         -> 83.456 seconds (float passthrough)
"""

import re
from typing import Union


# =============================================================================
# PARSING (String -> Float)
# =============================================================================

# Regex patterns for different timestamp formats
PATTERN_H_MM_SS_MS = re.compile(r'^(\d+):(\d{1,2}):(\d{1,2})\.(\d+)$')  # 0:01:23.456
PATTERN_M_SS_MS = re.compile(r'^(\d+):(\d{1,2})\.(\d+)$')  # 1:23.456
PATTERN_MM_SS_MS = re.compile(r'^(\d{2}):(\d{2})\.(\d+)$')  # 01:23.456 (stricter)


def parse_timestamp(value: Union[str, int, float]) -> float:
    """
    Parse timestamp to seconds.
    
    Args:
        value: Timestamp as string ("1:23.456") or number
        
    Returns:
        Time in seconds as float
        
    Raises:
        ValueError: If format is invalid
        
    Examples:
        >>> parse_timestamp("1:23.456")
        83.456
        >>> parse_timestamp("0:01:03.95")
        63.95
        >>> parse_timestamp(63.95)
        63.95
    """
    if isinstance(value, (int, float)):
        return float(value)
    
    if not isinstance(value, str):
        raise ValueError(f"Timestamp must be str or number, got {type(value).__name__}")
    
    value = value.strip()
    
    # Try H:MM:SS.mmm format (e.g., "0:01:03.95") - two colons
    match = PATTERN_H_MM_SS_MS.match(value)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        ms_str = match.group(4)
        milliseconds = int(ms_str) / (10 ** len(ms_str))
        return hours * 3600 + minutes * 60 + seconds + milliseconds
    
    # Try M:SS.mmm format (e.g., "1:23.456") - one colon
    match = PATTERN_M_SS_MS.match(value)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        ms_str = match.group(3)
        milliseconds = int(ms_str) / (10 ** len(ms_str))
        return minutes * 60 + seconds + milliseconds
    
    # Try plain number as string
    try:
        return float(value)
    except ValueError:
        raise ValueError(f"Invalid timestamp format: '{value}'")


def is_valid_timestamp(value: Union[str, int, float]) -> bool:
    """
    Check if value is a valid timestamp.
    
    Args:
        value: Value to validate
        
    Returns:
        True if valid, False otherwise
    """
    try:
        parse_timestamp(value)
        return True
    except (ValueError, TypeError):
        return False


# =============================================================================
# FORMATTING (Float -> String)
# =============================================================================

def format_timestamp(seconds: float, include_hours: bool = False) -> str:
    """
    Format seconds as MM:SS.mmm string.
    
    Args:
        seconds: Time in seconds
        include_hours: If True, always include hours (H:MM:SS.mmm)
        
    Returns:
        Formatted timestamp string
        
    Examples:
        >>> format_timestamp(83.456)
        "01:23.456"
        >>> format_timestamp(3723.5, include_hours=True)
        "1:02:03.500"
    """
    if seconds < 0:
        raise ValueError(f"Seconds cannot be negative: {seconds}")
    
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    hours = total_seconds // 3600
    remaining = total_seconds % 3600
    minutes = remaining // 60
    secs = remaining % 60
    
    if include_hours or hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"
    else:
        return f"{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def format_timestamp_short(seconds: float) -> str:
    """
    Format seconds as compact M:SS.mmm string (no leading zeros).
    
    Args:
        seconds: Time in seconds
        
    Returns:
        Compact timestamp string
        
    Examples:
        >>> format_timestamp_short(83.456)
        "1:23.456"
        >>> format_timestamp_short(3.5)
        "0:03.500"
    """
    if seconds < 0:
        raise ValueError(f"Seconds cannot be negative: {seconds}")
    
    total_seconds = int(seconds)
    milliseconds = int((seconds - total_seconds) * 1000)
    
    minutes = total_seconds // 60
    secs = total_seconds % 60
    
    return f"{minutes}:{secs:02d}.{milliseconds:03d}"


# =============================================================================
# VALIDATION
# =============================================================================

def validate_segment_times(start: float, end: float, max_duration: float = 305.0) -> None:
    """
    Validate segment start/end times.
    
    Args:
        start: Start time in seconds
        end: End time in seconds
        max_duration: Maximum allowed time (chunk duration + overlap)
        
    Raises:
        ValueError: If times are invalid
    """
    if start < 0:
        raise ValueError(f"Start time cannot be negative: {start}")
    if end < 0:
        raise ValueError(f"End time cannot be negative: {end}")
    if end <= start:
        raise ValueError(f"End time ({end}) must be greater than start ({start})")
    if end > max_duration:
        raise ValueError(f"End time ({end}) exceeds maximum ({max_duration})")


def calculate_duration(start: float, end: float) -> float:
    """
    Calculate segment duration in seconds.
    
    Args:
        start: Start time in seconds
        end: End time in seconds
        
    Returns:
        Duration in seconds
    """
    return end - start
