import sqlite3
import logging
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent

DIRECTORIES = [
    "raw_staging",
    "dataset/audio/train",
    "dataset/audio/test",
    "dataset/audio/dev",
    "dataset/db",
    "src/preprocessing",
    "src/training",
    "src/utils",
    "exports",
]

DB_PATH = PROJECT_ROOT / "dataset" / "db" / "cs_corpus.db"

def create_directories():
    """Creates the project directory structure."""
    logger.info("Initializing project structure...")
    for dir_path in DIRECTORIES:
        path = PROJECT_ROOT / dir_path
        try:
            path.mkdir(parents=True, exist_ok=True)
            logger.info(f"Verified/Created: {path}")
        except Exception as e:
            logger.error(f"Failed to create {path}: {e}")

def init_database():
    """Initializes the SQLite database with the required schema."""
    logger.info(f"Initializing database at {DB_PATH}...")
    
    create_sources_table = """
    CREATE TABLE IF NOT EXISTS sources (
        source_id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_type TEXT NOT NULL,
        original_url TEXT,
        collection_date TEXT
    );
    """

    create_utterances_table = """
    CREATE TABLE IF NOT EXISTS utterances (
        utterance_id TEXT PRIMARY KEY,
        source_id INTEGER,
        audio_path TEXT NOT NULL,
        transcript_cs TEXT,
        translation_vn TEXT,
        duration_sec REAL,
        cs_ratio REAL,
        split_group TEXT CHECK(split_group IN ('train', 'test', 'dev')),
        review_status TEXT DEFAULT 'pending' CHECK(review_status IN ('pending', 'approved', 'rejected', 'needs_fix')),
        FOREIGN KEY (source_id) REFERENCES sources (source_id)
    );
    """

    try:
        # Ensure the directory exists before connecting
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(create_sources_table)
            cursor.execute(create_utterances_table)
            conn.commit()
            logger.info("Database schema initialized successfully.")
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")

def main():
    create_directories()
    init_database()
    logger.info("Project setup complete.")

if __name__ == "__main__":
    main()
