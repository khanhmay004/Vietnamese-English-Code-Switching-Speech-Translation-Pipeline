# 01. Project Setup

## Overview
This document outlines the initial setup process for the Vietnamese-English Code-Switching Speech Translation project.

## Prerequisites
- Python 3.8+
- SQLite3

## Installation

1.  **Clone the repository** (if applicable).

2.  **Create a Virtual Environment**:
    It is recommended to use a virtual environment to manage dependencies.
    ```bash
    python -m venv venv
    # Activate on Windows:
    .\venv\Scripts\activate
    # Activate on Linux/Mac:
    source venv/bin/activate
    ```

3.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Initialize Project Structure**:
    Run the setup script to create the necessary directories and the SQLite database.
    ```bash
    python setup_project.py
    ```
    This will create:
    - `dataset/db/cs_corpus.db`: The main database.
    - `dataset/audio/`: Directories for train/test/dev audio splits.
    - `raw_staging/`: Landing zone for raw data.

## Project Structure
The project follows this structure:
```text
project_root/
│
├── raw_staging/            # Landing zone for crawled data
├── dataset/
│   ├── audio/              # Standardized 16kHz mono wav files
│   └── db/                 # SQLite database
├── src/
│   ├── preprocessing/      # Cleaning and cutting scripts
│   ├── training/           # Training scripts
│   └── utils/              # Helper functions
├── docs/                   # Project documentation
└── exports/                # Final export files
```
