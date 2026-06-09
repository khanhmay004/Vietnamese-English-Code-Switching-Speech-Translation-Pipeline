"""
Data Collators for Speech Translation Training.

Provides:
- WhisperCollator: For Whisper model training (ASR + ST)
- E2ECollator: For Wav2Vec2+mBART multitask training
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Union

import torch
from transformers import (
    WhisperProcessor,
    Wav2Vec2FeatureExtractor,
    MBart50Tokenizer
)

logger = logging.getLogger(__name__)


@dataclass
class WhisperCollator:
    """
    Data collator for Whisper multitask training.
    
    For each sample, creates two training examples:
    1. ASR: Audio -> Transcript (task="transcribe")
    2. ST: Audio -> Translation (task="translate")
    
    Args:
        processor: WhisperProcessor instance
        task: "transcribe", "translate", or "both" (multitask)
        language: Source language code (default: "vi")
        max_length: Maximum label length
    """
    processor: WhisperProcessor
    task: str = "both"
    language: str = "vi"
    max_length: int = 448
    
    def __call__(self, features: List[Dict[str, Any]]) -> Dict[str, torch.Tensor]:
        # Collect audio samples
        audio_samples = [f['audio'].numpy() for f in features]
        
        # Process audio - Whisper expects 30s (3000 mel frames) fixed-length input
        # Use padding="max_length" to ensure consistent 30s length
        batch = self.processor(
            audio_samples,
            sampling_rate=16000,
            return_tensors="pt",
            padding="max_length",  # Pad to 30 seconds
            truncation=True,       # Truncate if longer
            max_length=480000      # 30s * 16kHz
        )
        
        if self.task == "both":
            # Multitask: duplicate each sample for both tasks
            return self._collate_multitask(features, batch)
        else:
            # Single task
            return self._collate_single_task(features, batch)
    
    def _collate_single_task(
        self, 
        features: List[Dict[str, Any]], 
        batch: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """Collate for single task (ASR or ST)."""
        if self.task == "transcribe":
            texts = [f['transcript'] for f in features]
        else:  # translate
            texts = [f['translation'] for f in features]
        
        # Tokenize labels
        labels = self.processor.tokenizer(
            texts,
            max_length=self.max_length,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )
        
        # Replace padding token id with -100 for loss calculation
        labels_ids = labels['input_ids']
        labels_ids[labels_ids == self.processor.tokenizer.pad_token_id] = -100
        
        batch['labels'] = labels_ids
        
        return batch
    
    def _collate_multitask(
        self, 
        features: List[Dict[str, Any]], 
        batch: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """
        Collate for multitask learning.
        
        Each audio sample produces 2 training examples:
        - One with transcript as target (ASR)
        - One with translation as target (ST)
        
        NOTE: We create completely independent copies of the input features
        to avoid gradient checkpointing issues during backward pass.
        """
        input_features = batch['input_features']
        
        # Create two completely independent copies of input features
        # Using contiguous().clone() ensures no shared memory or computation graph
        features_asr = input_features.contiguous().clone()
        features_st = input_features.contiguous().clone()
        
        # Concatenate independent copies
        doubled_input = torch.cat([features_asr, features_st], dim=0)
        
        # Prepare text targets
        transcripts = [f['transcript'] for f in features]
        translations = [f['translation'] for f in features]
        all_texts = transcripts + translations
        
        # Tokenize all labels
        labels = self.processor.tokenizer(
            all_texts,
            max_length=self.max_length,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )
        
        labels_ids = labels['input_ids']
        labels_ids[labels_ids == self.processor.tokenizer.pad_token_id] = -100
        
        return {
            'input_features': doubled_input,
            'labels': labels_ids
        }


@dataclass
class E2ECollator:
    """
    Data collator for Wav2Vec2+mBART E2E multitask training.
    
    Uses special task tokens:
    - <2transcribe>: ASR task
    - <2translate>: ST task
    
    Args:
        audio_processor: Wav2Vec2FeatureExtractor instance
        tokenizer: MBart50Tokenizer instance
        task: "transcribe", "translate", or "both"
        max_input_length: Maximum audio samples (16kHz * seconds)
        max_label_length: Maximum label tokens
    """
    audio_processor: Wav2Vec2FeatureExtractor
    tokenizer: MBart50Tokenizer
    task: str = "both"
    max_input_length: int = 480000  # 30 seconds at 16kHz
    max_label_length: int = 256
    
    # Special tokens (will be added to tokenizer)
    TRANSCRIBE_TOKEN = "<2transcribe>"
    TRANSLATE_TOKEN = "<2translate>"
    
    def __call__(self, features: List[Dict[str, Any]]) -> Dict[str, torch.Tensor]:
        # Process audio
        audio_samples = [f['audio'].numpy() for f in features]
        
        # Pad/truncate audio
        processed = self.audio_processor(
            audio_samples,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True,
            max_length=self.max_input_length,
            truncation=True
        )
        
        if self.task == "both":
            return self._collate_multitask(features, processed)
        else:
            return self._collate_single_task(features, processed)
    
    def _collate_single_task(
        self, 
        features: List[Dict[str, Any]], 
        processed: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """Collate for single task."""
        if self.task == "transcribe":
            prefix = self.TRANSCRIBE_TOKEN
            texts = [f['transcript'] for f in features]
        else:
            prefix = self.TRANSLATE_TOKEN
            texts = [f['translation'] for f in features]
        
        # Add task prefix to labels
        prefixed_texts = [f"{prefix} {text}" for text in texts]
        
        # Tokenize
        labels = self.tokenizer(
            prefixed_texts,
            max_length=self.max_label_length,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )
        
        labels_ids = labels['input_ids']
        labels_ids[labels_ids == self.tokenizer.pad_token_id] = -100
        
        return {
            'input_values': processed['input_values'],
            'attention_mask': processed.get('attention_mask'),
            'labels': labels_ids
        }
    
    def _collate_multitask(
        self, 
        features: List[Dict[str, Any]], 
        processed: Dict[str, torch.Tensor]
    ) -> Dict[str, torch.Tensor]:
        """
        Multitask collation: each sample produces 2 training examples.
        """
        batch_size = processed['input_values'].shape[0]
        
        # Double input features
        # IMPORTANT: Clone to avoid gradient checkpointing backward issues
        doubled_input = torch.cat([
            processed['input_values'], 
            processed['input_values'].clone()
        ], dim=0)
        
        doubled_attention = None
        if processed.get('attention_mask') is not None:
            doubled_attention = torch.cat([
                processed['attention_mask'],
                processed['attention_mask'].clone()
            ], dim=0)
        
        # Prepare labels: first half transcripts with <2transcribe>, second half translations with <2translate>
        transcripts = [f"{self.TRANSCRIBE_TOKEN} {f['transcript']}" for f in features]
        translations = [f"{self.TRANSLATE_TOKEN} {f['translation']}" for f in features]
        all_texts = transcripts + translations
        
        labels = self.tokenizer(
            all_texts,
            max_length=self.max_label_length,
            padding=True,
            truncation=True,
            return_tensors="pt"
        )
        
        labels_ids = labels['input_ids']
        labels_ids[labels_ids == self.tokenizer.pad_token_id] = -100
        
        result = {
            'input_values': doubled_input,
            'labels': labels_ids
        }
        
        if doubled_attention is not None:
            result['attention_mask'] = doubled_attention
        
        return result


def get_collator(
    model_type: str,
    processor: Any,
    tokenizer: Optional[Any] = None,
    task: str = "both"
) -> Union[WhisperCollator, E2ECollator]:
    """
    Factory function to get appropriate collator.
    
    Args:
        model_type: "whisper" or "e2e"
        processor: Model processor
        tokenizer: Tokenizer (required for e2e)
        task: "transcribe", "translate", or "both"
    
    Returns:
        Appropriate collator instance
    """
    if model_type == "whisper":
        return WhisperCollator(processor=processor, task=task)
    elif model_type == "e2e":
        if tokenizer is None:
            raise ValueError("tokenizer required for e2e model")
        return E2ECollator(audio_processor=processor, tokenizer=tokenizer, task=task)
    else:
        raise ValueError(f"Unknown model type: {model_type}")
