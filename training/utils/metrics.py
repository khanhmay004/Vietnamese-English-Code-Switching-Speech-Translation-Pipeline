"""
Metrics Computation for Speech Translation.

Provides WER, CER, BLEU, and CHRF metrics.
"""

import logging
import re
from typing import Dict, List, Tuple, Any

import evaluate
from jiwer import wer, cer

logger = logging.getLogger(__name__)


def normalize_for_eval(text: str) -> str:
    """
    Normalize text for fair evaluation.
    
    Apply to BOTH predictions and references before scoring.
    This ensures punctuation/casing differences don't inflate error rates.
    
    Steps:
        1. Lowercase
        2. Strip punctuation: ,.?!;:"-()[]{}
        3. Collapse whitespace
    
    Args:
        text: Input text
        
    Returns:
        Normalized text
    """
    if not text or not isinstance(text, str):
        return ""
    
    # Lowercase
    text = text.lower()
    
    # Strip punctuation
    text = re.sub(r'[,.?!;:\"\'\-\(\)\[\]\{\}]', '', text)
    
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()


class MetricsComputer:
    """
    Compute ASR and Translation metrics.
    
    Metrics:
        - WER (Word Error Rate): ASR quality
        - CER (Character Error Rate): ASR quality
        - BLEU: Translation quality
        - CHRF: Translation quality (character-level)
    """
    
    def __init__(self):
        self.bleu_metric = evaluate.load("sacrebleu")
        self.chrf_metric = evaluate.load("chrf")
        logger.info("Metrics computer initialized")
    
    def compute_wer(
        self,
        predictions: List[str],
        references: List[str]
    ) -> float:
        """
        Compute Word Error Rate.
        
        Normalizes text before computing to ignore punctuation/case.
        
        Args:
            predictions: List of predicted transcripts
            references: List of reference transcripts
        
        Returns:
            WER as percentage (0-100)
        """
        # Normalize and filter empty strings
        valid_pairs = [
            (normalize_for_eval(p), normalize_for_eval(r)) 
            for p, r in zip(predictions, references)
            if r.strip()
        ]
        
        if not valid_pairs:
            return 0.0
        
        preds, refs = zip(*valid_pairs)
        return wer(list(refs), list(preds)) * 100
    
    def compute_cer(
        self,
        predictions: List[str],
        references: List[str]
    ) -> float:
        """
        Compute Character Error Rate.
        
        Normalizes text before computing to ignore punctuation/case.
        
        Args:
            predictions: List of predicted transcripts
            references: List of reference transcripts
        
        Returns:
            CER as percentage (0-100)
        """
        # Normalize and filter empty strings
        valid_pairs = [
            (normalize_for_eval(p), normalize_for_eval(r))
            for p, r in zip(predictions, references)
            if r.strip()
        ]
        
        if not valid_pairs:
            return 0.0
        
        preds, refs = zip(*valid_pairs)
        return cer(list(refs), list(preds)) * 100
    
    def compute_bleu(
        self,
        predictions: List[str],
        references: List[str]
    ) -> float:
        """
        Compute BLEU score.
        
        Normalizes text before computing.
        
        Args:
            predictions: List of predicted translations
            references: List of reference translations
        
        Returns:
            BLEU score (0-100)
        """
        # Normalize texts
        norm_preds = [normalize_for_eval(p) for p in predictions]
        norm_refs = [normalize_for_eval(r) for r in references]
        
        # sacrebleu expects references as list of lists
        refs_formatted = [[r] for r in norm_refs]
        
        result = self.bleu_metric.compute(
            predictions=norm_preds,
            references=refs_formatted
        )
        
        return result['score']
    
    def compute_chrf(
        self,
        predictions: List[str],
        references: List[str]
    ) -> float:
        """
        Compute CHRF score.
        
        Normalizes text before computing.
        
        Args:
            predictions: List of predicted translations
            references: List of reference translations
        
        Returns:
            CHRF score (0-100)
        """
        # Normalize texts
        norm_preds = [normalize_for_eval(p) for p in predictions]
        norm_refs = [normalize_for_eval(r) for r in references]
        
        refs_formatted = [[r] for r in norm_refs]
        
        result = self.chrf_metric.compute(
            predictions=norm_preds,
            references=refs_formatted
        )
        
        return result['score']
    
    def compute_asr_only(
        self,
        predictions: List[str],
        references: List[str]
    ) -> Dict[str, float]:
        """
        Compute ASR metrics only (WER, CER).
        
        Used for Whisper which only does transcription.
        
        Args:
            predictions: ASR predictions
            references: ASR references
        
        Returns:
            Dictionary with WER and CER
        """
        return {
            'wer': self.compute_wer(predictions, references),
            'cer': self.compute_cer(predictions, references)
        }
    
    def compute_all(
        self,
        asr_predictions: List[str],
        asr_references: List[str],
        st_predictions: List[str],
        st_references: List[str]
    ) -> Dict[str, float]:
        """
        Compute all metrics (ASR + Translation).
        
        Used for E2E model.
        
        Args:
            asr_predictions: ASR predictions
            asr_references: ASR references
            st_predictions: Translation predictions
            st_references: Translation references
        
        Returns:
            Dictionary with all metrics
        """
        return {
            'wer': self.compute_wer(asr_predictions, asr_references),
            'cer': self.compute_cer(asr_predictions, asr_references),
            'bleu': self.compute_bleu(st_predictions, st_references),
            'chrf': self.compute_chrf(st_predictions, st_references)
        }


def create_compute_metrics_fn(tokenizer, metric_type: str = "asr", normalize: bool = True):
    """
    Create a compute_metrics function for HuggingFace Trainer.
    
    Args:
        tokenizer: Model tokenizer
        metric_type: "asr" for WER/CER, "st" for BLEU/CHRF
        normalize: Whether to normalize text before computing metrics
    
    Returns:
        Callable for Trainer
    """
    metrics_computer = MetricsComputer()
    
    def compute_metrics(eval_pred) -> Dict[str, float]:
        predictions, labels = eval_pred
        
        # Decode predictions
        if hasattr(predictions, 'predictions'):
            predictions = predictions.predictions
        
        # Handle different prediction formats
        if len(predictions.shape) > 2:
            predictions = predictions.argmax(-1)
        
        # Replace -100 with pad token
        labels[labels == -100] = tokenizer.pad_token_id
        
        # Clip predictions to valid token IDs (handles out-of-range from added special tokens)
        # This prevents SentencePiece "piece id is out of range" errors
        vocab_size = len(tokenizer)
        predictions = predictions.clip(0, vocab_size - 1)
        labels = labels.clip(0, vocab_size - 1)
        
        # Decode with error handling
        try:
            pred_strs = tokenizer.batch_decode(predictions, skip_special_tokens=True)
            label_strs = tokenizer.batch_decode(labels, skip_special_tokens=True)
        except Exception as e:
            logger.warning(f"Tokenizer decode error: {e}. Using empty strings.")
            pred_strs = [""] * len(predictions)
            label_strs = [""] * len(labels)
        
        # Apply normalization for fair evaluation
        # This ensures punctuation/casing differences don't inflate metrics
        if normalize:
            pred_strs = [normalize_for_eval(s) for s in pred_strs]
            label_strs = [normalize_for_eval(s) for s in label_strs]
        
        if metric_type == "asr":
            return {
                'wer': metrics_computer.compute_wer(pred_strs, label_strs),
                'cer': metrics_computer.compute_cer(pred_strs, label_strs)
            }
        else:  # st
            return {
                'bleu': metrics_computer.compute_bleu(pred_strs, label_strs),
                'chrf': metrics_computer.compute_chrf(pred_strs, label_strs)
            }
    
    return compute_metrics
