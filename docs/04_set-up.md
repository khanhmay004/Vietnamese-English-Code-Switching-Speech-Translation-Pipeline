# Project Setup Guide

**Version**: 2.0  
**Last Updated**: 2025-12-13

---

## Overview

This guide covers setup for both **clients** (annotators, video uploaders) and **server administrators**.

```
┌─────────────────────────────────────────────────────────────────┐
│                     WINDOWS 11 SERVER                           │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ PostgreSQL  │  │ FastAPI     │  │ Vite Dev Server         │ │
│  │ Port: 5432  │  │ Port: 8000  │  │ Port: 5173              │ │
│  └─────────────┘  └──────┬──────┘  └────────────┬────────────┘ │
│                          └───────────┬───────────┘              │
│                                      ▼                          │
│                        ┌─────────────────────────┐              │
│                        │ Tailscale (VPN Mesh)    │              │
│                        └─────────────────────────┘              │
└─────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
               Annotator                       Ingestion Client
               (Browser)                       (ingest_gui.py)
```

---

## Part 1: Client Setup

### 1.1 Prerequisites

| Software | Purpose | Installation |
|----------|---------|--------------|
| Tailscale | VPN access to server | [tailscale.com](https://tailscale.com/download) |
| Python 3.10+ | For ingest_gui | [python.org](https://python.org) |
| FFmpeg | Audio processing | `choco install ffmpeg` |

### 1.2 Get Server Access

Contact your team lead for:
1. **Tailscale IP**: `100.64.x.x`
2. **Your username** for the annotation system

> [!IMPORTANT]
> You must have Tailscale installed and connected to the team network.

### 1.3 Access Annotation Interface

1. **Connect to Tailscale** (system tray icon → Connected)
2. **Open browser**: `http://[TAILSCALE_IP]:5173`
3. **Select your user** from the dropdown

### 1.4 Using Ingestion GUI (Video Uploads)

```powershell
# Clone repo and setup
git clone [repo-url] final_nlp && cd final_nlp
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Configure .env
# API_BASE=http://[TAILSCALE_IP]:8000/api

# Run GUI
python ingest_gui.py
```

**Workflow**:
1. Select your user
2. Paste YouTube URLs/playlists
3. Click **Fetch Videos**
4. Click **Check Duplicates**
5. Click **Download Selected**

### 1.5 Client Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | Check Tailscale is connected |
| Duplicate video | Already in database (expected) |
| FFmpeg not found | Install: `choco install ffmpeg` |

---

## Part 2: Server Setup (Admin Only)

### 2.1 Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 4 cores | 8 cores |
| RAM | 8 GB | 16 GB |
| Storage | 100 GB | 500 GB SSD |

### 2.2 Software Prerequisites

```powershell
# Install via Chocolatey
choco install -y python nodejs postgresql15 ffmpeg git tailscale
```

### 2.3 Initial Setup

```powershell
# Clone and setup
cd C:\Projects
git clone [repo-url] final_nlp && cd final_nlp
python -m venv .venv && .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Frontend
cd frontend && npm install && cd ..
```

### 2.4 Database Setup

```powershell
# Create database
psql -U postgres -c "CREATE DATABASE speech_translation_db;"

# Initialize schema
python scripts/init_db.py
```

### 2.5 Environment Configuration

Copy `.env.example` to `.env` and configure:

```ini
DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@localhost:5432/speech_translation_db
DATA_ROOT=C:\Projects\final_nlp\data
GEMINI_API_KEYS=key1,key2,key3
CORS_ORIGINS=http://localhost:5173,http://[TAILSCALE_IP]:5173
```

### 2.6 Tailscale Setup

```powershell
# Get your Tailscale IP
tailscale ip -4
# Share this IP with your team

# Configure firewall
New-NetFirewallRule -DisplayName "FastAPI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
New-NetFirewallRule -DisplayName "Vite" -Direction Inbound -LocalPort 5173 -Protocol TCP -Action Allow
```

### 2.7 Start Services

**Recommended**: Use the unified startup script:

```powershell
.\scripts\start_server.ps1
```

**Manual startup** (3 terminals):

```powershell
# Terminal 1: Backend
.\.venv\Scripts\Activate.ps1
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: Frontend
cd frontend && npm run dev -- --host 0.0.0.0

# Terminal 3: Gemini Worker
.\.venv\Scripts\Activate.ps1
python -m backend.processing.gemini_worker --queue
```

### 2.8 Verify Deployment

```powershell
# Test locally
curl http://localhost:8000/health

# Test from client (on their machine)
curl http://[TAILSCALE_IP]:8000/health
```

---

## Part 3: Data Backup (DVC + Google Drive)

### 3.1 Setup DVC

```powershell
pip install "dvc[gdrive]"
dvc init
dvc remote add -d gdrive gdrive://[FOLDER_ID]
```

### 3.2 Track Data

```powershell
dvc add data/chunks data/raw
git add data/*.dvc data/.gitignore
git commit -m "Track data with DVC"
dvc push
```

### 3.3 Database Backup

```powershell
# Manual backup
pg_dump -U postgres speech_translation_db > backup.sql

# Restore
psql -U postgres speech_translation_db < backup.sql
```

---

## Quick Reference

| Task | Command |
|------|---------|
| Start all services | `.\scripts\start_server.ps1` |
| Start backend | `uvicorn backend.main:app --host 0.0.0.0 --port 8000` |
| Start frontend | `cd frontend && npm run dev -- --host 0.0.0.0` |
| Start worker | `python -m backend.processing.gemini_worker --queue` |
| Get Tailscale IP | `tailscale ip -4` |
| Test backend | `curl http://localhost:8000/health` |
| Backup DB | `pg_dump -U postgres speech_translation_db > backup.sql` |
| Push to DVC | `dvc push` |

---

## Server Troubleshooting

| Issue | Solution |
|-------|----------|
| Port in use | `netstat -ano \| findstr :8000` then `taskkill /PID [PID] /F` |
| PostgreSQL down | `Start-Service postgresql-x64-15` |
| DVC push fails | Re-authorize: `dvc remote modify gdrive --local gdrive_acknowledge_abuse true` |
