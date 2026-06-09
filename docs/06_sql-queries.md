# SQL Operations Reference

Quick reference for direct database operations via pgAdmin4. All queries are **safe** unless marked with ⚠️ or ☢️.

> [!TIP]
> Always run `SELECT` queries first to preview what will be affected before running `DELETE` or `UPDATE`.

---

## Table Overview

| Table | Contains | Safe to Modify? |
|-------|----------|-----------------|
| `processing_jobs` | Queue metadata (job status, timestamps) | ✅ Safe |
| `chunks` | Audio file paths, workflow status, locks | ✅ Safe |
| `channels` | YouTube channel metadata | ✅ Safe |
| `videos` | Video metadata, file paths | ✅ Safe |
| `segments` | **THE ACTUAL TRANSCRIPTS** | ⚠️ Danger |
| `users` | Annotator accounts | ✅ Safe |

---

## Queue Management (`processing_jobs`)

### View queue status
```sql
SELECT status, COUNT(*) 
FROM processing_jobs 
GROUP BY status;
```

### View all jobs for a specific video
```sql
SELECT pj.*, c.chunk_index 
FROM processing_jobs pj
JOIN chunks c ON pj.chunk_id = c.id
WHERE pj.video_id = <VIDEO_ID>
ORDER BY c.chunk_index;
```

### View currently processing jobs
```sql
SELECT pj.id, pj.chunk_id, pj.video_id, pj.started_at, v.title
FROM processing_jobs pj
JOIN videos v ON pj.video_id = v.id
WHERE pj.status = 'processing';
```

### Reset queue (cancel all QUEUED jobs, keep PROCESSING)
```sql
-- Preview first
SELECT * FROM processing_jobs WHERE status = 'queued';

-- Delete queued jobs
DELETE FROM processing_jobs WHERE status = 'queued';
```

### Reset FAILED jobs back to QUEUED (retry all)
```sql
UPDATE processing_jobs 
SET status = 'queued', 
    error_message = NULL,
    started_at = NULL,
    completed_at = NULL
WHERE status = 'failed';
```

### Retry failed jobs for specific video only
```sql
UPDATE processing_jobs 
SET status = 'queued', 
    error_message = NULL,
    started_at = NULL,
    completed_at = NULL
WHERE status = 'failed' AND video_id = <VIDEO_ID>;
```

### Clear ALL jobs for a specific video
```sql
DELETE FROM processing_jobs WHERE video_id = <VIDEO_ID>;
```

### Clear completed jobs (cleanup old history)
```sql
DELETE FROM processing_jobs WHERE status = 'completed';
```

### Find "stuck" jobs (processing for too long)
```sql
SELECT * FROM processing_jobs 
WHERE status = 'PROCESSING' 
AND started_at < NOW() - INTERVAL '10 minutes';
```

### Reset stuck jobs to QUEUED
```sql
UPDATE processing_jobs 
SET status = 'QUEUED', started_at = NULL 
WHERE status = 'PROCESSING' 
AND started_at < NOW() - INTERVAL '10 minutes';
```

### Find videos where chunks are already 'review_ready' but have stale 'failed' job records
```sql
SELECT 
    v.id AS video_id,
    v.title,
    COUNT(DISTINCT pj.chunk_id) AS phantom_failed_chunks,
    COUNT(DISTINCT c.id) AS total_chunks
FROM processing_jobs pj
JOIN chunks c ON pj.chunk_id = c.id
JOIN videos v ON c.video_id = v.id
WHERE pj.status = 'FAILED'
  AND c.status = 'REVIEW_READY'  -- Chunk is actually DONE
GROUP BY v.id, v.title
ORDER BY phantom_failed_chunks DESC;
```

### Preview first
```sql
SELECT pj.id, pj.chunk_id, c.status AS chunk_status, pj.status AS job_status, pj.error_message
FROM processing_jobs pj
JOIN chunks c ON pj.chunk_id = c.id
WHERE pj.status = 'FAILED' AND c.status = 'REVIEW_READY';
```

### Delete the stale records
```sql
DELETE FROM processing_jobs pj
USING chunks c
WHERE pj.chunk_id = c.id
  AND pj.status = 'FAILED'
  AND c.status = 'REVIEW_READY';
```

### Show all status mismatches between chunks and jobs
```sql
SELECT 
    v.id AS video_id,
    v.title,
    c.id AS chunk_id,
    c.chunk_index,
    c.status AS chunk_status,
    pj.status AS job_status,
    pj.error_message
FROM chunks c
JOIN videos v ON c.video_id = v.id
LEFT JOIN processing_jobs pj ON c.id = pj.chunk_id
WHERE 
    -- Case 1: Job says failed, but chunk is actually done
    (pj.status = 'FAILED' AND c.status IN ('REVIEW_READY', 'APPROVED', 'IN_REVIEW'))
    OR
    -- Case 2: Chunk stuck in PROCESSING (worker crashed)
    (c.status = 'PROCESSING' AND (pj.status IS NULL OR pj.status IN ('FAILED', 'COMPLETED')))
    OR
    -- Case 3: Orphaned failed job
    (pj.status = 'FAILED' AND c.status NOT IN ('PENDING', 'PROCESSING'))
ORDER BY v.id, c.chunk_index;
```

### Delete ALL completed and failed jobs (they're just history logs)
```sql
DELETE FROM processing_jobs 
WHERE status IN ('COMPLETED', 'FAILED');
```

### Preview stuck chunks
```sql
SELECT c.id, c.chunk_index, v.title, c.status
FROM chunks c
JOIN videos v ON c.video_id = v.id
WHERE c.status = 'PROCESSING';
```

### Reset them to PENDING (so they get re-queued)
```sql
UPDATE chunks 
SET status = 'PENDING'
WHERE status = 'PROCESSING';
```

### Step 1: Delete all failed/completed job records
```sql
DELETE FROM processing_jobs WHERE status IN ('FAILED');
```

### Step 2: Reset any stuck PROCESSING chunks to PENDING
```sql
UPDATE chunks SET status = 'PENDING' WHERE status = 'PROCESSING';
```

### Step 3: Also delete any PROCESSING jobs (orphaned)
```sql
DELETE FROM processing_jobs WHERE status = 'PROCESSING' 
AND started_at < NOW() - INTERVAL '30 minutes';
```

---

## Chunk Management (`chunks`)

### View all chunks for a video
```sql
SELECT id, chunk_index, status, audio_path
FROM chunks 
WHERE video_id = <VIDEO_ID>
ORDER BY chunk_index;
```

### Reset chunks to PENDING (so they can be re-queued)
```sql
UPDATE chunks 
SET status = 'pending' 
WHERE video_id = <VIDEO_ID>;
```

### View chunk status summary for a video
```sql
SELECT status, COUNT(*) 
FROM chunks 
WHERE video_id = <VIDEO_ID>
GROUP BY status;
```

### Find chunks with status/job mismatch (the bug)
```sql
SELECT c.id AS chunk_id, c.status AS chunk_status, 
       pj.status AS job_status, pj.error_message
FROM chunks c
LEFT JOIN processing_jobs pj ON c.id = pj.chunk_id
WHERE c.status = 'review_ready' AND pj.status = 'failed';
```

### Release all expired locks
```sql
UPDATE chunks 
SET locked_by_user_id = NULL, lock_expires_at = NULL
WHERE lock_expires_at < NOW();
```

### Force-release a specific chunk's lock
```sql
UPDATE chunks 
SET locked_by_user_id = NULL, 
    lock_expires_at = NULL,
    status = 'review_ready'
WHERE id = <CHUNK_ID>;
```

---

## Channel Management (`channels`)

### Find empty channels (no videos)
```sql
SELECT ch.id, ch.name, COUNT(v.id) AS video_count
FROM channels ch
LEFT JOIN videos v ON ch.id = v.channel_id
GROUP BY ch.id, ch.name
HAVING COUNT(v.id) = 0;
```

### Delete empty channels
```sql
DELETE FROM channels 
WHERE id NOT IN (SELECT DISTINCT channel_id FROM videos);
```

### Find and delete "Unknown" channels with no videos
```sql
DELETE FROM channels 
WHERE name = 'Unknown' 
AND id NOT IN (SELECT DISTINCT channel_id FROM videos);
```

### List all channels with video counts
```sql
SELECT ch.id, ch.name, COUNT(v.id) AS video_count
FROM channels ch
LEFT JOIN videos v ON ch.id = v.channel_id
GROUP BY ch.id, ch.name
ORDER BY video_count DESC;
```

---

## Video Management (`videos`)

### List all videos with chunk counts
```sql
SELECT v.id, v.title, v.channel_id, COUNT(c.id) AS chunk_count
FROM videos v
LEFT JOIN chunks c ON v.id = c.video_id
GROUP BY v.id, v.title, v.channel_id
ORDER BY v.id;
```

### Find videos without chunks (need chunking)
```sql
SELECT v.id, v.title, v.file_path
FROM videos v
LEFT JOIN chunks c ON v.id = c.video_id
WHERE c.id IS NULL;
```

### View processing progress for all videos
```sql
SELECT 
    v.id,
    v.title,
    COUNT(c.id) AS total_chunks,
    COUNT(CASE WHEN c.status = 'approved' THEN 1 END) AS approved,
    COUNT(CASE WHEN c.status = 'review_ready' THEN 1 END) AS review_ready,
    COUNT(CASE WHEN c.status = 'pending' THEN 1 END) AS pending
FROM videos v
LEFT JOIN chunks c ON v.id = c.video_id
GROUP BY v.id, v.title
ORDER BY v.id;
```

---

## Segment Management (`segments`) ⚠️

> [!CAUTION]
> These queries modify actual transcript data. Use with extreme care.

### Count segments per chunk
```sql
SELECT chunk_id, COUNT(*) AS segment_count
FROM segments
WHERE chunk_id IN (
    SELECT id FROM chunks WHERE video_id = <VIDEO_ID>
)
GROUP BY chunk_id
ORDER BY chunk_id;
```

### View segments for a specific chunk
```sql
SELECT id, start_time_relative, end_time_relative, 
       LEFT(transcript, 50) AS transcript_preview
FROM segments
WHERE chunk_id = <CHUNK_ID>
ORDER BY start_time_relative;
```

### ⚠️ Delete all segments for a chunk (before re-transcribing)
```sql
DELETE FROM segments WHERE chunk_id = <CHUNK_ID>;
```

### ⚠️ Delete all segments for a video
```sql
DELETE FROM segments 
WHERE chunk_id IN (
    SELECT id FROM chunks WHERE video_id = <VIDEO_ID>
);
```

### Count verified vs unverified segments
```sql
SELECT 
    COUNT(*) AS total,
    COUNT(CASE WHEN is_verified THEN 1 END) AS verified,
    COUNT(CASE WHEN is_rejected THEN 1 END) AS rejected
FROM segments
WHERE chunk_id IN (
    SELECT id FROM chunks WHERE video_id = <VIDEO_ID>
);
```

---

## Nuclear Options ☢️

> [!CAUTION]
> These are destructive operations. **BACKUP FIRST.**

### ☢️ Reset EVERYTHING (start fresh)
```sql
-- Order matters due to foreign keys!
DELETE FROM segments;
DELETE FROM processing_jobs;
DELETE FROM chunks;
-- Videos and channels are preserved
```

### ☢️ Full database reset (including videos)
```sql
DELETE FROM segments;
DELETE FROM processing_jobs;
DELETE FROM chunks;
DELETE FROM videos;
DELETE FROM channels;
-- Only users remain
```

---

## Useful Monitoring Queries

### Overall system status
```sql
SELECT 
    (SELECT COUNT(*) FROM videos) AS total_videos,
    (SELECT COUNT(*) FROM chunks) AS total_chunks,
    (SELECT COUNT(*) FROM segments) AS total_segments,
    (SELECT COUNT(*) FROM processing_jobs WHERE status = 'queued') AS queued_jobs,
    (SELECT COUNT(*) FROM processing_jobs WHERE status = 'processing') AS processing_jobs;
```

### Processing rate (chunks completed per hour)
```sql
SELECT 
    date_trunc('hour', completed_at) AS hour,
    COUNT(*) AS completed
FROM processing_jobs
WHERE status = 'completed'
AND completed_at > NOW() - INTERVAL '24 hours'
GROUP BY date_trunc('hour', completed_at)
ORDER BY hour DESC;
```

### Failed jobs with error messages
```sql
SELECT pj.id, pj.chunk_id, v.title, pj.error_message
FROM processing_jobs pj
JOIN videos v ON pj.video_id = v.id
WHERE pj.status = 'failed'
ORDER BY pj.completed_at DESC
LIMIT 20;
```

---

## Data Consistency (Fix Stale Status)

> [!IMPORTANT]
> These queries help fix the "fully processed but shows failed" issue visible in the UI.

### Find videos showing "processed" but have failed jobs

This finds videos where the progress bar looks complete, but there are still failed jobs lurking:

```sql
SELECT 
    v.id AS video_id,
    v.title,
    COUNT(c.id) AS total_chunks,
    COUNT(CASE WHEN c.status = 'review_ready' THEN 1 END) AS review_ready,
    COUNT(CASE WHEN c.status = 'pending' THEN 1 END) AS pending,
    (SELECT COUNT(*) FROM processing_jobs pj 
     WHERE pj.video_id = v.id AND pj.status = 'failed') AS failed_jobs
FROM videos v
JOIN chunks c ON v.id = c.video_id
GROUP BY v.id, v.title
HAVING (SELECT COUNT(*) FROM processing_jobs pj 
        WHERE pj.video_id = v.id AND pj.status = 'failed') > 0
ORDER BY failed_jobs DESC;
```

### Clean up stale FAILED jobs (chunks already processed successfully)

When a chunk is `review_ready` but has an old `failed` job record, delete the stale job:

```sql
-- Preview first
SELECT pj.id, pj.chunk_id, c.status AS chunk_status, pj.status AS job_status
FROM processing_jobs pj
JOIN chunks c ON pj.chunk_id = c.id
WHERE pj.status = 'failed' 
AND c.status = 'review_ready';

-- Delete stale failed jobs
DELETE FROM processing_jobs pj
USING chunks c
WHERE pj.chunk_id = c.id
AND pj.status = 'failed'
AND c.status = 'review_ready';
```

### Clean up all COMPLETED/FAILED jobs for already-processed chunks

More aggressive cleanup - removes ALL old job history for chunks that are done:

```sql
DELETE FROM processing_jobs pj
USING chunks c
WHERE pj.chunk_id = c.id
AND pj.status IN ('completed', 'failed')
AND c.status = 'review_ready';
```

### Find orphaned jobs (chunk no longer exists)

```sql
SELECT pj.* 
FROM processing_jobs pj
LEFT JOIN chunks c ON pj.chunk_id = c.id
WHERE c.id IS NULL;
```

### Delete orphaned jobs

```sql
DELETE FROM processing_jobs pj
WHERE NOT EXISTS (
    SELECT 1 FROM chunks c WHERE c.id = pj.chunk_id
);
```

### True video processing status (accurate count)

This shows the REAL status of each video, ignoring stale job records:

```sql
SELECT 
    v.id,
    v.title,
    COUNT(c.id) AS total_chunks,
    COUNT(CASE WHEN c.status = 'pending' THEN 1 END) AS pending,
    COUNT(CASE WHEN c.status = 'processing' THEN 1 END) AS processing,
    COUNT(CASE WHEN c.status = 'review_ready' THEN 1 END) AS review_ready,
    COUNT(CASE WHEN c.status = 'in_review' THEN 1 END) AS in_review,
    COUNT(CASE WHEN c.status = 'approved' THEN 1 END) AS approved,
    COUNT(CASE WHEN c.status = 'rejected' THEN 1 END) AS rejected
FROM videos v
LEFT JOIN chunks c ON v.id = c.video_id
GROUP BY v.id, v.title
ORDER BY pending DESC, v.id;
```

