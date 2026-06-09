"""
Manifest Preprocessing Script.

Cleans and filters manifest.tsv before training:
1. Strip markdown artifacts ([laughter], [music], etc.)
2. Normalize whitespace
3. Filter empty transcripts/translations
4. Filter too-short audio (<0.5s)
5. Mark too-long audio (>30s) for truncation

Usage:
    python preprocess_manifest.py [--input PATH] [--output PATH] [--sample_ratio FLOAT]
"""

import argparse
import logging
import re
from pathlib import Path
from typing import Tuple

import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def strip_markdown(text: str) -> str:
    """
    Remove markdown artifacts from text.
    
    Patterns removed:
    - [laughter], [music], [cười], etc.
    - **bold**, *italics*
    """
    if pd.isna(text) or not isinstance(text, str):
        return ""
    
    # Remove bracketed annotations: [laughter], [music], [cười], etc.
    text = re.sub(r'\[[^\]]*\]', '', text)
    
    # Remove markdown emphasis: **bold**, *italics*
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    
    return text.strip()


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.
    
    - Convert NBSP to regular space
    - Collapse multiple spaces to single space
    - Strip leading/trailing whitespace
    """
    if pd.isna(text) or not isinstance(text, str):
        return ""
    
    # Convert NBSP to regular space
    text = text.replace('\u00A0', ' ')
    
    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


def clean_text(text: str) -> str:
    """Apply all text cleaning steps."""
    text = strip_markdown(text)
    text = normalize_whitespace(text)
    return text


def preprocess_manifest(
    df: pd.DataFrame,
    min_duration: float = 0.5,
    max_duration: float = 30.0
) -> Tuple[pd.DataFrame, dict]:
    """
    Preprocess manifest DataFrame.
    
    Args:
        df: Input DataFrame with columns [id, video_id, audio_path, duration, transcript, translation]
        min_duration: Minimum audio duration in seconds (filter below)
        max_duration: Maximum audio duration in seconds (cap above)
        
    Returns:
        Tuple of (cleaned DataFrame, stats dict)
    """
    original_count = len(df)
    stats = {
        'original_count': original_count,
        'removed_empty_transcript': 0,
        'removed_empty_translation': 0,
        'removed_too_short': 0,
        'capped_too_long': 0,
        'markdown_cleaned': 0,
        'final_count': 0
    }
    
    # Step 1: Clean transcript and translation text
    logger.info("Cleaning text...")
    
    # Check for markdown before cleaning
    markdown_pattern = r'\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]'
    has_markdown = df['transcript'].str.contains(markdown_pattern, regex=True, na=False)
    stats['markdown_cleaned'] = has_markdown.sum()
    
    df['transcript'] = df['transcript'].apply(clean_text)
    df['translation'] = df['translation'].apply(clean_text)
    
    # Step 2: Filter empty transcripts
    empty_transcript = df['transcript'].str.len() < 1
    stats['removed_empty_transcript'] = empty_transcript.sum()
    df = df[~empty_transcript].copy()
    
    # Step 3: Filter empty translations
    empty_translation = df['translation'].str.len() < 1
    stats['removed_empty_translation'] = empty_translation.sum()
    df = df[~empty_translation].copy()
    
    # Step 4: Filter too-short audio
    too_short = df['duration'] < min_duration
    stats['removed_too_short'] = too_short.sum()
    df = df[~too_short].copy()
    
    # Step 5: Cap too-long audio (don't filter, just note for truncation)
    too_long = df['duration'] > max_duration
    stats['capped_too_long'] = too_long.sum()
    df.loc[too_long, 'duration'] = max_duration
    
    stats['final_count'] = len(df)
    
    return df, stats


def sample_data(df: pd.DataFrame, sample_ratio: float, seed: int = 42) -> pd.DataFrame:
    """
    Randomly sample a fraction of the data.
    
    Args:
        df: Input DataFrame
        sample_ratio: Fraction to sample (0.0 to 1.0)
        seed: Random seed for reproducibility
        
    Returns:
        Sampled DataFrame
    """
    if sample_ratio >= 1.0:
        return df
    
    return df.sample(frac=sample_ratio, random_state=seed)


def main():
    parser = argparse.ArgumentParser(description='Preprocess manifest.tsv')
    parser.add_argument(
        '--input',
        type=str,
        default='data/export/manifest.tsv',
        help='Input manifest TSV path'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='data/export/manifest_clean.tsv',
        help='Output cleaned manifest TSV path'
    )
    parser.add_argument(
        '--sample_ratio',
        type=float,
        default=1.0,
        help='Fraction of data to sample (0.0-1.0)'
    )
    parser.add_argument(
        '--min_duration',
        type=float,
        default=0.5,
        help='Minimum audio duration in seconds'
    )
    parser.add_argument(
        '--max_duration',
        type=float,
        default=30.0,
        help='Maximum audio duration in seconds'
    )
    parser.add_argument(
        '--seed',
        type=int,
        default=42,
        help='Random seed for sampling'
    )
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        return 1
    
    # Load manifest
    logger.info(f"Loading manifest from {input_path}")
    df = pd.read_csv(input_path, sep='\t')
    logger.info(f"Loaded {len(df)} samples")
    
    # Preprocess
    df, stats = preprocess_manifest(
        df,
        min_duration=args.min_duration,
        max_duration=args.max_duration
    )
    
    # Sample if requested
    if args.sample_ratio < 1.0:
        original_after_clean = len(df)
        df = sample_data(df, args.sample_ratio, args.seed)
        logger.info(f"Sampled {len(df)}/{original_after_clean} samples ({args.sample_ratio*100:.0f}%)")
    
    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, sep='\t', index=False)
    logger.info(f"Saved cleaned manifest to {output_path}")
    
    # Print stats
    print("\n" + "=" * 60)
    print("PREPROCESSING COMPLETE")
    print("=" * 60)
    print(f"Original samples: {stats['original_count']}")
    print(f"Markdown cleaned: {stats['markdown_cleaned']}")
    print(f"Removed (empty transcript): {stats['removed_empty_transcript']}")
    print(f"Removed (empty translation): {stats['removed_empty_translation']}")
    print(f"Removed (too short <{args.min_duration}s): {stats['removed_too_short']}")
    print(f"Capped (too long >{args.max_duration}s): {stats['capped_too_long']}")
    print(f"Final samples: {stats['final_count']}")
    if args.sample_ratio < 1.0:
        print(f"After {args.sample_ratio*100:.0f}% sampling: {len(df)}")
    print("=" * 60)
    
    return 0


if __name__ == '__main__':
    exit(main())
