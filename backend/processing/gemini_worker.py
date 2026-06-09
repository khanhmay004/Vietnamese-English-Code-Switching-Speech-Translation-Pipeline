"""
Gemini AI Worker for Audio Transcription.

Sends audio chunks to Gemini for transcription and translation.
Supports multi-model cascade (Flash → Pro) when quota is exhausted.
Handles JSON parsing, timestamp conversion, and smart API key rotation.

Output Schema:
    [
        {
            "start": "00:00.000",
            "end": "00:05.123",
            "text": "Hello các bạn...",
            "translation": "Xin chào các bạn..."
        }
    ]
"""

import os
import re
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

# Load .env file BEFORE importing anything else that uses env vars
from dotenv import load_dotenv
load_dotenv()

import google.generativeai as genai
from sqlmodel import Session, select

from backend.db.engine import engine, DATA_ROOT
from backend.db.models import Chunk, Segment, ProcessingStatus, ProcessingJob, JobStatus
from backend.utils.time_parser import parse_timestamp


logger = logging.getLogger(__name__)


# =============================================================================
# CONSTANTS (from environment)
# =============================================================================

DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_PROMPT = """You are a Senior Linguistic Data Specialist and expert audio transcriptionist focusing on Vietnamese-English Code-Switching (VECS).

Your role is to process audio files into precise, machine-readable datasets for high-fidelity subtitling. You possess a perfect understanding of Vietnamese dialects, English slang, and technical terminology.

Your core operating principles are:
1. PRECISION: Timestamps must be accurate to the millisecond relative to the start of the file.
2. INTEGRITY: Transcription must be verbatim. No summarization, no censorship.
3. TONALITY PRESERVATION: Your translations must adapt English terms into Vietnamese while strictly maintaining the speaker's original register, emotion, and sentence-final particles (e.g., á, nè, nhỉ, ha)."""

USER_PROMPT = """Your task is to transcribe the attached audio file and output the data according to the provided JSON schema.

<context>
The output will be used for subtitles for a Vietnamese audience. The goal is to make the content understandable (translating English) without losing the "soul" of the original speech. The translation must feel like the speaker switched to Vietnamese naturally, retaining all their original sass, anger, or excitement.
</context>

<instructions>
1. **Analyze Audio**: Listen to the full audio to understand context and duration.
2. **Segmentation**: Break speech into natural segments (2-25 seconds).
    - No gaps > 1 second between segments unless there is silence/music.
3. **Transcription (Field: "text")**:
    - Transcribe exactly what is spoken.
    - Preserve code-switching (English stays English, Vietnamese stays Vietnamese).
    - **No Censorship**: Transcribe profanity, violence, or sensitive topics exactly.
4. **Translation (Field: "translation")**:
    - **Target**: Translate English words/idioms into natural Vietnamese.
    - **Constraint**: Do NOT modify existing Vietnamese words, sentence structures, or final particles.
    - **Proper Nouns**: Keep names, places, and brands in English (e.g., "iPhone", "Hà Nội", "Taylor Swift").
5. **Timestamping**: Format as "MM:SS.mmm". Ensure precision.
</instructions>

<translation_examples>
    <example_1>
        <context>Casual Shopping (Slang/Particles)</context>
        <audio_transcript>Cái store này sale off đến fifty percent luôn á.</audio_transcript>
        <bad_translation>Cửa hàng này đang giảm giá đến năm mươi phần trăm luôn đấy.</bad_translation>
        <good_translation>Cửa hàng này đang giảm giá đến năm mươi phần trăm luôn á.</good_translation>
        <reason>The particle "á" was preserved; only "store", "sale off", "fifty percent" were translated.</reason>
    </example_1>

    <example_2>
        <context>Gaming (High intensity/Urgency)</context>
        <audio_transcript>Trời ơi, con boss này damage to quá, anh em heal máu lẹ đi!</audio_transcript>
        <good_translation>Trời ơi, con trùm này sát thương to quá, anh em hồi máu lẹ đi!</good_translation>
    </example_2>

    <example_3>
        <context>Corporate (Professional but preserving structure)</context>
        <audio_transcript>Mình cần optimize cái campaign này để boost conversion rate lên xíu nha.</audio_transcript>
        <good_translation>Mình cần tối ưu hóa cái chiến dịch này để tăng tỷ lệ chuyển đổi lên xíu nha.</good_translation>
        <reason>Preserved "cái", "lên xíu nha" while translating technical terms.</reason>
    </example_3>

    <example_4>
        <context>Medical (Urgent/Technical)</context>
        <audio_transcript>Bệnh nhân có dấu hiệu bị stroke, y tá chuẩn bị phòng MRI ngay lập tức.</audio_transcript>
        <good_translation>Bệnh nhân có dấu hiệu bị đột quỵ, y tá chuẩn bị phòng cộng hưởng từ ngay lập tức.</good_translation>
    </example_4>

    <example_5>
        <context>Emotional Argument (Anger/Disbelief)</context>
        <audio_transcript>Why did you do that? Mày bị crazy hả? Tao không believe được luôn á!</audio_transcript>
        <good_translation>Tại sao mày làm thế? Mày bị điên hả? Tao không tin được luôn á!</good_translation>
        <reason>Translates the English questions/verbs but keeps the aggressive Vietnamese pronouns "Mày/Tao" and particles "hả/á".</reason>
    </example_5>
</translation_examples>

Process the audio now."""

# Response Schema for Structured Output
RESPONSE_SCHEMA = {
    "type": "ARRAY",
    "description": "A list of transcribed and translated audio segments.",
    "items": {
        "type": "OBJECT",
        "properties": {
            "start": {
                "type": "STRING",
                "description": "Start timestamp in MM:SS.mmm format (e.g., 04:05.123). Must be relative to 00:00."
            },
            "end": {
                "type": "STRING",
                "description": "End timestamp in MM:SS.mmm format. Must not overlap with the next segment."
            },
            "text": {
                "type": "STRING",
                "description": "Verbatim transcription. Preserves code-switching exactly as spoken."
            },
            "translation": {
                "type": "STRING",
                "description": "Vietnamese translation. Translates English terms but strictly preserves original Vietnamese sentence particles and tonality."
            }
        },
        "required": ["start", "end", "text", "translation"]
    }
}


# =============================================================================
# API KEY MANAGEMENT
# =============================================================================

class ModelKeyManager:
    """
    Smart API key manager with multi-model cascade and cooldown tracking.
    
    Tracks cooldowns per (model, key) tuple, not just per key.
    This allows switching models when one model's quota is exhausted.
    
    Cascade Algorithm:
    1. Try all keys on Flash (primary model)
    2. If all Flash keys exhausted → switch to Pro
    3. If all Pro keys exhausted → recheck Flash (some may have recovered)
    4. If everything exhausted → sleep 15 min → restart from Flash
    """
    
    # Model priority order (first = primary)
    MODELS = ["gemini-2.5-flash", "gemini-2.5-pro"]
    
    COOLDOWN_MINUTES = 5           # Cooldown per exhausted (model, key)
    EXHAUSTED_SLEEP_MINUTES = 15   # Sleep when ALL models+keys exhausted
    
    def __init__(self):
        self._keys = self._load_keys()
        if not self._keys:
            raise ValueError("No Gemini API keys found. Set GEMINI_API_KEYS env var.")
        
        # Cooldowns tracked per (model, key) tuple
        self._cooldowns: Dict[Tuple[str, str], datetime] = {}
        self._current_model_idx = 0
        
        logger.info(f"ModelKeyManager: loaded {len(self._keys)} API keys")
        logger.info(f"ModelKeyManager: models = {self.MODELS}")
    
    def _load_keys(self) -> List[str]:
        """Load API keys from environment."""
        keys = []
        
        # Try comma-separated list first
        combined = os.getenv("GEMINI_API_KEYS", "")
        if combined:
            keys = [k.strip() for k in combined.split(",") if k.strip()]
        
        # Fallback to numbered keys
        if not keys:
            for i in range(1, 100):
                key = os.getenv(f"GEMINI_API_KEY_{i}")
                if key:
                    keys.append(key)
        
        # Final fallback
        if not keys:
            key = os.getenv("GEMINI_API_KEY")
            if key:
                keys.append(key)
        
        return keys
    
    @property
    def key_count(self) -> int:
        return len(self._keys)
    
    @property
    def current_model(self) -> str:
        """Get the current model being used."""
        return self.MODELS[self._current_model_idx]
    
    def is_cooling(self, model: str, key: str) -> bool:
        """Check if (model, key) combo is currently in cooldown."""
        cooldown_until = self._cooldowns.get((model, key))
        if cooldown_until is None:
            return False
        return datetime.now(timezone.utc) < cooldown_until
    
    def mark_cooling(self, model: str, key: str) -> None:
        """Mark a (model, key) combo as exhausted (5-min cooldown)."""
        cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=self.COOLDOWN_MINUTES)
        self._cooldowns[(model, key)] = cooldown_until
        logger.warning(
            f"Key ...{key[-8:]} exhausted on {model}, "
            f"cooling until {cooldown_until.strftime('%H:%M:%S UTC')}"
        )
    
    def get_available_key(self, model: str) -> Optional[str]:
        """Get first available key for a specific model (not cooling)."""
        for key in self._keys:
            if not self.is_cooling(model, key):
                return key
        return None
    
    def get_next_available(self) -> Tuple[str, str]:
        """
        Get next available (model, key) pair using cascade logic.
        
        Returns:
            Tuple of (model_name, api_key)
            
        Algorithm:
        1. Try current model's keys
        2. If none → switch to next model
        3. Cycle through all models twice (allows keys to recover)
        4. If still nothing → sleep 15 min → restart from first model
        """
        # Try up to 2 full cycles through all models
        # (first cycle exhausts, second cycle allows recovery check)
        max_attempts = len(self.MODELS) * 2
        
        for attempt in range(max_attempts):
            model = self.MODELS[self._current_model_idx]
            key = self.get_available_key(model)
            
            if key:
                logger.info(f"Using model: {model}, key: ...{key[-8:]}")
                return model, key
            
            # All keys exhausted for this model, switch to next
            old_model = model
            self._current_model_idx = (self._current_model_idx + 1) % len(self.MODELS)
            new_model = self.MODELS[self._current_model_idx]
            logger.info(f"All keys exhausted for {old_model}, switching to {new_model}...")
        
        # All models exhausted, sleep and restart
        logger.warning(
            f"All models and keys exhausted! "
            f"Sleeping {self.EXHAUSTED_SLEEP_MINUTES} minutes..."
        )
        time.sleep(self.EXHAUSTED_SLEEP_MINUTES * 60)
        
        # Reset to first model and try again
        self._current_model_idx = 0
        self._cooldowns.clear()  # Clear all cooldowns after long sleep
        logger.info("Cooldowns cleared, restarting from first model...")
        
        return self.get_next_available()  # Recursive retry
    
    def configure_genai(self, key: str) -> None:
        """Configure genai library with the given API key."""
        genai.configure(api_key=key)


# =============================================================================
# JSON PARSING
# =============================================================================

def clean_json_response(text: str) -> str:
    """
    Clean Gemini response to extract JSON.
    
    Removes markdown code blocks and whitespace.
    """
    # Remove markdown code blocks
    text = re.sub(r'^```json\s*', '', text, flags=re.MULTILINE)
    text = re.sub(r'^```\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'```$', '', text)
    
    return text.strip()


def parse_gemini_response(text: str) -> List[Dict[str, Any]]:
    """
    Parse Gemini response into structured segments.
    
    Args:
        text: Raw response text from Gemini
        
    Returns:
        List of segment dictionaries
        
    Raises:
        ValueError: If parsing fails
    """
    cleaned = clean_json_response(text)
    
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error: {e}")
        logger.error(f"Raw text: {cleaned[:500]}")
        raise ValueError(f"Invalid JSON response: {e}")
    
    if not isinstance(data, list):
        raise ValueError(f"Expected list, got {type(data).__name__}")
    
    # Validate and convert each segment
    segments = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        
        try:
            segment = {
                "start": parse_timestamp(item.get("start", 0)),
                "end": parse_timestamp(item.get("end", 0)),
                "text": str(item.get("text", "")),
                "translation": str(item.get("translation", "")),
            }
            segments.append(segment)
        except ValueError as e:
            logger.warning(f"Skipping segment {i}: {e}")
    
    return segments


# =============================================================================
# MAIN PROCESSING
# =============================================================================

def process_chunk(
    chunk_id: int,
    api_key_pool: Any,
    model_name: str = DEFAULT_MODEL
) -> Tuple[int, Dict[str, Any]]:
    """
    Process a single chunk with Gemini.
    
    Args:
        chunk_id: ID of chunk to process
        api_key_pool: Object with get_key() method returning API key string
        model_name: Gemini model to use
        
    Returns:
        Tuple of (segments_created, metadata)
    """
    if api_key_pool is None:
        raise ValueError("api_key_pool is required")

    
    with Session(engine) as session:
        chunk = session.get(Chunk, chunk_id)
        if not chunk:
            raise ValueError(f"Chunk {chunk_id} not found")
        
        # Check if already processed
        if chunk.status == ProcessingStatus.REVIEW_READY:
            logger.info(f"Chunk {chunk_id} already processed, skipping")
            return 0, {"skipped": True}
        
        # Resolve audio path
        audio_path = DATA_ROOT / chunk.audio_path
        if not audio_path.exists():
            raise FileNotFoundError(f"Audio not found: {audio_path}")
        
        # Update status
        chunk.status = ProcessingStatus.PROCESSING
        session.add(chunk)
        session.commit()
        
        # Configure Gemini
        genai.configure(api_key=api_key_pool.get_key())
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT  # Set system instruction at model level
        )
        
        # Upload and process
        logger.info(f"Processing chunk {chunk_id}: {chunk.audio_path}")
        start_time = time.time()
        
        try:
            # Upload audio file
            audio_file = genai.upload_file(str(audio_path))
            
            # Generate transcription with structured output
            response = model.generate_content(
                [USER_PROMPT, audio_file],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA  # Enforce structure
                )
            )
            
            processing_time = time.time() - start_time
            
            # Parse response
            segments_data = parse_gemini_response(response.text)
            
            # Delete existing segments for this chunk
            existing = session.exec(
                select(Segment).where(Segment.chunk_id == chunk_id)
            ).all()
            for seg in existing:
                session.delete(seg)
            
            # Insert new segments
            for seg_data in segments_data:
                segment = Segment(
                    chunk_id=chunk_id,
                    start_time_relative=seg_data["start"],
                    end_time_relative=seg_data["end"],
                    transcript=seg_data["text"],
                    translation=seg_data["translation"],
                    is_verified=False,
                )
                session.add(segment)
            
            # Update chunk status
            chunk.status = ProcessingStatus.REVIEW_READY
            session.add(chunk)
            session.commit()
            
            metadata = {
                "processing_time_seconds": processing_time,
                "segments_count": len(segments_data),
                "api_key": f"...{api_key_pool.get_key()[-8:]}",
            }
            
            logger.info(f"Chunk {chunk_id}: {len(segments_data)} segments in {processing_time:.1f}s")
            
            return len(segments_data), metadata
            
        except Exception as e:
            logger.error(f"Failed to process chunk {chunk_id}: {e}")
            chunk.status = ProcessingStatus.PENDING  # Reset for retry
            session.add(chunk)
            session.commit()
            
            # Try rotating API key
            api_key_pool.rotate()
            raise


def process_all_pending(
    limit: int = 10,
    model_name: str = DEFAULT_MODEL
) -> Dict[str, int]:
    """
    Process all pending chunks.
    
    Args:
        limit: Maximum chunks to process
        model_name: Gemini model to use
        
    Returns:
        Dict with success/fail counts
    """
    api_key_pool = ApiKeyPool()
    
    with Session(engine) as session:
        chunks = session.exec(
            select(Chunk)
            .where(Chunk.status == ProcessingStatus.PENDING)
            .order_by(Chunk.video_id, Chunk.chunk_index)
            .limit(limit)
        ).all()
    
    results = {"success": 0, "failed": 0, "total_segments": 0}
    
    for chunk in chunks:
        try:
            segments, _ = process_chunk(chunk.id, api_key_pool, model_name)
            results["success"] += 1
            results["total_segments"] += segments
            
            # Rate limiting
            time.sleep(2)
            
        except Exception as e:
            logger.error(f"Chunk {chunk.id} failed: {e}")
            results["failed"] += 1
    
    return results


# =============================================================================
# QUEUE WORKER (Centralized Processing)
# =============================================================================

def run_queue_worker(
    poll_interval: float = 2.0,
    rate_limit_delay: float = 1.0,
):
    """
    Run the centralized queue worker with multi-model cascade.
    
    This is a single-threaded worker that:
    1. Polls for QUEUED jobs
    2. Gets an available (model, key) pair (cascades Flash → Pro)
    3. Processes the chunk
    4. On 429 error: marks (model, key) as cooling, cascades to next
    5. If all models+keys exhausted: sleeps 15 min, rechecks
    
    Run:
        python -m backend.processing.gemini_worker --queue
    """
    logger.info("=" * 60)
    logger.info("Starting Gemini Queue Worker (Multi-Model Cascade)")
    logger.info(f"  Poll interval: {poll_interval}s")
    logger.info(f"  Rate limit delay: {rate_limit_delay}s")
    logger.info(f"  Models: {ModelKeyManager.MODELS}")
    logger.info("=" * 60)
    
    # Initialize multi-model key manager
    model_manager = ModelKeyManager()
    current_model, current_key = model_manager.get_next_available()
    model_manager.configure_genai(current_key)
    
    # Simple key pool wrapper for process_chunk compatibility
    class SmartKeyPool:
        """Wrapper to maintain compatibility with process_chunk signature."""
        def __init__(self):
            self._current_key = None
        
        def set_key(self, key: str):
            self._current_key = key
        
        def get_key(self):
            return self._current_key
        
        def rotate(self):
            # No-op, rotation handled by model_manager
            return self._current_key
    
    key_pool = SmartKeyPool()
    key_pool.set_key(current_key)
    
    while True:
        try:
            with Session(engine) as session:
                # Get oldest QUEUED job with row-level lock
                job = session.exec(
                    select(ProcessingJob)
                    .where(ProcessingJob.status == JobStatus.QUEUED)
                    .order_by(ProcessingJob.created_at)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).first()
                
                if not job:
                    # No jobs in queue, sleep and retry
                    logger.debug("Queue empty, waiting...")
                    time.sleep(poll_interval)
                    continue
                
                # Claim the job
                job.status = JobStatus.PROCESSING
                job.started_at = datetime.now(timezone.utc)
                session.add(job)
                session.commit()
                
                job_id = job.id
                chunk_id = job.chunk_id
                video_id = job.video_id
                
            logger.info(f"Processing job {job_id}: chunk {chunk_id} (video {video_id}) with {current_model}")
            
            # Process the chunk with current model
            try:
                segments_created, metadata = process_chunk(chunk_id, key_pool, current_model)
                
                # Mark job as completed
                with Session(engine) as session:
                    job = session.get(ProcessingJob, job_id)
                    if job:
                        job.status = JobStatus.COMPLETED
                        job.completed_at = datetime.now(timezone.utc)
                        session.add(job)
                        session.commit()
                
                logger.info(f"✓ Job {job_id} completed: {segments_created} segments ({current_model})")
                
            except Exception as e:
                error_str = str(e).lower()
                error_msg = str(e)[:1000]
                
                # Check if rate limited (429 error)
                if "429" in error_str or "resource" in error_str or "quota" in error_str:
                    logger.warning(f"Rate limited on {current_model}! Marking (model, key) as cooling...")
                    model_manager.mark_cooling(current_model, current_key)
                    
                    # Return job to queue so it can be retried
                    with Session(engine) as session:
                        job = session.get(ProcessingJob, job_id)
                        if job:
                            job.status = JobStatus.QUEUED
                            job.started_at = None
                            session.add(job)
                            session.commit()
                    
                    # Get next available (model, key) - may switch models or wait
                    current_model, current_key = model_manager.get_next_available()
                    model_manager.configure_genai(current_key)
                    key_pool.set_key(current_key)
                    continue

                
                # Other errors: mark job as failed
                logger.error(f"✗ Job {job_id} failed: {error_msg}")
                with Session(engine) as session:
                    job = session.get(ProcessingJob, job_id)
                    if job:
                        job.status = JobStatus.FAILED
                        job.completed_at = datetime.now(timezone.utc)
                        job.error_message = error_msg
                        session.add(job)
                        session.commit()
            
            # Rate limiting between jobs
            time.sleep(rate_limit_delay)
            
        except KeyboardInterrupt:
            logger.info("\nQueue worker stopped by user (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"Worker error: {e}")
            time.sleep(poll_interval)


# =============================================================================
# CLI ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import sys
    
    # Setup logging to both console and file
    log_dir = Path(__file__).parent.parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "gemini_worker.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, mode='a', encoding='utf-8')
        ]
    )
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "--queue":
            # Run queue worker with smart key rotation
            run_queue_worker()
        elif sys.argv[1] == "--all":
            # Process all pending chunks (legacy mode)
            limit = 10
            if len(sys.argv) > 2:
                limit = int(sys.argv[2])
            print(f"Processing up to {limit} pending chunks...")
            results = process_all_pending(limit=limit)
            print(f"Results: {results}")
        else:
            # Process specific chunk by ID
            chunk_id = int(sys.argv[1])
            process_chunk(chunk_id)
    else:
        print("Gemini Worker - Audio Transcription (Multi-Model Cascade)")
        print("")
        print("Usage:")
        print("  python -m backend.processing.gemini_worker --queue      # Run queue worker")
        print("  python -m backend.processing.gemini_worker --all [N]    # Process N pending chunks")
        print("  python -m backend.processing.gemini_worker <chunk_id>   # Process single chunk")
        print("")
        print("Multi-Model Cascade:")
        print("  1. Try all API keys on gemini-2.5-flash")
        print("  2. If all exhausted → switch to gemini-2.5-pro")
        print("  3. If all pro keys exhausted → recheck flash (may have recovered)")
        print("  4. If everything exhausted → sleep 15 min → restart")

