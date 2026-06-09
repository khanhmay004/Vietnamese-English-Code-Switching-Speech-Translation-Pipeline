"""Test yt-dlp download with corrected configuration."""
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.ingestion.downloader import download_audio, get_yt_dlp_config

url = 'https://www.youtube.com/watch?v=mVSrQn9xsTA'
output_dir = Path('./data/temp')

print("=" * 50)
print("Testing download with corrected format_sort...")
print(f"URL: {url}")
print(f"Output: {output_dir}")
print()

# Show the config being used
config = get_yt_dlp_config(output_dir, 'test')
print(f"format_sort: {config['format_sort']}")
print()

result = download_audio(url, output_dir, lambda msg: print(f"  {msg}"))

if result and result.file_path:
    print(f"\n✓ SUCCESS!")
    print(f"  Title: {result.title}")
    print(f"  File: {result.file_path}")
    print(f"  Duration: {result.duration_seconds}s")
    print(f"  Channel: {result.channel_name}")
else:
    print("\n✗ FAILED - No file returned")

