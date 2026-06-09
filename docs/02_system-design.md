# System Design: Vietnamese-English Code-Switching Speech Translation Pipeline

**Version**: 2.0  
**Date**: December 2025  
**Architecture**: 3-Tier Full-Stack (PostgreSQL + FastAPI + React)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Layer](#3-data-layer)
4. [Backend API Layer](#4-backend-api-layer)
5. [Processing Layer](#5-processing-layer)
6. [Frontend Layer](#6-frontend-layer)
7. [Operations Layer](#7-operations-layer)
8. [Security & Concurrency](#8-security--concurrency)
9. [File Structure](#9-file-structure)
10. [Integration Points](#10-integration-points)

---

## 1. Executive Summary

This system creates a 150+ hour Vietnamese-English code-switching speech translation dataset from YouTube content. The pipeline automates audio ingestion, chunking, AI transcription, and human verification.

### Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Database | PostgreSQL | ACID compliance, foreign keys, production-ready |
| ORM | SQLModel | Combines SQLAlchemy + Pydantic for type safety |
| API | FastAPI | Async, OpenAPI docs, modern Python |
| Frontend | React + Vite | Fast dev experience, Wavesurfer.js integration |
| Audio Processing | FFmpeg | Industry standard, 16kHz/mono output |
| AI Transcription | Gemini Flash | Fast, accurate, JSON output mode |
| Auth | X-User-ID Header | Simple "honor system" for trusted team |

### Critical Constraints

> [!IMPORTANT]
> **The "Relative Time" Law**: All timestamps in the database are RELATIVE to chunk start (0-305 seconds). Absolute video time is calculated ONLY during export.

> [!IMPORTANT]
> **The "Ghost Lock" Pattern**: Chunks are locked by user ID with 30-minute expiry. Expired locks are treated as NULL.

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER INTERACTIONS                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────┐         ┌──────────────────────────────────┐     │
│   │ ingest_gui   │         │     React Frontend (5173)        │     │
│   │  (Tkinter)   │         │  ┌──────────┬──────────────────┐ │     │
│   │              │         │  │ Waveform │  Segment Table   │ │     │
│   │  Download    │         │  │ Viewer   │  (MUI DataGrid)  │ │     │
│   │  + Upload    │         │  └──────────┴──────────────────┘ │     │
│   └──────┬───────┘         └─────────────┬────────────────────┘     │
│          │                               │                           │
│          │  HTTP                         │ HTTP (via Vite proxy)    │
│          ▼                               ▼                           │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │                 FastAPI Backend (8000)                    │      │
│   │  ┌──────────────────────────────────────────────────┐    │      │
│   │  │  Routers: /users /videos /chunks /segments       │    │      │
│   │  └──────────────────────────────────────────────────┘    │      │
│   │  ┌─────────────┐  ┌─────────────┐  ┌──────────────┐     │      │
│   │  │ Auth (deps) │  │ Static      │  │ CORS         │     │      │
│   │  │ X-User-ID   │  │ File Server │  │ Middleware   │     │      │
│   │  └─────────────┘  └─────────────┘  └──────────────┘     │      │
│   └──────────────────────────┬───────────────────────────────┘      │
│                              │                                       │
│                              ▼                                       │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │                    PostgreSQL Database                    │      │
│   │  ┌────────┐ ┌─────────┐ ┌────────┐ ┌─────────┐ ┌───────┐│      │
│   │  │ users  │ │channels │ │ videos │ │ chunks  │ │segment││      │
│   │  └────────┘ └─────────┘ └────────┘ └─────────┘ └───────┘│      │
│   └──────────────────────────────────────────────────────────┘      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                     BACKGROUND PROCESSING                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐          │
│   │   Chunker    │    │   Gemini     │    │  Denoiser    │          │
│   │   (FFmpeg)   │───▶│   Worker     │    │(DeepFilterNet)          │
│   │              │    │              │    │              │          │
│   │ 5min/5s      │    │ JSON output  │    │ Flagged      │          │
│   │ overlap      │    │ API rotation │    │ chunks       │          │
│   └──────────────┘    └──────────────┘    └──────────────┘          │
│                                                                      │
│   ┌──────────────────────────────────────────────────────────┐      │
│   │                      Exporter                             │      │
│   │  Overlap resolution → manifest.tsv generation             │      │
│   └──────────────────────────────────────────────────────────┘      │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Layer

### 3.1 Database Schema

```mermaid
erDiagram
    users ||--o{ videos : uploads
    users ||--o{ chunks : locks
    channels ||--o{ videos : contains
    videos ||--o{ chunks : has
    chunks ||--o{ segments : contains

    users {
        int id PK
        string username UK
        enum role
        timestamp created_at
    }

    channels {
        int id PK
        string name
        string url UK
        timestamp created_at
    }

    videos {
        int id PK
        int channel_id FK
        int uploaded_by_id FK
        string title
        int duration_seconds
        string original_url UK
        string file_path
        timestamp created_at
    }

    chunks {
        int id PK
        int video_id FK
        int chunk_index
        string audio_path
        enum status
        enum denoise_status
        int locked_by_user_id FK
        timestamp lock_expires_at
        timestamp created_at
    }

    segments {
        int id PK
        int chunk_id FK
        float start_time_relative
        float end_time_relative
        string transcript
        string translation
        bool is_verified
        bool is_rejected
        timestamp created_at
        timestamp updated_at
    }

    processing_jobs {
        int id PK
        int chunk_id FK
        int video_id FK
        enum status
        int requested_by_user_id FK
        timestamp created_at
        timestamp started_at
        timestamp completed_at
        string error_message
    }
```

### 3.2 Enums

| Enum | Values | Purpose |
|------|--------|---------|
| `UserRole` | ADMIN, ANNOTATOR | Permission levels |
| `ProcessingStatus` | PENDING, PROCESSING, REVIEW_READY, IN_REVIEW, APPROVED, REJECTED | Chunk workflow state |
| `DenoiseStatus` | NOT_NEEDED, FLAGGED, QUEUED, PROCESSED | Audio cleanup state |
| `JobStatus` | QUEUED, PROCESSING, COMPLETED, FAILED | Gemini processing job state |

### 3.3 File: `backend/db/models.py`

SQLModel class definitions with:
- Foreign key relationships
- UNIQUE constraints on `users.username`, `channels.url`, `videos.original_url`
- Default values and timestamps
- Back-populates for ORM relationships

### 3.4 File: `backend/db/engine.py`

- Creates SQLAlchemy engine with connection pooling (`pool_size=5`, `max_overflow=10`)
- `get_session()` dependency for FastAPI
- `resolve_path()` / `get_relative_path()` for file storage

---

## 4. Backend API Layer

### 4.1 FastAPI Application (`backend/main.py`)

| Component | Purpose |
|-----------|---------|
| `lifespan()` | Creates directories, initializes database on startup |
| `CORSMiddleware` | Allows React frontend on port 5173 |
| `StaticFiles` | Serves audio files at `/api/static/` |
| `include_router()` | Mounts 6 routers under `/api` prefix (users, videos, chunks, segments, queue, export) |

### 4.2 Authentication (`backend/auth/deps.py`)

```python
async def get_current_user(
    x_user_id: Optional[int] = Header(None, alias="X-User-ID"),
    session: Session = Depends(get_session)
) -> User:
```

"Honor system" auth - trusts X-User-ID header. Returns 401 if missing or invalid.

### 4.3 API Endpoints

#### Users Router (`backend/routers/users.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/users` | GET | List all annotators |
| `/api/users/{id}` | GET | Get user by ID |

#### Videos Router (`backend/routers/videos.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/videos` | GET | List videos (optional channel filter) |
| `/api/videos/check?url=` | GET | Duplicate detection |
| `/api/videos/{id}` | GET | Get video by ID |
| `/api/videos/upload` | POST | Multipart file upload |
| `/api/channels` | GET | List all channels |
| `/api/channels/{id}` | GET | Get channel by ID |
| `/api/channels` | POST | Create channel |
| `/api/channels/by-url` | GET | Find channel by URL |
| `/api/channels/stats` | GET | Get statistics for all channels |
| `/api/channels/{id}/videos` | GET | Get videos for a channel |
| `/api/stats` | GET | System-wide statistics |

#### Chunks Router (`backend/routers/chunks.py`)

| `/api/chunks` | GET | List chunks (optional filters) |
| `/api/chunks/next` | GET | Work queue - get next available chunk |
| `/api/chunks/{id}` | GET | Get chunk with video info |
| `/api/chunks/{id}/lock` | POST | Acquire 30-min lock |
| `/api/chunks/{id}/unlock` | POST | Release lock |
| `/api/chunks/{id}/flag-noise` | POST | Toggle denoise flag |
| `/api/chunks/{id}/approve` | POST | Approve and release lock |
| `/api/chunks/{id}/retranscript` | POST | Re-queue chunk for Gemini (deletes segments) |
| `/api/videos/{video_id}/chunks` | GET | List chunks for a video with lock info |

#### Segments Router (`backend/routers/segments.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/segments` | GET | List segments (with chunk filter) |
| `/api/chunks/{id}/segments` | GET | Get chunk's segments (ordered by time) |
| `/api/segments/{id}` | GET | Get segment by ID |
| `/api/segments/{id}` | PUT | Update segment text/timestamps |
| `/api/segments` | POST | Create new segment |
| `/api/segments/{id}` | DELETE | Delete segment |
| `/api/segments/{id}/verify` | POST | Toggle verification status |
| `/api/segments/bulk-verify` | POST | Mark multiple segments as verified |
| `/api/segments/bulk-reject` | POST | Mark multiple segments as rejected |

#### Queue Router (`backend/routers/queue.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/queue` | POST | Add videos to processing queue |
| `/api/queue/summary` | GET | Get queue status per video |
| `/api/queue/stream` | GET | SSE endpoint for real-time updates |
| `/api/queue/{video_id}/retry` | POST | Retry failed jobs for a video |
| `/api/queue/stats` | GET | Overall queue statistics |
| `/api/queue/logs` | GET | Get Gemini worker log tail |

#### Export Router (`backend/routers/export.py`)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/export/preview` | GET | Preview export stats (approved chunks, verified segments) |
| `/api/export/run` | POST | Run export and generate manifest.tsv |

---

## 5. Processing Layer

### 5.1 FFmpeg Chunker (`backend/processing/chunker.py`)

**Algorithm**:
```
For a video of duration D seconds:
  Chunk 0: 0s    -> 305s  (5min + 5s overlap)
  Chunk 1: 300s  -> 605s  (5min + 5s overlap)
  Chunk N: N*300 -> (N+1)*300 + 5 seconds
```

**FFmpeg Command**:
```bash
ffmpeg -i input.m4a -ss <start> -t <duration> -ac 1 -ar 16000 -acodec pcm_s16le output.wav
```

**Output**: 16kHz, Mono, 16-bit PCM WAV files

### 5.2 Gemini Worker (`backend/processing/gemini_worker.py`)

**Multi-Model Cascade**:

The worker implements a cascade strategy when API quota is exhausted:

```
1. Try all API keys on gemini-2.5-flash (primary model)
2. If all Flash keys exhausted → switch to gemini-2.5-pro
3. If all Pro keys exhausted → recheck Flash (some may have recovered)
4. If everything exhausted → sleep 15 minutes → restart from step 1
```

**ModelKeyManager Class**:
```python
class ModelKeyManager:
    MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]
    COOLDOWN_MINUTES = 5      # Per (model, key) tuple
    EXHAUSTED_SLEEP_MINUTES = 15
    
    def get_next_available(self) -> Tuple[str, str]:
        # Returns (model_name, api_key) or blocks until available
        ...
    
    def mark_cooling(self, model: str, key: str):
        # Called on 429 error, puts (model, key) on 5-min cooldown
        ...
```

**System Prompt** instructs Gemini to:
- Output JSON array with `start`, `end`, `text`, `translation`
- Use `MM:SS.mmm` timestamp format
- Segment audio into 2-25 second chunks
- Transcribe code-switching accurately

**Error Handling**: On 429 (quota exceeded), immediately rotates to next (model, key) pair

### 5.3 Time Parser (`backend/utils/time_parser.py`)

Bidirectional conversion:
- `parse_timestamp("1:23.456")` → `83.456` (float seconds)
- `format_timestamp(83.456)` → `"01:23.456"`

Supports both `M:SS.mmm` and `H:MM:SS.mmm` formats.

---

### 5.4 Queue Worker (Centralized Processing)

The Gemini worker operates as a **separate long-running process** that polls the `ProcessingJob` table:

**Startup Command**:
```powershell
python -m backend.processing.gemini_worker --queue
```

**Workflow**:
1. Poll `processing_jobs` for `status = QUEUED`
2. Claim job with row-level lock (`skip_locked=True`)
3. Set job status to `PROCESSING`, call Gemini API
4. Insert segments into database
5. Set job to `COMPLETED` or `FAILED`

**SSE Integration**: `/api/queue/stream` pushes real-time updates to PreprocessingPage.

---

## 6. Frontend Layer

### 6.1 React Application Structure

```
frontend/src/
├── main.tsx              # Entry point, dark theme, React Query
├── App.tsx               # Tab navigation, user selector, state management
├── api/
│   └── client.ts             # Shared Axios instance with X-User-ID header
├── pages/
│   ├── DashboardPage.tsx     # System stats, channel list
│   ├── ChannelPage.tsx       # Video list with accordion chunks
│   ├── WorkbenchPage.tsx     # Annotation interface (waveform + segments)
│   ├── PreprocessingPage.tsx # Queue management for Gemini processing
│   ├── ProcessingPage.tsx    # Legacy chunking controls (deprecated)
│   ├── ExportPage.tsx        # Dataset export with overlap resolution
│   └── SettingsPage.tsx      # Users, system info, keyboard shortcuts
├── components/
│   ├── WaveformViewer.tsx    # Wavesurfer.js with regions
│   └── SegmentTable.tsx      # Custom editable table with bulk actions
└── styles/
    └── workbench.css         # Global styles, CSS variables
```

### 6.2 Technology Stack

| Package | Purpose |
|---------|---------|
| `@tanstack/react-query` | Server state management, caching |
| `@mui/material` | UI components, dark theme |
| `wavesurfer.js` | Audio waveform visualization |
| `axios` | HTTP client |

### 6.3 Navigation Flow

```mermaid
flowchart LR
    D[Dashboard] --> C[Channel]
    C --> |Select Video| V[ChannelPage: Video List]
    V --> |Click Chunk| W[WorkbenchPage]
    W --> |Approve| V
    D --> S[Settings]
    D --> P[Processing]
    D --> E[Export]
```

### 6.4 Page Descriptions

| Page | Purpose | Key Features |
|------|---------|-------------|
| **Dashboard** | Overview | System stats, channel list view with pending counts |
| **Channel** | Video browser | Accordion expansion showing chunks, lock status, review buttons |
| **Workbench** | Annotation | 3-zone layout (header, waveform, segment table), bulk verify/reject |
| **Preprocessing** | Queue control | Add videos to queue, monitor progress via SSE, retry failed jobs |
| **Export** | Dataset generation | Preview stats, export to manifest.tsv |
| **Settings** | Configuration | Users list, system info, keyboard shortcuts reference |

### 6.5 WorkbenchPage Layout (3-Zone)

```
┌─────────────────────────────────────────────────────┐
│ HEADER: Video title, chunk info, lock status, save  │
├─────────────────────────────────────────────────────┤
│ WAVEFORM: Audio visualization with segment regions  │
│ ▶ ⏸ 🔊 timeline controls                            │
├─────────────────────────────────────────────────────┤
│ SEGMENT TABLE: Editable transcript/translation      │
│ Columns: ☑ | ▶ | Start | End | Transcript | Trans  │
│ [row 1]                                             │
│ [row 2]                                             │
│ ...                                                 │
└─────────────────────────────────────────────────────┘
```

### 6.6 Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+Space` | Play/Pause audio |
| `Ctrl+←` | Seek backward 5 seconds |
| `Ctrl+→` | Seek forward 5 seconds |
| `Ctrl+D` | Toggle denoise flag |
| `Ctrl+S` | Save changes |

---

## 7. Operations Layer

### 7.1 Ingestion (`ingest_gui.py` + `backend/ingestion/downloader.py`)

**Tkinter GUI Features**:
- URL input with playlist expansion
- User/channel dropdown selection
- Treeview with status column
- Duplicate checking via API
- Batch download with progress

**yt-dlp Configuration**:
```python
{
    'format': 'bestaudio/best',
    # CRITICAL: Use colon (:) syntax, not equals (=)!
    'format_sort': ['lang:vi', 'acodec:aac', 'abr'],
    'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a'}],
    'writeinfojson': True,
}
```

### 7.2 Denoiser (`backend/operations/denoiser.py`)

**Batch Processing**:
1. Query chunks where `denoise_status = FLAGGED`
2. Run DeepFilterNet on each audio file
3. Save as `{original}_denoised.wav`
4. Update `audio_path` in database
5. Set `denoise_status = PROCESSED`

**CLI Usage**:
```bash
python -m backend.operations.denoiser --limit 10
python -m backend.operations.denoiser --status
```

### 7.3 Exporter (`backend/operations/exporter.py`)

**300-Second Guillotine Rule**:

To prevent duplicate data from chunk overlaps (5-second overlap zone at 300-305s), the exporter uses a simple cutoff:
- Segments are clipped at the 300-second boundary
- Each segment is exported as an **individual audio clip** (not a reference to full chunks)
- Audio data is cached in RAM for efficient slicing (~29MB per 5-min WAV, supports 600+ chunks in 20GB RAM)

**Processing Pipeline**:
1. Query all approved chunks with verified segments
2. Load chunk audio into cache (one-time per chunk)
3. Slice individual segments using numpy array operations
4. Write 16kHz mono WAV files to `data/export/segments/`
5. Generate `manifest.tsv` with metadata

**Output**: `data/export/manifest.tsv`

| Column | Description |
|--------|-------------|
| id | Segment ID |
| video_id | Source video |
| audio_path | Relative path to individual segment clip |
| duration | Segment length in seconds |
| transcript | Original code-switched text |
| translation | Vietnamese translation |

> [!NOTE]
> No start/end columns - each clip is self-contained (audio already sliced).

---

## 8. Security & Concurrency

### 8.1 Honor System Auth

Simple X-User-ID header for trusted team:
```
GET /api/chunks/next
X-User-ID: 1
```

No passwords, no JWT. Quick for internal tools.

### 8.2 Ghost Lock Pattern

Prevents concurrent edits:

```python
# Lock acquisition
if chunk.locked_by_user_id is not None:
    if chunk.lock_expires_at > now:
        if chunk.locked_by_user_id != current_user.id:
            raise 409 Conflict
    else:
        # Lock expired, treat as unlocked
        pass

chunk.locked_by_user_id = current_user.id
chunk.lock_expires_at = now + 30 minutes
```

### 8.3 Duplicate Prevention

UNIQUE constraint on `videos.original_url`:
- Check before download: `GET /api/videos/check?url=...`
- Reject on upload if exists: HTTP 409 Conflict

---

## 9. File Structure

```
final_nlp/
├── backend/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app
│   ├── auth/
│   │   └── deps.py               # X-User-ID validation
│   ├── db/
│   │   ├── models.py             # SQLModel tables
│   │   └── engine.py             # PostgreSQL connection
│   ├── routers/
│   │   ├── users.py
│   │   ├── videos.py
│   │   ├── chunks.py
│   │   └── segments.py
│   ├── processing/
│   │   ├── chunker.py            # FFmpeg wrapper
│   │   └── gemini_worker.py      # AI transcription
│   ├── ingestion/
│   │   └── downloader.py         # yt-dlp wrapper
│   ├── operations/
│   │   ├── denoiser.py           # DeepFilterNet
│   │   └── exporter.py           # Manifest generation
│   ├── utils/
│   │   └── time_parser.py        # Timestamp conversion
│   └── alembic/
│       ├── env.py
│       └── versions/
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── pages/
│       │   └── WorkbenchPage.tsx
│       └── components/
│           ├── WaveformViewer.tsx
│           └── SegmentTable.tsx
├── scripts/
│   ├── init_db.py
│   └── start_dev.ps1
├── data/
│   ├── raw/                      # Original .m4a downloads
│   ├── chunks/                   # 5-min WAV segments
│   └── export/                   # Final dataset
├── ingest_gui.py                 # Tkinter ingestion tool
├── requirements.txt
├── alembic.ini
├── .env.example
└── README.md
```

---

## 10. Integration Points

### 10.1 Data Flow

```
YouTube URL
    ↓
ingest_gui.py (yt-dlp download)
    ↓
POST /api/videos/upload
    ↓
chunker.py (FFmpeg → 5min WAV)
    ↓
gemini_worker.py (AI transcription)
    ↓
Database: segments with RELATIVE timestamps
    ↓
React Frontend (human review)
    ↓
POST /api/chunks/{id}/approve
    ↓
exporter.py (overlap resolution)
    ↓
manifest.tsv (ABSOLUTE timestamps)
```

### 10.2 API ↔ Frontend Communication

All API calls go through Vite proxy:
```typescript
// vite.config.ts
proxy: {
  '/api': {
    target: 'http://localhost:8000',
    changeOrigin: true,
  }
}
```

### 10.3 Database ↔ File System

All file paths in database are **relative** to `DATA_ROOT`:
- `videos.file_path`: `"raw/video_20251209_abc123.m4a"`
- `chunks.audio_path`: `"chunks/video_1/chunk_000.wav"`

Resolution: `DATA_ROOT / relative_path`

---

## Appendix: Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/speech_translation_db` | PostgreSQL connection |
| `DATA_ROOT` | `./data` | Root directory for files |
| `GEMINI_API_KEYS` | (required) | Comma-separated API keys |
| `BACKEND_PORT` | `8000` | FastAPI port |
| `FRONTEND_PORT` | `5173` | Vite dev server port |
