"""
Custom Logger for Training Pipeline.

Provides unified logging to file, console, and TensorBoard.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def setup_logger(
    name: str = "training",
    log_dir: Optional[str] = None,
    log_level: str = "INFO",
    log_to_file: bool = True,
    log_to_console: bool = True
) -> logging.Logger:
    """
    Setup a logger with file and console handlers.
    
    Args:
        name: Logger name
        log_dir: Directory to save log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_to_file: Whether to log to file
        log_to_console: Whether to log to console
    
    Returns:
        Configured logger
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers = []  # Clear existing handlers
    
    # Format
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Console handler
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_to_file and log_dir:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_path / f"{name}_{timestamp}.log"
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        logger.info(f"Logging to file: {log_file}")
    
    return logger


class TrainingLogger:
    """
    High-level training logger with structured output.
    """
    
    def __init__(
        self,
        experiment_name: str,
        output_dir: str,
        log_level: str = "INFO"
    ):
        self.experiment_name = experiment_name
        self.output_dir = Path(output_dir)
        self.log_dir = self.output_dir / "logs"
        
        self.logger = setup_logger(
            name=experiment_name,
            log_dir=str(self.log_dir),
            log_level=log_level
        )
        
        self.step = 0
        self.epoch = 0
        
    def log_config(self, config: dict) -> None:
        """Log configuration at start of training."""
        self.logger.info("=" * 60)
        self.logger.info(f"Experiment: {self.experiment_name}")
        self.logger.info("=" * 60)
        self.logger.info("Configuration:")
        for key, value in config.items():
            if isinstance(value, dict):
                self.logger.info(f"  {key}:")
                for k, v in value.items():
                    self.logger.info(f"    {k}: {v}")
            else:
                self.logger.info(f"  {key}: {value}")
        self.logger.info("=" * 60)
    
    def log_epoch_start(self, epoch: int, total_epochs: int) -> None:
        """Log start of epoch."""
        self.epoch = epoch
        self.logger.info(f"Epoch {epoch}/{total_epochs} started")
    
    def log_step(
        self,
        step: int,
        loss: float,
        lr: float,
        **kwargs
    ) -> None:
        """Log training step."""
        self.step = step
        msg = f"Step {step} | Loss: {loss:.4f} | LR: {lr:.2e}"
        for key, value in kwargs.items():
            if isinstance(value, float):
                msg += f" | {key}: {value:.4f}"
            else:
                msg += f" | {key}: {value}"
        self.logger.info(msg)
    
    def log_eval(
        self,
        step: int,
        eval_loss: float,
        metrics: dict
    ) -> None:
        """Log evaluation results."""
        self.logger.info(f"Eval @ Step {step} | Loss: {eval_loss:.4f}")
        for key, value in metrics.items():
            if isinstance(value, float):
                self.logger.info(f"  {key}: {value:.4f}")
            else:
                self.logger.info(f"  {key}: {value}")
    
    def log_final_results(self, results: dict) -> None:
        """Log final training results."""
        self.logger.info("=" * 60)
        self.logger.info("FINAL RESULTS")
        self.logger.info("=" * 60)
        for key, value in results.items():
            if isinstance(value, float):
                self.logger.info(f"  {key}: {value:.4f}")
            else:
                self.logger.info(f"  {key}: {value}")
        self.logger.info("=" * 60)
    
    def info(self, msg: str) -> None:
        """Log info message."""
        self.logger.info(msg)
    
    def warning(self, msg: str) -> None:
        """Log warning message."""
        self.logger.warning(msg)
    
    def error(self, msg: str) -> None:
        """Log error message."""
        self.logger.error(msg)
