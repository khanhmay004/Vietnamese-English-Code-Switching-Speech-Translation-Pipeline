"""
Unified Training Script for Speech Translation.

Supports both Whisper and E2E models with config-driven behavior.

Usage:
    python train.py --config configs/dev_whisper.yaml
    python train.py --config configs/prod_e2e.yaml --resume checkpoint-500
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

import torch
import yaml
from transformers import (
    Seq2SeqTrainingArguments,
    Seq2SeqTrainer,
    set_seed
)

# Add training directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from data import VietEngDataset, WhisperCollator, E2ECollator
from data.split_data import main as split_data_main
from models import WhisperWrapper, E2EModel
from utils import (
    TrainingLogger,
    create_compute_metrics_fn,
    LoggingCallback,
    EncoderUnfreezeCallback,
    MetricsSaveCallback,
    ConvergenceMonitorCallback
)


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load YAML configuration file.
    
    Args:
        config_path: Path to YAML config
    
    Returns:
        Configuration dictionary
    """
    config_path = Path(config_path)
    
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    # Load base config if specified
    if '_base_' in config:
        base_path = config_path.parent / config['_base_']
        with open(base_path, 'r') as f:
            base_config = yaml.safe_load(f)
        
        # Merge: config overrides base
        base_config = deep_merge(base_config, config)
        config = base_config
        del config['_base_']
    
    return config


def deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def setup_datasets(config: Dict, processor, tokenizer=None) -> tuple:
    """
    Setup train/dev datasets.
    
    Returns:
        Tuple of (train_dataset, eval_dataset, collator)
    """
    paths = config.get('paths', {})
    audio_root = paths.get('data_root', '.')
    splits_dir = Path(paths.get('splits_dir', 'data/splits'))
    
    # Ensure splits exist
    if not (splits_dir / 'train.csv').exists():
        print("Splits not found, creating...")
        split_data_main()
    
    # Load datasets
    train_dataset = VietEngDataset(
        csv_path=splits_dir / 'train.csv',
        audio_root=audio_root,
        sample_rate=config.get('audio', {}).get('sample_rate', 16000),
        max_audio_length=config.get('audio', {}).get('max_length_seconds', 30)
    )
    
    eval_dataset = VietEngDataset(
        csv_path=splits_dir / 'dev.csv',
        audio_root=audio_root,
        sample_rate=config.get('audio', {}).get('sample_rate', 16000),
        max_audio_length=config.get('audio', {}).get('max_length_seconds', 30)
    )
    
    # Create collator
    model_config = config.get('model', {})
    task = model_config.get('task', 'both')
    
    if model_config.get('type') == 'whisper':
        collator = WhisperCollator(processor=processor, task=task)
    else:  # e2e
        collator = E2ECollator(
            audio_processor=processor,
            tokenizer=tokenizer,
            task=task
        )
    
    return train_dataset, eval_dataset, collator


def create_training_args(config: Dict, output_dir: str) -> Seq2SeqTrainingArguments:
    """Create Seq2SeqTrainingArguments from config."""
    train_config = config.get('training', {})
    dataloader_config = config.get('dataloader', {})
    
    # Determine precision
    fp16 = train_config.get('fp16', False)
    bf16 = train_config.get('bf16', False)
    
    args = Seq2SeqTrainingArguments(
        output_dir=output_dir,
        
        # Batch size
        per_device_train_batch_size=train_config.get('batch_size', 4),
        per_device_eval_batch_size=train_config.get('batch_size', 4),
        gradient_accumulation_steps=train_config.get('gradient_accumulation_steps', 1),
        
        # Learning rate
        learning_rate=train_config.get('learning_rate', 1e-5),
        lr_scheduler_type=train_config.get('lr_scheduler_type', 'linear'),
        warmup_ratio=train_config.get('warmup_ratio', 0.1),
        weight_decay=train_config.get('weight_decay', 0.01),
        max_grad_norm=train_config.get('max_grad_norm', 1.0),
        
        # Training duration
        num_train_epochs=train_config.get('num_train_epochs', 3),
        max_steps=train_config.get('max_steps', -1),
        
        # Precision
        fp16=fp16,
        bf16=bf16,
        tf32=train_config.get('tf32', False),  # H100 TensorFloat-32 acceleration
        
        # Checkpointing
        gradient_checkpointing=train_config.get('gradient_checkpointing', False),
        
        # Evaluation & Saving
        eval_strategy="steps",
        eval_steps=train_config.get('eval_steps', 200),
        save_strategy="steps",
        save_steps=train_config.get('save_steps', 200),
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        
        # Use pytorch format for E2E model (mBART has shared tensors that safetensors can't handle)
        save_safetensors=False,
        
        # Logging
        logging_steps=train_config.get('logging_steps', 50),
        logging_dir=f"{output_dir}/logs",
        report_to=["tensorboard"],
        
        # DataLoader
        dataloader_num_workers=dataloader_config.get('num_workers', 4),
        dataloader_pin_memory=dataloader_config.get('pin_memory', True),
        
        # CRITICAL: Do not remove custom dataset columns before collation
        remove_unused_columns=False,
        
        # Generation (for Seq2Seq)
        predict_with_generate=True,
        generation_max_length=256,
        
        # Seed
        seed=config.get('training', {}).get('seed', 42),
    )
    
    return args


def train_whisper(config: Dict, resume_from: Optional[str] = None) -> Dict:
    """Train Whisper model."""
    model_config = config.get('model', {})
    output_config = config.get('output', {})
    
    output_dir = output_config.get('dir', 'training/outputs/whisper')
    experiment_name = output_config.get('experiment_name', 'whisper')
    
    # Initialize logger
    logger = TrainingLogger(experiment_name, output_dir)
    logger.log_config(config)
    
    # Load model
    logger.info(f"Loading model: {model_config.get('name', 'openai/whisper-small')}")
    model = WhisperWrapper(
        model_name=model_config.get('name', 'openai/whisper-small'),
        language=model_config.get('language', 'vi'),
        task='transcribe'  # Base task, collator handles multitask
    )
    
    # Prepare for training
    train_config = config.get('training', {})
    model.prepare_for_training(
        gradient_checkpointing=train_config.get('gradient_checkpointing', False),
        freeze_encoder=train_config.get('freeze_encoder', False)
    )
    
    # Setup datasets
    train_dataset, eval_dataset, collator = setup_datasets(
        config,
        processor=model.get_processor()
    )
    
    logger.info(f"Train samples: {len(train_dataset)}, Eval samples: {len(eval_dataset)}")
    
    # Create training arguments
    training_args = create_training_args(config, output_dir)
    
    # Create compute_metrics function
    compute_metrics = create_compute_metrics_fn(
        tokenizer=model.get_processor().tokenizer,
        metric_type='asr'
    )
    
    # Create callbacks
    callbacks = [
        LoggingCallback(logger),
        MetricsSaveCallback(output_dir, experiment_name),
        ConvergenceMonitorCallback()
    ]
    
    # Create trainer
    trainer = Seq2SeqTrainer(
        model=model.get_model(),
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
        tokenizer=model.get_processor().feature_extractor,
        compute_metrics=compute_metrics,
        callbacks=callbacks
    )
    
    # Train
    logger.info("Starting training...")
    train_result = trainer.train(resume_from_checkpoint=resume_from)
    
    # Save final model
    trainer.save_model()
    model.get_processor().save_pretrained(output_dir)
    
    # Log results
    results = {
        'train_loss': train_result.training_loss,
        'train_runtime': train_result.metrics.get('train_runtime', 0),
        'train_samples_per_second': train_result.metrics.get('train_samples_per_second', 0)
    }
    logger.log_final_results(results)
    
    # Save results
    with open(Path(output_dir) / 'train_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results


def train_e2e(config: Dict, resume_from: Optional[str] = None) -> Dict:
    """Train E2E model."""
    model_config = config.get('model', {})
    output_config = config.get('output', {})
    
    output_dir = output_config.get('dir', 'training/outputs/e2e')
    experiment_name = output_config.get('experiment_name', 'e2e')
    
    # Initialize logger
    logger = TrainingLogger(experiment_name, output_dir)
    logger.log_config(config)
    
    # Load model
    logger.info(f"Loading E2E model: {model_config.get('encoder')} + {model_config.get('decoder')}")
    model = E2EModel(
        encoder_name=model_config.get('encoder', 'facebook/wav2vec2-large-xlsr-53'),
        decoder_name=model_config.get('decoder', 'facebook/mbart-large-50'),
        add_adapter=model_config.get('add_adapter', True)
    )
    
    # Prepare for training
    train_config = config.get('training', {})
    model.prepare_for_training(
        gradient_checkpointing=train_config.get('gradient_checkpointing', False),
        freeze_encoder=train_config.get('freeze_encoder', False),
        freeze_feature_encoder=train_config.get('freeze_feature_encoder', True)
    )
    
    # Setup datasets
    train_dataset, eval_dataset, collator = setup_datasets(
        config,
        processor=model.get_audio_processor(),
        tokenizer=model.get_tokenizer()
    )
    
    logger.info(f"Train samples: {len(train_dataset)}, Eval samples: {len(eval_dataset)}")
    
    # Create training arguments
    training_args = create_training_args(config, output_dir)
    
    # Create compute_metrics function
    compute_metrics = create_compute_metrics_fn(
        tokenizer=model.get_tokenizer(),
        metric_type='st'
    )
    
    # Create callbacks
    callbacks = [
        LoggingCallback(logger),
        MetricsSaveCallback(output_dir, experiment_name),
        ConvergenceMonitorCallback()
    ]
    
    # Add encoder unfreeze callback if configured
    freeze_encoder_epochs = train_config.get('freeze_encoder_epochs', 0)
    if freeze_encoder_epochs > 0:
        callbacks.append(EncoderUnfreezeCallback(freeze_encoder_epochs))
    
    # Create trainer
    trainer = Seq2SeqTrainer(
        model=model.get_model(),
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=collator,
        tokenizer=model.get_tokenizer(),
        compute_metrics=compute_metrics,
        callbacks=callbacks
    )
    
    # Train
    logger.info("Starting training...")
    train_result = trainer.train(resume_from_checkpoint=resume_from)
    
    # Save final model (includes processor and tokenizer)
    # NOTE: We must save the underlying model explicitly because Trainer
    # saves the wrapper, which may not include the full config.json
    model.save(output_dir)
    
    # Log results
    results = {
        'train_loss': train_result.training_loss,
        'train_runtime': train_result.metrics.get('train_runtime', 0),
        'train_samples_per_second': train_result.metrics.get('train_samples_per_second', 0)
    }
    logger.log_final_results(results)
    
    # Save results
    with open(Path(output_dir) / 'train_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    return results


def main():
    parser = argparse.ArgumentParser(description='Train Speech Translation Model')
    parser.add_argument(
        '--config',
        type=str,
        required=True,
        help='Path to YAML config file'
    )
    parser.add_argument(
        '--resume',
        type=str,
        default=None,
        help='Resume from checkpoint path'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug mode'
    )
    parser.add_argument(
        '--dry_run',
        action='store_true',
        help='Validate config without training'
    )
    
    args = parser.parse_args()
    
    # Load config
    print(f"Loading config: {args.config}")
    config = load_config(args.config)
    
    if args.dry_run:
        print("Config loaded successfully:")
        print(yaml.dump(config, default_flow_style=False))
        return 0
    
    # Set seed
    seed = config.get('training', {}).get('seed', 42)
    set_seed(seed)
    print(f"Random seed: {seed}")
    
    # Check GPU
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1e9
        print(f"GPU: {gpu_name} ({gpu_mem:.1f}GB)")
    else:
        print("WARNING: No GPU detected, training will be slow")
    
    # Train based on model type
    model_type = config.get('model', {}).get('type', 'whisper')
    
    if model_type == 'whisper':
        results = train_whisper(config, resume_from=args.resume)
    elif model_type == 'e2e':
        results = train_e2e(config, resume_from=args.resume)
    else:
        print(f"Unknown model type: {model_type}")
        return 1
    
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE")
    print("=" * 60)
    print(f"Final loss: {results.get('train_loss', 'N/A'):.4f}")
    print(f"Runtime: {results.get('train_runtime', 0)/3600:.2f} hours")
    
    return 0


if __name__ == '__main__':
    exit(main())
