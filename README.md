# Vietnamese-English Code-Switching Speech Translation Pipeline

A full-stack system for creating a 150+ hour Vietnamese-English code-switching speech translation dataset, featuring an annotation workbench and model training infrastructure.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           DATA FACTORY                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  Ingestion → Processing → Annotation → Export → Training                │
│  (yt-dlp)   (FFmpeg+AI)   (React UI)   (JSONL)   (Wav2Vec2/Whisper)    │
└─────────────────────────────────────────────────────────────────────────┘
```

| Layer | Technology | Description |
|-------|------------|-------------|
| Frontend | React + Vite + Wavesurfer.js | Waveform annotation workbench |
| Backend | FastAPI + SQLModel | REST API with PostgreSQL |
| Processing | FFmpeg + Gemini AI | Audio chunking and transcription |
| Training | PyTorch + HuggingFace | Wav2Vec2+mBART E2E, Whisper fine-tuning |
| Storage | PostgreSQL + DVC | Metadata and versioned audio data |

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+
- PostgreSQL 15+
- FFmpeg (in PATH)
- CUDA 12.x (for training, optional for annotation)

### 1. Database Setup
```sql
CREATE DATABASE speech_translation_db;
```

### 2. Environment Configuration
```bash
cp .env.example .env
# Edit .env with your PostgreSQL credentials and Gemini API keys
```

### 3. Backend Setup
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python scripts/init_db.py
uvicorn backend.main:app --reload --port 8000
```

### 4. Frontend Setup
```powershell
cd frontend
npm install
npm run dev
```

### 5. Access
- **Annotation Workbench**: http://localhost:5173
- **API Documentation**: http://localhost:8000/docs

---

## Training Module

The training module is isolated with its own environment for GPU-intensive model training.

### Training Setup
```powershell
cd training
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### Models
- **E2E Model**: Wav2Vec2 encoder → Linear Adapter → mBART-50 decoder
- **Whisper**: Fine-tuned OpenAI Whisper for Vietnamese ASR

### Configuration
Training configs are in `training/configs/`:
- `dev_e2e.yaml` - Local development (RTX 2050, 25min data)
- `prod_e2e.yaml` - Production training (H100, full dataset)

### Analysis
Post-training analysis is available in `training/training_analysis.ipynb`.

---

## Project Structure

```
├── backend/
│   ├── db/              # SQLModel models, database engine
│   ├── routers/         # FastAPI endpoints (videos, chunks, segments)
│   ├── processing/      # FFmpeg chunking, Gemini transcription
│   ├── operations/      # DeepFilterNet denoising, export
│   └── auth/            # X-User-ID authentication
├── frontend/
│   └── src/
│       ├── components/  # WaveformViewer, SegmentTable
│       └── pages/       # Dashboard, Annotation, Settings
├── training/
│   ├── configs/         # YAML training configurations
│   ├── models/          # E2E and Whisper model definitions
│   ├── scripts/         # Training and evaluation scripts
│   └── outputs/         # Checkpoints and results (gitignored)
├── scripts/
│   ├── init_db.py       # Database initialization
│   └── start_dev.ps1    # Development startup script
├── docs/
│   ├── 02_system-design.md
│   ├── 03_workflow.md
│   └── 05_model-training.md
└── data/                # Audio files (gitignored, DVC-tracked)
    ├── raw/             # Original downloads
    └── chunks/          # 5-min WAV segments
```

## Data Pipeline Workflow

1. **Ingest** - Download YouTube audio via `ingest_gui.py` or API
2. **Chunk** - FFmpeg splits into 5-min segments with 5s overlap
3. **Transcribe** - Gemini AI generates initial Vietnamese transcription
4. **Annotate** - Human reviewers verify/edit in React workbench
5. **Export** - Generate `manifest.tsv` for model training
6. **Train** - Fine-tune E2E or Whisper models on annotated data

## Documentation

Detailed documentation is available in the `docs/` directory:
- [System Design](docs/02_system-design.md) - Architecture and data integrity
- [Workflow](docs/03_workflow.md) - Annotation and processing pipelines
- [Model Training](docs/05_model-training.md) - Training configurations and results

## Environment Variables

See `.env.example` for all configuration options including:
- PostgreSQL connection settings
- Gemini API keys (supports key rotation)
- Audio processing parameters
- CORS and networking configuration
