"""
Data Splitter Utility - Create Train/Dev/Test splits from manifest.

Usage:
    python split_data.py [--manifest PATH] [--output_dir PATH] [--seed INT]
    
Logic:
    1. Read manifest.tsv
    2. Group by video_id (ensures no speaker overlap)
    3. Split 80/10/10 (train/dev/test)
    4. Normalize paths (backslash -> forward slash)
    5. Output CSVs
"""

import argparse
import logging
from pathlib import Path
from typing import Tuple

import pandas as pd
from sklearn.model_selection import train_test_split

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_manifest(manifest_path: Path) -> pd.DataFrame:
    """
    Load manifest TSV file.
    
    Args:
        manifest_path: Path to manifest.tsv
        
    Returns:
        DataFrame with columns: id, video_id, audio_path, duration, transcript, translation
    """
    logger.info(f"Loading manifest from {manifest_path}")
    
    df = pd.read_csv(manifest_path, sep='\t')
    
    # Normalize paths: backslash -> forward slash
    df['audio_path'] = df['audio_path'].str.replace('\\', '/', regex=False)
    
    # Prepend 'data/' if not present (for correct relative paths)
    if not df['audio_path'].iloc[0].startswith('data/'):
        df['audio_path'] = 'data/' + df['audio_path']
    
    logger.info(f"Loaded {len(df)} segments from {df['video_id'].nunique()} videos")
    
    return df


def split_by_video(
    df: pd.DataFrame,
    train_ratio: float = 0.8,
    dev_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split data by video_id to prevent speaker overlap.
    
    Args:
        df: Full manifest DataFrame
        train_ratio: Proportion for training (default 0.8)
        dev_ratio: Proportion for development (default 0.1)
        test_ratio: Proportion for testing (default 0.1)
        seed: Random seed for reproducibility
        
    Returns:
        Tuple of (train_df, dev_df, test_df)
    """
    assert abs(train_ratio + dev_ratio + test_ratio - 1.0) < 1e-6, "Ratios must sum to 1"
    
    # Get unique video IDs
    video_ids = df['video_id'].unique()
    logger.info(f"Splitting {len(video_ids)} videos with ratio {train_ratio}/{dev_ratio}/{test_ratio}")
    
    # Handle edge case: too few videos
    if len(video_ids) < 3:
        logger.warning(f"Only {len(video_ids)} videos - using random segment split instead")
        train_df, temp_df = train_test_split(df, test_size=(1-train_ratio), random_state=seed)
        dev_df, test_df = train_test_split(temp_df, test_size=test_ratio/(dev_ratio+test_ratio), random_state=seed)
        return train_df, dev_df, test_df
    
    # Split video IDs
    train_videos, temp_videos = train_test_split(
        video_ids, 
        test_size=(1 - train_ratio), 
        random_state=seed
    )
    dev_videos, test_videos = train_test_split(
        temp_videos, 
        test_size=test_ratio / (dev_ratio + test_ratio), 
        random_state=seed
    )
    
    # Filter dataframes
    train_df = df[df['video_id'].isin(train_videos)].copy()
    dev_df = df[df['video_id'].isin(dev_videos)].copy()
    test_df = df[df['video_id'].isin(test_videos)].copy()
    
    return train_df, dev_df, test_df


def save_splits(
    train_df: pd.DataFrame,
    dev_df: pd.DataFrame,
    test_df: pd.DataFrame,
    output_dir: Path
) -> None:
    """
    Save split DataFrames to CSV files.
    
    Args:
        train_df: Training data
        dev_df: Development data
        test_df: Test data
        output_dir: Directory to save CSVs
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    train_path = output_dir / 'train.csv'
    dev_path = output_dir / 'dev.csv'
    test_path = output_dir / 'test.csv'
    
    train_df.to_csv(train_path, index=False)
    dev_df.to_csv(dev_path, index=False)
    test_df.to_csv(test_path, index=False)
    
    logger.info(f"Saved splits to {output_dir}:")
    logger.info(f"  - train.csv: {len(train_df)} segments")
    logger.info(f"  - dev.csv: {len(dev_df)} segments")
    logger.info(f"  - test.csv: {len(test_df)} segments")


def main():
    parser = argparse.ArgumentParser(description='Split manifest into train/dev/test sets')
    parser.add_argument(
        '--manifest', 
        type=str, 
        default='data/export/manifest.tsv',
        help='Path to manifest.tsv'
    )
    parser.add_argument(
        '--output_dir', 
        type=str, 
        default='data/splits',
        help='Directory to save split CSVs'
    )
    parser.add_argument(
        '--seed', 
        type=int, 
        default=42,
        help='Random seed for reproducibility'
    )
    parser.add_argument(
        '--train_ratio',
        type=float,
        default=0.8,
        help='Training set ratio'
    )
    parser.add_argument(
        '--sample_ratio',
        type=float,
        default=1.0,
        help='Fraction of data to sample (0.0-1.0) for dev testing'
    )
    parser.add_argument(
        '--preprocess',
        action='store_true',
        help='Run preprocessing before splitting'
    )
    
    args = parser.parse_args()
    
    manifest_path = Path(args.manifest)
    output_dir = Path(args.output_dir)
    
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return 1
    
    # Load manifest
    df = load_manifest(manifest_path)
    
    # Preprocess if requested
    if args.preprocess:
        logger.info("Running preprocessing...")
        from preprocess_manifest import preprocess_manifest
        df, stats = preprocess_manifest(df)
        logger.info(f"Preprocessing complete: {stats['original_count']} -> {stats['final_count']} samples")
    
    # Sample if requested
    if args.sample_ratio < 1.0:
        original_count = len(df)
        df = df.sample(frac=args.sample_ratio, random_state=args.seed)
        logger.info(f"Sampled {len(df)}/{original_count} samples ({args.sample_ratio*100:.0f}%)")
    
    # Split by video
    train_df, dev_df, test_df = split_by_video(
        df, 
        train_ratio=args.train_ratio,
        dev_ratio=(1 - args.train_ratio) / 2,
        test_ratio=(1 - args.train_ratio) / 2,
        seed=args.seed
    )
    
    # Save
    save_splits(train_df, dev_df, test_df, output_dir)
    
    logger.info("Data splitting complete!")
    return 0


if __name__ == '__main__':
    exit(main())
