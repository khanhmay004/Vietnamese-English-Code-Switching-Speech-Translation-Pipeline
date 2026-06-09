@echo off
REM =============================================================================
REM Development Training Pipeline - Windows (Fully Self-Contained)
REM =============================================================================
REM GPU: RTX 2050 (4GB) or similar low-VRAM GPU
REM Data: 25 min test set (227 segments)
REM Models: whisper-tiny, wav2vec2-base + mbart-large
REM 
REM This script creates its own isolated virtual environment in training/.venv/
REM Run from: final_nlp folder (project root)
REM =============================================================================

echo ==========================================
echo   Development Training Pipeline (Windows)
echo ==========================================
echo.

REM Change to project root (script is in training/, so go up one level)
cd /d "%~dp0\.."
echo [INFO] Working directory: %CD%

REM =============================================================================
REM ENVIRONMENT SETUP - Creates isolated venv in training/.venv/
REM =============================================================================

REM Virtual environment inside training folder (self-contained)
set VENV_DIR=%~dp0.venv
set REQUIREMENTS_FLAG=%VENV_DIR%\.requirements_installed

REM Create virtual environment if it doesn't exist
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo.
    echo [SETUP] Creating isolated training environment...
    python -m venv %VENV_DIR%
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment!
        pause
        exit /b 1
    )
    echo [SETUP] Virtual environment created: %VENV_DIR%
    REM Delete requirements flag to force reinstall
    if exist "%REQUIREMENTS_FLAG%" del "%REQUIREMENTS_FLAG%"
)

REM Activate the training virtual environment
echo [SETUP] Activating training environment...
call %VENV_DIR%\Scripts\activate.bat

REM Verify we're using the right Python
echo.
echo [INFO] Python: 
python --version
echo [INFO] Python path: 
where python

REM =============================================================================
REM DEPENDENCY INSTALLATION
REM =============================================================================

if not exist "%REQUIREMENTS_FLAG%" (
    echo.
    echo [1/6] Installing dependencies...
    
    echo [1/6a] Upgrading pip...
    python -m pip install --upgrade pip -q --no-cache-dir
    
    echo [1/6b] Installing PyTorch with CUDA 12.4...
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124 -q --no-cache-dir
    if errorlevel 1 (
        echo [ERROR] Failed to install PyTorch!
        pause
        exit /b 1
    )
    
    echo [1/6c] Installing remaining dependencies...
    pip install -r training\requirements.txt -q --no-cache-dir
    if errorlevel 1 (
        echo [ERROR] Failed to install requirements!
        pause
        exit /b 1
    )
    
    echo. > "%REQUIREMENTS_FLAG%"
    echo [1/6] Dependencies installed successfully!
) else (
    echo [1/6] Dependencies already installed
)

REM Verify PyTorch installation
echo.
python -c "import torch; print(f'[INFO] PyTorch: {torch.__version__}'); print(f'[INFO] CUDA: {torch.cuda.is_available()}')"

REM =============================================================================
REM DATA PREPARATION
REM =============================================================================

if not exist "data\splits\train.csv" (
    echo.
    echo [2/6] Splitting data...
    python training\data\split_data.py --manifest data\export\manifest.tsv --output_dir data\splits
) else (
    echo [2/6] Data already split
)

REM =============================================================================
REM TRAINING
REM =============================================================================

REM Train Whisper
echo.
echo [3/6] Training Whisper (tiny) - Est: 10 min
echo ----------------------------------------
python training\scripts\train.py --config training\configs\dev_whisper.yaml
if errorlevel 1 goto :error

REM Train E2E
echo.
echo [4/6] Training E2E Model - Est: 20 min
echo ----------------------------------------
python training\scripts\train.py --config training\configs\dev_e2e.yaml
if errorlevel 1 goto :error

REM =============================================================================
REM EVALUATION
REM =============================================================================

echo.
echo [5/6] Evaluating models...
echo ----------------------------------------
python training\scripts\run_evaluation.py --model_dir training\outputs\dev_whisper --model_type whisper --output training\outputs\results
python training\scripts\run_evaluation.py --model_dir training\outputs\dev_e2e --model_type e2e --output training\outputs\results

REM Generate charts
echo.
echo [6/6] Generating charts...
echo ----------------------------------------
python training\scripts\export_charts.py --results_dir training\outputs\results --output training\outputs\charts --dpi 300

REM =============================================================================
REM COMPLETE
REM =============================================================================

echo.
echo ==========================================
echo   DEVELOPMENT PIPELINE COMPLETE!
echo ==========================================
echo.
echo Outputs:
echo   - Checkpoints: training\outputs\dev_whisper\
echo                  training\outputs\dev_e2e\
echo   - Metrics:     training\outputs\results\
echo   - Charts:      training\outputs\charts\
echo.
goto :end

:error
echo.
echo [ERROR] Training failed! Check logs above.
echo.
pause
exit /b 1

:end
pause
