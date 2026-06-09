"""
Chart Export Script for Visualization.

Generates high-resolution charts for academic reporting.

Usage:
    python export_charts.py --results_dir results/ --output charts/
"""

import argparse
import json
from pathlib import Path
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

import numpy as np
import pandas as pd
import seaborn as sns

# Set style
plt.style.use('seaborn-v0_8-whitegrid')
sns.set_palette("husl")


def load_metrics(results_dir: str) -> Dict[str, Dict]:
    """Load metrics from JSON files."""
    results_dir = Path(results_dir)
    metrics = {}
    
    for metrics_file in results_dir.glob("*_metrics.json"):
        model_name = metrics_file.stem.replace("_metrics", "")
        with open(metrics_file, 'r') as f:
            metrics[model_name] = json.load(f)
    
    return metrics


def load_training_logs(logs_dir: str) -> Dict[str, pd.DataFrame]:
    """Load training logs from TensorBoard events or JSON."""
    logs_dir = Path(logs_dir)
    logs = {}
    
    # Try JSON format first
    for json_file in logs_dir.glob("*_metrics.json"):
        model_name = json_file.stem.replace("_metrics", "")
        with open(json_file, 'r') as f:
            data = json.load(f)
        if isinstance(data, list):
            logs[model_name] = pd.DataFrame(data)
    
    return logs


def plot_loss_curve(
    logs: Dict[str, pd.DataFrame],
    output_path: str,
    dpi: int = 300
) -> None:
    """
    Plot training/eval loss curves.
    
    Args:
        logs: Dictionary of training logs per model
        output_path: Path to save chart
        dpi: Chart resolution
    """
    fig, ax = plt.subplots(figsize=(10, 6))
    
    for model_name, log_df in logs.items():
        if 'eval_loss' in log_df.columns and 'step' in log_df.columns:
            ax.plot(
                log_df['step'],
                log_df['eval_loss'],
                label=f'{model_name}',
                linewidth=2
            )
    
    ax.set_xlabel('Training Steps', fontsize=12)
    ax.set_ylabel('Evaluation Loss', fontsize=12)
    ax.set_title('Training Loss Curves', fontsize=14, fontweight='bold')
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def plot_metric_comparison(
    metrics: Dict[str, Dict],
    metric_names: List[str],
    output_path: str,
    title: str,
    dpi: int = 300
) -> None:
    """
    Plot bar chart comparing metrics across models.
    
    Args:
        metrics: Dictionary of metrics per model
        metric_names: List of metric names to plot
        output_path: Path to save chart
        title: Chart title
        dpi: Chart resolution
    """
    models = list(metrics.keys())
    n_metrics = len(metric_names)
    
    fig, ax = plt.subplots(figsize=(10, 6))
    
    x = np.arange(len(models))
    width = 0.8 / n_metrics
    
    colors = sns.color_palette("husl", n_metrics)
    
    for i, metric_name in enumerate(metric_names):
        values = [metrics[model].get(metric_name, 0) for model in models]
        offset = (i - n_metrics/2 + 0.5) * width
        bars = ax.bar(x + offset, values, width, label=metric_name.upper(), color=colors[i])
        
        # Add value labels
        for bar, val in zip(bars, values):
            height = bar.get_height()
            ax.annotate(
                f'{val:.2f}',
                xy=(bar.get_x() + bar.get_width() / 2, height),
                xytext=(0, 3),
                textcoords="offset points",
                ha='center', va='bottom',
                fontsize=9
            )
    
    ax.set_xlabel('Model', fontsize=12)
    ax.set_ylabel('Score', fontsize=12)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xticks(x)
    ax.set_xticklabels(models, fontsize=11)
    ax.legend(fontsize=10)
    ax.grid(True, alpha=0.3, axis='y')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def plot_latency_comparison(
    metrics: Dict[str, Dict],
    output_path: str,
    dpi: int = 300
) -> None:
    """
    Plot latency comparison.
    
    Args:
        metrics: Dictionary of metrics per model
        output_path: Path to save chart
        dpi: Chart resolution
    """
    models = list(metrics.keys())
    latencies = [metrics[model].get('avg_latency_ms', 0) for model in models]
    
    fig, ax = plt.subplots(figsize=(8, 5))
    
    colors = sns.color_palette("coolwarm", len(models))
    bars = ax.barh(models, latencies, color=colors)
    
    # Add value labels
    for bar, val in zip(bars, latencies):
        ax.annotate(
            f'{val:.1f} ms',
            xy=(val, bar.get_y() + bar.get_height() / 2),
            xytext=(5, 0),
            textcoords="offset points",
            ha='left', va='center',
            fontsize=10
        )
    
    ax.set_xlabel('Average Latency (ms)', fontsize=12)
    ax.set_title('Inference Latency Comparison', fontsize=14, fontweight='bold')
    ax.grid(True, alpha=0.3, axis='x')
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def create_summary_table(
    metrics: Dict[str, Dict],
    output_path: str,
    dpi: int = 300
) -> None:
    """
    Create summary table as image.
    
    Args:
        metrics: Dictionary of metrics per model
        output_path: Path to save chart
        dpi: Chart resolution
    """
    # Prepare data
    rows = []
    for model, model_metrics in metrics.items():
        rows.append({
            'Model': model,
            'WER ↓': f"{model_metrics.get('wer', 0):.2f}",
            'CER ↓': f"{model_metrics.get('cer', 0):.2f}",
            'BLEU ↑': f"{model_metrics.get('bleu', 0):.2f}",
            'CHRF ↑': f"{model_metrics.get('chrf', 0):.2f}",
            'Latency (ms)': f"{model_metrics.get('avg_latency_ms', 0):.1f}"
        })
    
    df = pd.DataFrame(rows)
    
    # Create figure
    fig, ax = plt.subplots(figsize=(12, len(rows) * 0.8 + 1))
    ax.axis('off')
    
    # Create table
    table = ax.table(
        cellText=df.values,
        colLabels=df.columns,
        cellLoc='center',
        loc='center',
        colColours=['#4472C4'] * len(df.columns)
    )
    
    # Style table
    table.auto_set_font_size(False)
    table.set_fontsize(11)
    table.scale(1.2, 1.5)
    
    # Header styling
    for j in range(len(df.columns)):
        table[(0, j)].set_text_props(color='white', fontweight='bold')
    
    plt.title('Model Comparison Summary', fontsize=14, fontweight='bold', pad=20)
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, bbox_inches='tight')
    plt.close()
    print(f"Saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Export Training Charts')
    parser.add_argument(
        '--results_dir',
        type=str,
        default='training/outputs/results',
        help='Directory with evaluation results'
    )
    parser.add_argument(
        '--logs_dir',
        type=str,
        default='training/outputs',
        help='Directory with training logs'
    )
    parser.add_argument(
        '--output',
        type=str,
        default='training/outputs/charts',
        help='Output directory for charts'
    )
    parser.add_argument(
        '--dpi',
        type=int,
        default=300,
        help='Chart resolution (DPI)'
    )
    
    args = parser.parse_args()
    
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Loading results from {args.results_dir}")
    metrics = load_metrics(args.results_dir)
    
    if not metrics:
        print("No metrics found!")
        return 1
    
    print(f"Found models: {list(metrics.keys())}")
    
    # Load training logs
    logs = load_training_logs(args.logs_dir)
    
    # Generate charts
    print("\nGenerating charts...")
    
    # 1. Loss curves (if logs available)
    if logs:
        plot_loss_curve(
            logs,
            output_dir / "loss_curves.png",
            dpi=args.dpi
        )
    
    # 2. ASR metrics comparison (WER, CER)
    plot_metric_comparison(
        metrics,
        ['wer', 'cer'],
        output_dir / "asr_comparison.png",
        "ASR Performance (Lower is Better)",
        dpi=args.dpi
    )
    
    # 3. Translation metrics comparison (BLEU, CHRF)
    plot_metric_comparison(
        metrics,
        ['bleu', 'chrf'],
        output_dir / "translation_comparison.png",
        "Translation Performance (Higher is Better)",
        dpi=args.dpi
    )
    
    # 4. Latency comparison
    plot_latency_comparison(
        metrics,
        output_dir / "latency_comparison.png",
        dpi=args.dpi
    )
    
    # 5. Summary table
    create_summary_table(
        metrics,
        output_dir / "model_summary.png",
        dpi=args.dpi
    )
    
    print(f"\n✓ All charts saved to {output_dir}")
    return 0


if __name__ == '__main__':
    exit(main())
