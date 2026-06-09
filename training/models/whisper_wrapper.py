"""
Whisper Model Wrapper for Speech Translation Training.

Provides a clean interface for fine-tuning Whisper on ASR and ST tasks.
"""

import logging
from typing import Dict, Any, Optional

import torch
from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer
)

logger = logging.getLogger(__name__)


class WhisperWrapper:
    """
    Wrapper for Whisper model fine-tuning.
    
    Args:
        model_name: HuggingFace model name (e.g., "openai/whisper-small")
        language: Source language code (default: "vi" for Vietnamese)
        task: "transcribe" or "translate"
    """
    
    SUPPORTED_MODELS = [
        "openai/whisper-tiny",
        "openai/whisper-base", 
        "openai/whisper-small",
        "openai/whisper-medium",
        "openai/whisper-large-v3"
    ]
    
    def __init__(
        self,
        model_name: str = "openai/whisper-small",
        language: str = "vi",
        task: str = "transcribe"
    ):
        self.model_name = model_name
        self.language = language
        self.task = task
        
        logger.info(f"Loading Whisper model: {model_name}")
        
        # Load processor
        self.processor = WhisperProcessor.from_pretrained(model_name)
        
        # Load model
        self.model = WhisperForConditionalGeneration.from_pretrained(model_name)
        
        # Configure for language
        self.model.config.forced_decoder_ids = self.processor.get_decoder_prompt_ids(
            language=language, 
            task=task
        )
        self.model.config.suppress_tokens = []
        
        # Get model size info
        param_count = sum(p.numel() for p in self.model.parameters())
        trainable_count = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        
        logger.info(f"Model loaded: {param_count/1e6:.1f}M params ({trainable_count/1e6:.1f}M trainable)")
    
    def get_model(self) -> WhisperForConditionalGeneration:
        """Get the underlying model."""
        return self.model
    
    def get_processor(self) -> WhisperProcessor:
        """Get the processor."""
        return self.processor
    
    def prepare_for_training(
        self,
        gradient_checkpointing: bool = False,
        freeze_encoder: bool = False
    ) -> None:
        """
        Prepare model for training.
        
        Args:
            gradient_checkpointing: Enable gradient checkpointing (saves VRAM)
            freeze_encoder: Freeze encoder weights (for limited VRAM)
        """
        if gradient_checkpointing:
            self.model.gradient_checkpointing_enable()
            logger.info("Enabled gradient checkpointing")
        
        if freeze_encoder:
            for param in self.model.model.encoder.parameters():
                param.requires_grad = False
            logger.info("Froze encoder weights")
    
    def save(self, output_dir: str) -> None:
        """Save model and processor."""
        self.model.save_pretrained(output_dir)
        self.processor.save_pretrained(output_dir)
        logger.info(f"Saved model to {output_dir}")
    
    @classmethod
    def from_pretrained(cls, path: str, **kwargs) -> "WhisperWrapper":
        """Load from saved checkpoint."""
        wrapper = cls.__new__(cls)
        wrapper.processor = WhisperProcessor.from_pretrained(path)
        wrapper.model = WhisperForConditionalGeneration.from_pretrained(path)
        wrapper.language = kwargs.get("language", "vi")
        wrapper.task = kwargs.get("task", "transcribe")
        return wrapper


def create_whisper_trainer(
    model: WhisperWrapper,
    train_dataset,
    eval_dataset,
    data_collator,
    training_args: Seq2SeqTrainingArguments,
    compute_metrics_fn=None
) -> Seq2SeqTrainer:
    """
    Create a Seq2SeqTrainer for Whisper.
    
    Args:
        model: WhisperWrapper instance
        train_dataset: Training dataset
        eval_dataset: Evaluation dataset
        data_collator: Data collator
        training_args: Training arguments
        compute_metrics_fn: Metrics computation function
    
    Returns:
        Configured Seq2SeqTrainer
    """
    return Seq2SeqTrainer(
        model=model.get_model(),
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
        tokenizer=model.get_processor().feature_extractor,
        compute_metrics=compute_metrics_fn
    )
