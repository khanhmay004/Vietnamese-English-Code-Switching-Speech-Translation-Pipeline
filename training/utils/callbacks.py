"""
Custom Callbacks for Training Pipeline.

Provides:
- Logging callback
- Early stopping with patience
- Encoder unfreezing callback
"""

import logging
import time
from pathlib import Path
from typing import Dict, Optional

from transformers import TrainerCallback, TrainerState, TrainerControl
from transformers.trainer_utils import IntervalStrategy

logger = logging.getLogger(__name__)


class LoggingCallback(TrainerCallback):
    """
    Callback for detailed logging during training.
    """
    
    def __init__(self, training_logger):
        self.training_logger = training_logger
        self.start_time = None
        self.step_times = []
    
    def on_train_begin(self, args, state, control, **kwargs):
        self.start_time = time.time()
        self.training_logger.info("Training started")
    
    def on_epoch_begin(self, args, state, control, **kwargs):
        epoch = int(state.epoch) if state.epoch else 0
        self.training_logger.log_epoch_start(epoch + 1, args.num_train_epochs)
    
    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None:
            return
        
        step = state.global_step
        loss = logs.get('loss', logs.get('train_loss', 0))
        lr = logs.get('learning_rate', 0)
        
        self.training_logger.log_step(step, loss, lr)
    
    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if metrics is None:
            return
        
        step = state.global_step
        eval_loss = metrics.get('eval_loss', 0)
        
        self.training_logger.log_eval(step, eval_loss, metrics)
    
    def on_train_end(self, args, state, control, **kwargs):
        elapsed = time.time() - self.start_time
        hours = elapsed / 3600
        
        self.training_logger.info(f"Training completed in {hours:.2f} hours")


class EncoderUnfreezeCallback(TrainerCallback):
    """
    Callback to unfreeze encoder after N epochs.
    
    For E2E model: freeze encoder initially for stability,
    then unfreeze for fine-grained tuning.
    """
    
    def __init__(self, unfreeze_after_epochs: int = 1):
        self.unfreeze_after_epochs = unfreeze_after_epochs
        self.unfrozen = False
    
    def on_epoch_begin(self, args, state, control, model=None, **kwargs):
        if self.unfrozen:
            return
        
        current_epoch = int(state.epoch) if state.epoch else 0
        
        if current_epoch >= self.unfreeze_after_epochs:
            # Unfreeze encoder
            if hasattr(model, 'encoder'):
                for param in model.encoder.parameters():
                    param.requires_grad = True
                self.unfrozen = True
                logger.info(f"Unfroze encoder at epoch {current_epoch + 1}")


class MetricsSaveCallback(TrainerCallback):
    """
    Callback to save metrics to JSON after evaluation.
    """
    
    def __init__(self, output_dir: str, experiment_name: str):
        self.output_dir = Path(output_dir)
        self.experiment_name = experiment_name
        self.metrics_history = []
    
    def on_evaluate(self, args, state, control, metrics=None, **kwargs):
        if metrics is None:
            return
        
        record = {
            'step': state.global_step,
            'epoch': state.epoch,
            **metrics
        }
        self.metrics_history.append(record)
    
    def on_train_end(self, args, state, control, **kwargs):
        import json
        
        metrics_dir = self.output_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        
        output_file = metrics_dir / f"{self.experiment_name}_metrics.json"
        
        with open(output_file, 'w') as f:
            json.dump(self.metrics_history, f, indent=2)
        
        logger.info(f"Saved metrics history to {output_file}")


class ConvergenceMonitorCallback(TrainerCallback):
    """
    Monitor training for convergence issues.
    
    Warns if loss is not decreasing.
    """
    
    def __init__(self, patience: int = 500, min_delta: float = 0.01):
        self.patience = patience
        self.min_delta = min_delta
        self.losses = []
        self.warned = False
    
    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs is None:
            return
        
        loss = logs.get('loss', logs.get('train_loss'))
        if loss is None:
            return
        
        self.losses.append(loss)
        
        if len(self.losses) >= self.patience and not self.warned:
            recent = self.losses[-100:]
            earlier = self.losses[-self.patience:-self.patience+100]
            
            if min(recent) > min(earlier) - self.min_delta:
                logger.warning(
                    f"⚠️ WARNING: Loss not improving! "
                    f"Recent min: {min(recent):.4f}, Earlier min: {min(earlier):.4f}"
                )
                self.warned = True
