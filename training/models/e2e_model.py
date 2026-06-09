"""
E2E Model - Wav2Vec2 + mBART Speech Encoder-Decoder for Speech Translation.

Implements the bidirectional shared model with special task tokens.
"""

import logging
from typing import Dict, Any, Optional, List

import torch
import torch.nn as nn
from transformers import (
    SpeechEncoderDecoderModel,
    Wav2Vec2FeatureExtractor,
    MBart50Tokenizer,
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer
)

logger = logging.getLogger(__name__)


# Special task tokens
TRANSCRIBE_TOKEN = "<2transcribe>"
TRANSLATE_TOKEN = "<2translate>"


class SpeechEncoderDecoderModelWrapper(nn.Module):
    """
    Wrapper for SpeechEncoderDecoderModel that filters out unsupported arguments.
    
    Newer HuggingFace Trainer versions pass `num_items_in_batch` to forward(),
    but MBartForCausalLM (the decoder) doesn't accept it. This wrapper filters
    out such arguments.
    """
    
    def __init__(self, model: SpeechEncoderDecoderModel):
        super().__init__()
        self.model = model
        
    def forward(self, **kwargs):
        # Filter out arguments that the underlying model doesn't accept
        kwargs.pop('num_items_in_batch', None)
        return self.model(**kwargs)
    
    def generate(self, *args, **kwargs):
        return self.model.generate(*args, **kwargs)
    
    def save_pretrained(self, *args, **kwargs):
        return self.model.save_pretrained(*args, **kwargs)
    
    @property
    def config(self):
        return self.model.config
    
    @property
    def encoder(self):
        return self.model.encoder
    
    @property
    def decoder(self):
        return self.model.decoder
    
    @property
    def enc_to_dec_proj(self):
        return getattr(self.model, 'enc_to_dec_proj', None)
    
    @enc_to_dec_proj.setter
    def enc_to_dec_proj(self, value):
        self.model.enc_to_dec_proj = value
    
    def gradient_checkpointing_enable(self, *args, **kwargs):
        return self.model.gradient_checkpointing_enable(*args, **kwargs)
    
    def __getattr__(self, name):
        # Delegate all other attributes to the wrapped model
        try:
            return super().__getattr__(name)
        except AttributeError:
            return getattr(self.model, name)


class E2EModel:
    """
    End-to-End Speech Translation Model.
    
    Combines Wav2Vec2 encoder with mBART decoder for multitask learning.
    
    Args:
        encoder_name: Wav2Vec2 model name
        decoder_name: mBART model name
        add_adapter: Whether to add adapter layer between encoder and decoder
    """
    
    ENCODER_OPTIONS = [
        "facebook/wav2vec2-base",
        "facebook/wav2vec2-large-xlsr-53"
    ]
    
    DECODER_OPTIONS = [
        "facebook/mbart-large-50"
    ]
    
    def __init__(
        self,
        encoder_name: str = "facebook/wav2vec2-large-xlsr-53",
        decoder_name: str = "facebook/mbart-large-50",
        add_adapter: bool = True
    ):
        self.encoder_name = encoder_name
        self.decoder_name = decoder_name
        
        logger.info(f"Building E2E model: {encoder_name} + {decoder_name}")
        
        # Load processors
        # NOTE: Use FeatureExtractor, not Processor, because xlsr-53 doesn't have a tokenizer
        self.audio_processor = Wav2Vec2FeatureExtractor.from_pretrained(encoder_name)
        self.tokenizer = MBart50Tokenizer.from_pretrained(decoder_name)
        
        # Add special tokens
        self._add_special_tokens()
        
        # Build model
        base_model = SpeechEncoderDecoderModel.from_encoder_decoder_pretrained(
            encoder_name,
            decoder_name
        )
        
        # Resize embeddings for new tokens
        base_model.decoder.resize_token_embeddings(len(self.tokenizer))
        
        # Store unwrapped model for configuration
        self._base_model = base_model
        
        # Wrap model to filter out incompatible forward() arguments
        self.model = SpeechEncoderDecoderModelWrapper(base_model)
        
        # Configure model
        self._configure_model()
        
        # Add adapter if requested
        if add_adapter:
            self._add_adapter_layer()
        
        # Log model size
        param_count = sum(p.numel() for p in self.model.parameters())
        trainable_count = sum(p.numel() for p in self.model.parameters() if p.requires_grad)
        logger.info(f"Model built: {param_count/1e6:.1f}M params ({trainable_count/1e6:.1f}M trainable)")
    
    def _add_special_tokens(self) -> None:
        """Add task-specific tokens to tokenizer."""
        special_tokens = {
            'additional_special_tokens': [TRANSCRIBE_TOKEN, TRANSLATE_TOKEN]
        }
        num_added = self.tokenizer.add_special_tokens(special_tokens)
        logger.info(f"Added {num_added} special tokens: {TRANSCRIBE_TOKEN}, {TRANSLATE_TOKEN}")
        
        # Store token IDs for later use
        self.transcribe_token_id = self.tokenizer.convert_tokens_to_ids(TRANSCRIBE_TOKEN)
        self.translate_token_id = self.tokenizer.convert_tokens_to_ids(TRANSLATE_TOKEN)
    
    def _configure_model(self) -> None:
        """Configure encoder-decoder model settings."""
        config = self.model.config
        
        # Decoder settings
        config.decoder_start_token_id = self.tokenizer.lang_code_to_id["vi_VN"]
        config.pad_token_id = self.tokenizer.pad_token_id
        config.eos_token_id = self.tokenizer.eos_token_id
        
        # Encoder settings
        config.encoder.feat_proj_dropout = 0.0
        config.encoder.final_dropout = 0.0
        config.encoder.layerdrop = 0.0
        
        logger.info("Model configured for Vietnamese output")
    
    def _add_adapter_layer(self) -> None:
        """
        Add adapter/bridge layer to align encoder-decoder dimensions.
        
        The adapter projects encoder hidden states to decoder input dimension.
        """
        encoder_dim = self.model.encoder.config.hidden_size
        decoder_dim = self.model.decoder.config.d_model
        
        if encoder_dim != decoder_dim:
            logger.info(f"Adding adapter layer: {encoder_dim} -> {decoder_dim}")
            # The SpeechEncoderDecoderModel handles this internally
            # Set the encoder projection layer
            self.model.enc_to_dec_proj = nn.Linear(encoder_dim, decoder_dim)
    
    def get_model(self) -> SpeechEncoderDecoderModel:
        """Get the underlying model."""
        return self.model
    
    def get_audio_processor(self) -> Wav2Vec2FeatureExtractor:
        """Get audio processor."""
        return self.audio_processor
    
    def get_tokenizer(self) -> MBart50Tokenizer:
        """Get tokenizer."""
        return self.tokenizer
    
    def prepare_for_training(
        self,
        gradient_checkpointing: bool = False,
        freeze_encoder: bool = False,
        freeze_feature_encoder: bool = True
    ) -> None:
        """
        Prepare model for training.
        
        Args:
            gradient_checkpointing: Enable gradient checkpointing (saves VRAM)
            freeze_encoder: Freeze entire encoder (for limited VRAM)
            freeze_feature_encoder: Freeze only feature extractor (recommended)
        """
        if gradient_checkpointing:
            self.model.gradient_checkpointing_enable()
            logger.info("Enabled gradient checkpointing")
        
        if freeze_encoder:
            for param in self.model.encoder.parameters():
                param.requires_grad = False
            logger.info("Froze entire encoder")
        elif freeze_feature_encoder:
            # Freeze only the CNN feature extractor
            self.model.encoder.freeze_feature_encoder()
            logger.info("Froze feature encoder (CNN layers)")
    
    def unfreeze_encoder(self) -> None:
        """Unfreeze encoder for later training stages."""
        for param in self.model.encoder.parameters():
            param.requires_grad = True
        logger.info("Unfroze encoder")
    
    def save(self, output_dir: str) -> None:
        """Save model, processor, and tokenizer."""
        self.model.save_pretrained(output_dir)
        self.audio_processor.save_pretrained(output_dir)
        self.tokenizer.save_pretrained(output_dir)
        logger.info(f"Saved model to {output_dir}")
    
    @classmethod
    def from_pretrained(cls, path: str) -> "E2EModel":
        """Load from saved checkpoint."""
        wrapper = cls.__new__(cls)
        wrapper.model = SpeechEncoderDecoderModel.from_pretrained(path)
        wrapper.audio_processor = Wav2Vec2FeatureExtractor.from_pretrained(path)
        wrapper.tokenizer = MBart50Tokenizer.from_pretrained(path)
        
        # Restore special token IDs
        wrapper.transcribe_token_id = wrapper.tokenizer.convert_tokens_to_ids(TRANSCRIBE_TOKEN)
        wrapper.translate_token_id = wrapper.tokenizer.convert_tokens_to_ids(TRANSLATE_TOKEN)
        
        return wrapper


def create_e2e_trainer(
    model: E2EModel,
    train_dataset,
    eval_dataset,
    data_collator,
    training_args: Seq2SeqTrainingArguments,
    compute_metrics_fn=None
) -> Seq2SeqTrainer:
    """
    Create a Seq2SeqTrainer for E2E model.
    
    Args:
        model: E2EModel instance
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
        tokenizer=model.get_tokenizer(),
        compute_metrics=compute_metrics_fn
    )
