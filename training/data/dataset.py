"""
VietEngDataset - Universal Dataset class for Vietnamese-English Speech Translation.

Supports both Whisper and Wav2Vec2+mBART models with unified interface.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional, Union

import torch
import torchaudio
import pandas as pd
from torch.utils.data import Dataset

logger = logging.getLogger(__name__)


class VietEngDataset(Dataset):
    """
    Dataset for Vietnamese-English Code-Switching Speech Translation.
    
    Args:
        csv_path: Path to split CSV (train.csv, dev.csv, or test.csv)
        audio_root: Root directory for audio files (default: current dir)
        sample_rate: Target sample rate (default: 16000)
        max_audio_length: Maximum audio length in seconds (default: 30)
        
    Returns dict with:
        - audio: Raw audio waveform (torch.Tensor)
        - sample_rate: Audio sample rate
        - transcript: Original code-switched text
        - translation: Vietnamese translation
        - audio_path: Path to audio file (for debugging)
        - duration: Audio duration in seconds
    """
    
    def __init__(
        self,
        csv_path: Union[str, Path],
        audio_root: Union[str, Path] = ".",
        sample_rate: int = 16000,
        max_audio_length: float = 30.0
    ):
        self.csv_path = Path(csv_path)
        self.audio_root = Path(audio_root)
        self.sample_rate = sample_rate
        self.max_audio_length = max_audio_length
        self.max_samples = int(max_audio_length * sample_rate)
        
        # Load data
        self.data = pd.read_csv(self.csv_path)
        logger.info(f"Loaded {len(self.data)} samples from {self.csv_path.name}")
        
    def __len__(self) -> int:
        return len(self.data)
    
    def __getitem__(self, idx: int) -> Dict[str, Any]:
        row = self.data.iloc[idx]
        
        # Resolve audio path
        audio_path = self.audio_root / row['audio_path']
        
        # Load audio
        try:
            waveform, sr = torchaudio.load(str(audio_path))
        except Exception as e:
            logger.error(f"Failed to load audio {audio_path}: {e}")
            # Return silence as fallback
            waveform = torch.zeros(1, self.sample_rate)
            sr = self.sample_rate
        
        # Convert to mono if stereo
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        
        # Resample if needed
        if sr != self.sample_rate:
            resampler = torchaudio.transforms.Resample(sr, self.sample_rate)
            waveform = resampler(waveform)
        
        # Flatten to 1D
        waveform = waveform.squeeze(0)
        
        # Truncate if too long
        if waveform.shape[0] > self.max_samples:
            waveform = waveform[:self.max_samples]
        
        # Get text fields
        transcript = str(row.get('transcript', ''))
        translation = str(row.get('translation', ''))
        duration = float(row.get('duration', waveform.shape[0] / self.sample_rate))
        
        return {
            'audio': waveform,
            'sample_rate': self.sample_rate,
            'transcript': transcript,
            'translation': translation,
            'audio_path': str(audio_path),
            'duration': duration
        }


class VietEngDatasetPreprocessed(Dataset):
    """
    Dataset that loads preprocessed audio features (for faster training).
    
    Use this when audio has been pre-converted to numpy arrays.
    """
    
    def __init__(
        self,
        csv_path: Union[str, Path],
        features_dir: Union[str, Path],
        max_length: int = 480000  # 30s at 16kHz
    ):
        self.csv_path = Path(csv_path)
        self.features_dir = Path(features_dir)
        self.max_length = max_length
        
        self.data = pd.read_csv(self.csv_path)
        logger.info(f"Loaded {len(self.data)} samples (preprocessed)")
        
    def __len__(self) -> int:
        return len(self.data)
    
    def __getitem__(self, idx: int) -> Dict[str, Any]:
        row = self.data.iloc[idx]
        
        # Load preprocessed numpy array
        feature_path = self.features_dir / f"{row['id']}.npy"
        
        if feature_path.exists():
            import numpy as np
            audio = torch.from_numpy(np.load(feature_path))
        else:
            # Fallback to loading from audio
            logger.warning(f"Preprocessed features not found for {row['id']}, loading audio")
            audio = torch.zeros(self.max_length)
        
        return {
            'audio': audio,
            'transcript': str(row.get('transcript', '')),
            'translation': str(row.get('translation', '')),
            'audio_path': str(row.get('audio_path', '')),
            'duration': float(row.get('duration', 0))
        }
