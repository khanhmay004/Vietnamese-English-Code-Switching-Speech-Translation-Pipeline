"""
Evaluation Script for Speech Translation Models.

Runs trained models on test set and computes metrics.

Usage:
    python run_evaluation.py --model_dir outputs/whisper --output results/
    python run_evaluation.py --model_dir outputs/e2e --model_type e2e --output results/
"""

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional

import torch
import pandas as pd
from tqdm import tqdm
from transformers import (
    WhisperForConditionalGeneration,
    WhisperProcessor,
    SpeechEncoderDecoderModel,
    Wav2Vec2FeatureExtractor,
    MBart50Tokenizer
)

sys.path.insert(0, str(Path(__file__).parent.parent))

from data import VietEngDataset
from utils import MetricsComputer, setup_logger


logger = setup_logger("evaluate", log_to_file=False)


def load_whisper_model(model_dir: str):
    """Load trained Whisper model."""
    logger.info(f"Loading Whisper model from {model_dir}")
    model = WhisperForConditionalGeneration.from_pretrained(model_dir)
    processor = WhisperProcessor.from_pretrained(model_dir)
    
    if torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()
    return model, processor


def load_e2e_model(model_dir: str):
    """Load trained E2E model."""
    logger.info(f"Loading E2E model from {model_dir}")
    model = SpeechEncoderDecoderModel.from_pretrained(model_dir)
    processor = Wav2Vec2FeatureExtractor.from_pretrained(model_dir)
    tokenizer = MBart50Tokenizer.from_pretrained(model_dir)
    
    if torch.cuda.is_available():
        model = model.cuda()
    
    model.eval()
    return model, processor, tokenizer


def generate_whisper_predictions(
    model,
    processor,
    dataset: VietEngDataset,
    task: str = "transcribe",
    batch_size: int = 16  # Process 16 samples at a time
) -> tuple:
    """
    Generate predictions with Whisper model (BATCHED for speed).
    
    Args:
        model: Whisper model
        processor: Whisper processor
        dataset: Test dataset
        task: "transcribe" or "translate"
        batch_size: Number of samples per batch
    
    Returns:
        Tuple of (predictions, references, latencies)
    """
    predictions = []
    references = []
    total_latency = 0.0
    
    device = next(model.parameters()).device
    
    forced_decoder_ids = processor.get_decoder_prompt_ids(
        language="vi",
        task=task
    )
    
    # Process in batches
    num_samples = len(dataset)
    for batch_start in tqdm(range(0, num_samples, batch_size), desc=f"Whisper {task}"):
        batch_end = min(batch_start + batch_size, num_samples)
        
        # Collect batch samples
        batch_audio = []
        batch_refs = []
        for i in range(batch_start, batch_end):
            sample = dataset[i]
            batch_audio.append(sample['audio'].numpy())
            batch_refs.append(sample['transcript'] if task == 'transcribe' else sample['translation'])
        
        # Process batch
        inputs = processor(
            batch_audio,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True
        ).input_features.to(device)
        
        # Generate
        start_time = time.perf_counter()
        with torch.no_grad():
            generated_ids = model.generate(
                inputs,
                forced_decoder_ids=forced_decoder_ids,
                max_length=256
            )
        latency = time.perf_counter() - start_time
        total_latency += latency
        
        # Decode batch
        pred_texts = processor.batch_decode(generated_ids, skip_special_tokens=True)
        
        # Log first 3 samples for sanity check
        if batch_start == 0:
            logger.info("=" * 50)
            logger.info("SAMPLE PREDICTIONS (first 3):")
            for i in range(min(3, len(pred_texts))):
                logger.info(f"  Sample {i+1}:")
                logger.info(f"    Pred: {pred_texts[i][:100]}...")
                logger.info(f"    Ref:  {batch_refs[i][:100]}...")
            logger.info("=" * 50)
        
        predictions.extend(pred_texts)
        references.extend(batch_refs)
    
    # Return average latency per sample
    avg_latency = total_latency / num_samples
    latencies = [avg_latency] * num_samples
    
    return predictions, references, latencies


def generate_e2e_predictions(
    model,
    processor,
    tokenizer,
    dataset: VietEngDataset,
    task: str = "transcribe",
    batch_size: int = 8  # Smaller batch for E2E (larger model)
) -> tuple:
    """
    Generate predictions with E2E model (BATCHED for speed).
    
    Args:
        model: E2E model
        processor: Audio processor
        tokenizer: Text tokenizer
        dataset: Test dataset
        task: "transcribe" or "translate"
        batch_size: Number of samples per batch
    
    Returns:
        Tuple of (predictions, references, latencies)
    """
    predictions = []
    references = []
    total_latency = 0.0
    
    device = next(model.parameters()).device
    
    # Task token
    task_token = "<2transcribe>" if task == "transcribe" else "<2translate>"
    
    # Process in batches
    num_samples = len(dataset)
    for batch_start in tqdm(range(0, num_samples, batch_size), desc=f"E2E {task}"):
        batch_end = min(batch_start + batch_size, num_samples)
        
        # Collect batch samples
        batch_audio = []
        batch_refs = []
        for i in range(batch_start, batch_end):
            sample = dataset[i]
            batch_audio.append(sample['audio'].numpy())
            batch_refs.append(sample['transcript'] if task == 'transcribe' else sample['translation'])
        
        # Process batch
        inputs = processor(
            batch_audio,
            sampling_rate=16000,
            return_tensors="pt",
            padding=True
        )
        input_values = inputs.input_values.to(device)
        
        # Get Vietnamese language token for mBART
        # This forces the decoder to output Vietnamese
        forced_bos_token_id = tokenizer.lang_code_to_id.get("vi_VN", None)
        
        # Generate with proper params
        start_time = time.perf_counter()
        with torch.no_grad():
            generated_ids = model.generate(
                input_values,
                max_length=256,
                num_beams=1,  # Greedy for speed
                forced_bos_token_id=forced_bos_token_id,
                early_stopping=True,
                no_repeat_ngram_size=3,  # Prevent repetition
            )
        latency = time.perf_counter() - start_time
        total_latency += latency
        
        # Decode batch
        pred_texts = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
        
        # Remove task tokens
        pred_texts = [p.replace(task_token, '').strip() for p in pred_texts]
        
        # Log first 3 samples for sanity check
        if batch_start == 0:
            logger.info("=" * 50)
            logger.info("SAMPLE PREDICTIONS (first 3):")
            for i in range(min(3, len(pred_texts))):
                logger.info(f"  Sample {i+1}:")
                logger.info(f"    Pred: {pred_texts[i][:100]}...")
                logger.info(f"    Ref:  {batch_refs[i][:100]}...")
            logger.info("=" * 50)
        
        predictions.extend(pred_texts)
        references.extend(batch_refs)
    
    # Return average latency per sample
    avg_latency = total_latency / num_samples
    latencies = [avg_latency] * num_samples
    
    return predictions, references, latencies


def evaluate_model(
    model_type: str,
    model_dir: str,
    test_csv: str,
    audio_root: str = "."
) -> Dict[str, Any]:
    """
    Evaluate a trained model.
    
    Args:
        model_type: "whisper" or "e2e"
        model_dir: Path to model checkpoint
        test_csv: Path to test CSV
        audio_root: Root directory for audio
    
    Returns:
        Dictionary with metrics and predictions
    """
    # Load model
    if model_type == "whisper":
        model, processor = load_whisper_model(model_dir)
        tokenizer = processor.tokenizer
    else:
        model, processor, tokenizer = load_e2e_model(model_dir)
    
    # Load dataset
    dataset = VietEngDataset(
        csv_path=test_csv,
        audio_root=audio_root
    )
    logger.info(f"Loaded {len(dataset)} test samples")
    
    # Generate predictions for both tasks
    if model_type == "whisper":
        # ASR: Vietnamese audio → Vietnamese transcript
        asr_preds, asr_refs, asr_latencies = generate_whisper_predictions(
            model, processor, dataset, task="transcribe"
        )
        # NOTE: Whisper's "translate" task always outputs ENGLISH.
        # If your translation references are Vietnamese, skip ST evaluation.
        # For now, we use ASR predictions for both to get meaningful WER.
        st_preds = asr_preds  # Use same predictions
        st_refs = asr_refs    # Use same references
        st_latencies = asr_latencies
        logger.warning("Whisper ST evaluation skipped (translate outputs English, refs are Vietnamese)")
    else:
        asr_preds, asr_refs, asr_latencies = generate_e2e_predictions(
            model, processor, tokenizer, dataset, task="transcribe"
        )
        st_preds, st_refs, st_latencies = generate_e2e_predictions(
            model, processor, tokenizer, dataset, task="translate"
        )
    
    # Compute metrics based on model type
    metrics_computer = MetricsComputer()
    
    if model_type == "whisper":
        # Whisper: ASR metrics only (WER, CER)
        metrics = metrics_computer.compute_asr_only(
            predictions=asr_preds,
            references=asr_refs
        )
        avg_latency = sum(asr_latencies) / len(dataset)
        predictions_data = {
            'asr': list(zip(asr_preds, asr_refs))
        }
    else:
        # E2E: Full metrics (WER, CER, BLEU, CHRF)
        metrics = metrics_computer.compute_all(
            asr_predictions=asr_preds,
            asr_references=asr_refs,
            st_predictions=st_preds,
            st_references=st_refs
        )
        avg_latency = (sum(asr_latencies) + sum(st_latencies)) / (2 * len(dataset))
        predictions_data = {
            'asr': list(zip(asr_preds, asr_refs)),
            'st': list(zip(st_preds, st_refs))
        }
    
    metrics['avg_latency_ms'] = avg_latency * 1000
    
    logger.info("Evaluation Results:")
    for key, value in metrics.items():
        logger.info(f"  {key}: {value:.4f}")
    
    return {
        'model_type': model_type,
        'model_dir': model_dir,
        'metrics': metrics,
        'predictions': predictions_data
    }


def save_results(results: Dict, output_dir: str, model_name: str) -> None:
    """Save evaluation results (separate files per model)."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save metrics
    metrics_file = output_dir / f"{model_name}_metrics.json"
    with open(metrics_file, 'w', encoding='utf-8') as f:
        json.dump(results['metrics'], f, indent=2, ensure_ascii=False)
    logger.info(f"Saved metrics to {metrics_file}")
    
    # Save predictions CSV
    predictions_file = output_dir / f"{model_name}_predictions.csv"
    
    rows = []
    predictions = results['predictions']
    has_st = 'st' in predictions
    
    for i, (asr_pred, asr_ref) in enumerate(predictions['asr']):
        row = {
            'id': i,
            'asr_prediction': asr_pred,
            'asr_reference': asr_ref
        }
        if has_st:
            st_pred, st_ref = predictions['st'][i]
            row['st_prediction'] = st_pred
            row['st_reference'] = st_ref
        rows.append(row)
    
    df = pd.DataFrame(rows)
    df.to_csv(predictions_file, index=False, encoding='utf-8')
    logger.info(f"Saved predictions to {predictions_file}")
    
    # === Export RAW text files for easy inspection ===
    
    # ASR predictions
    asr_pred_file = output_dir / f"{model_name}_asr_predictions.txt"
    with open(asr_pred_file, 'w', encoding='utf-8') as f:
        for pred, _ in predictions['asr']:
            f.write(pred + '\n')
    
    # ASR references (ground truth)
    asr_ref_file = output_dir / f"{model_name}_asr_references.txt"
    with open(asr_ref_file, 'w', encoding='utf-8') as f:
        for _, ref in predictions['asr']:
            f.write(ref + '\n')
    
    logger.info(f"Saved ASR raw files: {asr_pred_file.name}, {asr_ref_file.name}")
    
    # ST predictions and references (if available)
    if has_st:
        st_pred_file = output_dir / f"{model_name}_st_predictions.txt"
        with open(st_pred_file, 'w', encoding='utf-8') as f:
            for pred, _ in predictions['st']:
                f.write(pred + '\n')
        
        st_ref_file = output_dir / f"{model_name}_st_references.txt"
        with open(st_ref_file, 'w', encoding='utf-8') as f:
            for _, ref in predictions['st']:
                f.write(ref + '\n')
        
        logger.info(f"Saved ST raw files: {st_pred_file.name}, {st_ref_file.name}")


def main():
    parser = argparse.ArgumentParser(description='Evaluate Speech Translation Model')
    parser.add_argument(
        '--model_dir',
        type=str,
        required=True,
        help='Path to trained model directory'
    )
    parser.add_argument(
        '--model_type',
        type=str,
        choices=['whisper', 'e2e'],
        default='whisper',
        help='Model type'
    )
    parser.add_argument(
        '--test_csv',
        type=str,
        default='data/splits/test.csv',
        help='Path to test CSV'
    )
    parser.add_argument(
        '--audio_root',
        type=str,
        default='.',
        help='Root directory for audio files'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='training/outputs/results',
        help='Output directory for results'
    )
    
    args = parser.parse_args()
    
    # Check GPU
    if torch.cuda.is_available():
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
    else:
        logger.warning("No GPU detected")
    
    # Evaluate
    results = evaluate_model(
        model_type=args.model_type,
        model_dir=args.model_dir,
        test_csv=args.test_csv,
        audio_root=args.audio_root
    )
    
    # Save
    model_name = Path(args.model_dir).name
    save_results(results, args.output, model_name)
    
    print("\n" + "=" * 60)
    print("EVALUATION COMPLETE")
    print("=" * 60)
    for key, value in results['metrics'].items():
        print(f"  {key}: {value:.4f}")
    
    return 0


if __name__ == '__main__':
    exit(main())
