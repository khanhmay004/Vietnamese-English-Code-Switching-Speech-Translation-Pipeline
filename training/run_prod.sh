#!/bin/bash
# =============================================================================
# Production Training Pipeline - Linux (H100 SXM 80GB) - Fully Self-Contained
# =============================================================================
# GPU: H100 SXM (80GB VRAM)
# CPU: AMD EPYC 9554 64-core
# Data: 40-50 hours audio
# Models: whisper-medium, wav2vec2-large-xlsr + mbart-large
# Budget: 6-7 hours (target: 3.5 hours)
#
# This script creates its own isolated virtual environment in training/.venv/
# Run from: final_nlp folder (project root)
# =============================================================================

set -e  # Exit on error

echo "=========================================="
echo "  Production Training Pipeline (H100)    "
echo "=========================================="
echo ""

# Record start time
START_TIME=$(date +%s)

# Change to project root (script is in training/, so go up one level)
cd "$(dirname "$0")/.."
echo "[INFO] Working directory: $(pwd)"

# =============================================================================
# GPU CHECK
# =============================================================================

echo "[SYSTEM] Checking GPU..."
nvidia-smi --query-gpu=name,memory.total --format=csv
echo ""

# =============================================================================
# ENVIRONMENT SETUP - Creates isolated venv in training/.venv/
# =============================================================================

# Virtual environment inside training folder (self-contained)
SCRIPT_DIR="$(dirname "$0")"
VENV_DIR="$SCRIPT_DIR/.venv"
REQUIREMENTS_FLAG="$VENV_DIR/.requirements_installed"

# Create virtual environment if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "[SETUP] Creating isolated training environment..."
    python3 -m venv "$VENV_DIR"
    echo "[SETUP] Virtual environment created: $VENV_DIR"
    # Delete requirements flag to force reinstall
    rm -f "$REQUIREMENTS_FLAG"
fi

# Activate the training virtual environment
echo "[SETUP] Activating training environment..."
source "$VENV_DIR/bin/activate"

# Verify we're using the right Python
echo ""
echo "[INFO] Python: $(python --version)"
echo "[INFO] Python path: $(which python)"

# =============================================================================
# DEPENDENCY INSTALLATION
# =============================================================================

if [ ! -f "$REQUIREMENTS_FLAG" ]; then
    echo ""
    echo "[1/6] Installing dependencies..."
    
    echo "[1/6a] Upgrading pip..."
    python -m pip install --upgrade pip -q
    
    echo "[1/6b] Installing PyTorch with CUDA 12.4..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 -q
    
    echo "[1/6c] Installing remaining dependencies..."
    pip install -r training/requirements.txt -q
    
    touch "$REQUIREMENTS_FLAG"
    echo "[1/6] Dependencies installed successfully!"
else
    echo "[1/6] Dependencies already installed"
fi

# Verify PyTorch installation
echo ""
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}'); print(f'[INFO] CUDA Device: {torch.cuda.get_device_name(0)}')"

# =============================================================================
# DATA PREPARATION
# =============================================================================

echo ""
echo "[2/6] Preparing data..."

# Step 1: Preprocess manifest (clean text, filter by duration)
if [ ! -f "data/export/manifest_clean.tsv" ]; then
    echo "[2/6a] Preprocessing manifest..."
    python training/data/preprocess_manifest.py \
        --input data/export/manifest.tsv \
        --output data/export/manifest_clean.tsv
else
    echo "[2/6a] Preprocessed manifest already exists"
fi

# Step 2: Split data
echo "[2/6b] Splitting data..."
python training/data/split_data.py \
    --manifest data/export/manifest_clean.tsv \
    --output_dir data/splits

# Check data sizes
echo ""
echo "[INFO] Data split summary:"
wc -l data/splits/*.csv

# =============================================================================
# TRAINING
# =============================================================================

# Train Whisper
echo ""
echo "=========================================="
echo "[3/6] Training Whisper (medium)"
echo "Estimated time: 50 minutes"
echo "=========================================="
WHISPER_START=$(date +%s)

python training/scripts/train.py --config training/configs/prod_whisper.yaml 2>&1 | tee training/outputs/whisper_training.log

WHISPER_END=$(date +%s)
WHISPER_DURATION=$((WHISPER_END - WHISPER_START))
echo "[INFO] Whisper training completed in $((WHISPER_DURATION / 60)) minutes"

# Train E2E
echo ""
echo "=========================================="
echo "[4/6] Training E2E Model (wav2vec2 + mbart)"
echo "Estimated time: 2 hours"
echo "=========================================="
E2E_START=$(date +%s)

python training/scripts/train.py --config training/configs/prod_e2e.yaml 2>&1 | tee training/outputs/e2e_training.log

E2E_END=$(date +%s)
E2E_DURATION=$((E2E_END - E2E_START))
echo "[INFO] E2E training completed in $((E2E_DURATION / 60)) minutes"

# =============================================================================
# EVALUATION
# =============================================================================

echo ""
echo "[5/6] Evaluating models on test set..."
echo "=========================================="
python training/scripts/run_evaluation.py \
    --model_dir training/outputs/prod_whisper \
    --model_type whisper \
    --output training/outputs/results

python training/scripts/run_evaluation.py \
    --model_dir training/outputs/prod_e2e \
    --model_type e2e \
    --output training/outputs/results

# Generate charts
echo ""
echo "[6/6] Generating high-resolution charts..."
echo "=========================================="
python training/scripts/export_charts.py \
    --results_dir training/outputs/results \
    --logs_dir training/outputs \
    --output training/outputs/charts \
    --dpi 300

# =============================================================================
# COMPLETE
# =============================================================================

# Calculate total time
END_TIME=$(date +%s)
TOTAL_DURATION=$((END_TIME - START_TIME))
HOURS=$((TOTAL_DURATION / 3600))
MINUTES=$(((TOTAL_DURATION % 3600) / 60))

echo ""
echo "=========================================="
echo "  PRODUCTION PIPELINE COMPLETE!          "
echo "=========================================="
echo ""
echo "Total runtime: ${HOURS}h ${MINUTES}m"
echo ""
echo "Training times:"
echo "  - Whisper: $((WHISPER_DURATION / 60)) minutes"
echo "  - E2E:     $((E2E_DURATION / 60)) minutes"
echo ""
echo "Outputs:"
echo "  - Whisper checkpoint: training/outputs/prod_whisper/"
echo "  - E2E checkpoint:     training/outputs/prod_e2e/"
echo "  - Metrics:            training/outputs/results/"
echo "  - Charts:             training/outputs/charts/"
echo "  - Logs:               training/outputs/*.log"
echo ""
echo "Don't forget to download your checkpoints!"
echo ""

# Create summary file
mkdir -p training/outputs
cat << EOF > training/outputs/training_summary.txt
Production Training Summary
===========================
Date: $(date)
Total Runtime: ${HOURS}h ${MINUTES}m

Whisper Training: $((WHISPER_DURATION / 60)) minutes
E2E Training: $((E2E_DURATION / 60)) minutes

GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader)
EOF

echo "Summary saved to training/outputs/training_summary.txt"
