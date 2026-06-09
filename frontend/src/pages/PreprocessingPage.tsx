/**
 * Audio Preprocessing Page
 * 
 * Queue management for Gemini transcription processing.
 * Shows videos with pending chunks, allows batch selection and processing.
 * Real-time updates via SSE.
 */

import { useState, useEffect, useCallback } from 'react'
import {
    Box,
    Typography,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    TableSortLabel,
    Paper,
    Checkbox,
    Button,
    Chip,
    IconButton,
    Tooltip,
    CircularProgress,
    Alert,
    LinearProgress,
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions,
} from '@mui/material'
import {
    PlayArrow as PlayIcon,
    Refresh as RefreshIcon,
    Warning as WarningIcon,
    Article as LogIcon,
    Cancel as CancelIcon,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

// Types
interface VideoQueueStatus {
    video_id: number
    video_title: string
    channel_name: string
    duration_seconds: number
    total_chunks: number
    pending_chunks: number
    queued_chunks: number
    processing_chunks: number
    completed_chunks: number
    failed_chunks: number
}

interface QueueStats {
    queued: number
    processing: number
    completed: number
    failed: number
    pending_chunks: number
}

// Helper to format duration
const formatDuration = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600)
    const mins = Math.floor((seconds % 3600) / 60)
    const secs = seconds % 60
    if (hours > 0) {
        return `${hours}:${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${mins}:${secs.toString().padStart(2, '0')}`
}

interface PreprocessingPageProps {
    userId: number
}

export function PreprocessingPage({ userId }: PreprocessingPageProps) {
    const [selectedVideos, setSelectedVideos] = useState<Set<number>>(new Set())
    const [sseConnected, setSseConnected] = useState(false)
    const [showLogModal, setShowLogModal] = useState(false)
    const [sortBy, setSortBy] = useState<'title' | 'channel' | 'duration' | 'progress' | 'status'>('channel')
    const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
    const queryClient = useQueryClient()

    // Fetch queue summary
    const { data: videos, isLoading, error, refetch } = useQuery<VideoQueueStatus[]>({
        queryKey: ['queue-summary'],
        queryFn: () => api.get('/queue/summary').then(r => r.data),
        refetchInterval: 10000, // Fallback polling every 10s
    })

    // Fetch queue stats
    const { data: stats } = useQuery<QueueStats>({
        queryKey: ['queue-stats'],
        queryFn: () => api.get('/queue/stats').then(r => r.data),
        refetchInterval: 5000,
    })

    // Fetch worker logs
    const { data: logsData, refetch: refetchLogs, isFetching: loadingLogs } = useQuery<{
        exists: boolean
        lines: string[]
        total_lines?: number
        message?: string
    }>({
        queryKey: ['worker-logs'],
        queryFn: () => api.get('/queue/logs?lines=200').then(r => r.data),
        enabled: showLogModal,
        refetchInterval: showLogModal ? 3000 : false,
    })

    // SSE connection for real-time updates
    useEffect(() => {
        const eventSource = new EventSource('/api/queue/status')

        eventSource.onopen = () => {
            setSseConnected(true)
        }

        eventSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)

                if (data.event === 'job_started' ||
                    data.event === 'job_completed' ||
                    data.event === 'job_failed') {
                    // Refetch data on any job status change
                    queryClient.invalidateQueries({ queryKey: ['queue-summary'] })
                    queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
                }
            } catch (e) {
                // Ignore parse errors (heartbeats, etc.)
            }
        }

        eventSource.onerror = () => {
            setSseConnected(false)
        }

        return () => {
            eventSource.close()
        }
    }, [queryClient])

    // Add to queue mutation
    const addToQueue = useMutation({
        mutationFn: (videoIds: number[]) =>
            api.post('/queue/add-videos', { video_ids: videoIds }, {
                headers: { 'X-User-ID': userId.toString() }
            }),
        onSuccess: (response) => {
            const data = response.data
            console.log(`Queued ${data.queued} chunks, skipped ${data.skipped}`)
            queryClient.invalidateQueries({ queryKey: ['queue-summary'] })
            queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
            setSelectedVideos(new Set())
        }
    })

    // Retry failed mutation
    const retryFailed = useMutation({
        mutationFn: (videoId: number) =>
            api.post(`/queue/retry-failed/${videoId}`, {}, {
                headers: { 'X-User-ID': userId.toString() }
            }),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['queue-summary'] })
            queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
        }
    })

    // Cancel bulk jobs mutation
    const cancelBulkJobs = useMutation({
        mutationFn: (videoIds: number[]) =>
            api.delete('/queue/jobs/bulk', {
                data: { video_ids: videoIds },
                headers: { 'X-User-ID': userId.toString() }
            }),
        onSuccess: (response) => {
            const data = response.data
            console.log(`Cancelled ${data.cancelled} queued jobs`)
            queryClient.invalidateQueries({ queryKey: ['queue-summary'] })
            queryClient.invalidateQueries({ queryKey: ['queue-stats'] })
            setSelectedVideos(new Set())
        }
    })

    // Selection handlers
    const toggleVideo = useCallback((videoId: number) => {
        setSelectedVideos(prev => {
            const next = new Set(prev)
            if (next.has(videoId)) {
                next.delete(videoId)
            } else {
                next.add(videoId)
            }
            return next
        })
    }, [])

    const toggleAll = useCallback(() => {
        if (!videos) return

        if (selectedVideos.size === videos.length) {
            setSelectedVideos(new Set())
        } else {
            setSelectedVideos(new Set(videos.map(v => v.video_id)))
        }
    }, [videos, selectedVideos])

    // Get status chip for a video
    const getStatusChip = (video: VideoQueueStatus) => {
        if (video.processing_chunks > 0) {
            return (
                <Chip
                    icon={<CircularProgress size={12} />}
                    label="Processing..."
                    color="info"
                    size="small"
                />
            )
        }
        if (video.queued_chunks > 0) {
            return (
                <Chip
                    label={`${video.queued_chunks} queued`}
                    color="warning"
                    size="small"
                />
            )
        }
        if (video.failed_chunks > 0) {
            return (
                <Chip
                    icon={<WarningIcon />}
                    label={`${video.failed_chunks} failed`}
                    color="error"
                    size="small"
                />
            )
        }
        if (video.pending_chunks > 0) {
            return (
                <Chip
                    label={`${video.pending_chunks} pending`}
                    variant="outlined"
                    size="small"
                />
            )
        }
        return (
            <Chip
                label="Ready"
                color="success"
                size="small"
            />
        )
    }

    // Calculate progress for a video
    const getProgress = (video: VideoQueueStatus): number => {
        if (video.total_chunks === 0) return 0
        const processed = video.completed_chunks
        return (processed / video.total_chunks) * 100
    }

    // Sorting handler
    const handleSort = (column: 'title' | 'channel' | 'duration' | 'progress' | 'status') => {
        if (sortBy === column) {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc')
        } else {
            setSortBy(column)
            setSortDir('asc')
        }
    }

    // Get status priority for sorting (processing > queued > failed > pending > ready)
    const getStatusPriority = (video: VideoQueueStatus): number => {
        if (video.processing_chunks > 0) return 1
        if (video.queued_chunks > 0) return 2
        if (video.failed_chunks > 0) return 3
        if (video.pending_chunks > 0) return 4
        return 5 // Ready
    }

    // Sort videos
    const sortedVideos = videos ? [...videos].sort((a, b) => {
        let cmp = 0
        switch (sortBy) {
            case 'title':
                cmp = a.video_title.localeCompare(b.video_title)
                break
            case 'channel':
                cmp = a.channel_name.localeCompare(b.channel_name)
                break
            case 'duration':
                cmp = a.duration_seconds - b.duration_seconds
                break
            case 'progress':
                cmp = getProgress(a) - getProgress(b)
                break
            case 'status':
                cmp = getStatusPriority(a) - getStatusPriority(b)
                break
        }
        return sortDir === 'asc' ? cmp : -cmp
    }) : []

    if (isLoading) {
        return (
            <Box sx={{ p: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
                <CircularProgress />
                <Typography>Loading queue...</Typography>
            </Box>
        )
    }

    if (error) {
        return (
            <Box sx={{ p: 3 }}>
                <Alert severity="error">
                    Failed to load processing queue. Is the backend running?
                </Alert>
            </Box>
        )
    }

    return (
        <Box className="preprocessing-page" sx={{ p: 3 }}>
            {/* Header */}
            <Box sx={{ mb: 3 }}>
                <Typography variant="h5" gutterBottom>
                    🎤 Audio Preprocessing
                </Typography>
                <Typography color="text.secondary">
                    Queue videos for Gemini transcription. Chunks are processed one at a time by the background worker.
                </Typography>
            </Box>

            {/* Status bar */}
            <Paper sx={{ p: 2, mb: 3, display: 'flex', gap: 3, alignItems: 'center', flexWrap: 'wrap' }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <Box
                        sx={{
                            width: 8,
                            height: 8,
                            borderRadius: '50%',
                            bgcolor: sseConnected ? 'success.main' : 'error.main'
                        }}
                    />
                    <Typography variant="body2" color="text.secondary">
                        {sseConnected ? 'Connected' : 'Disconnected'}
                    </Typography>
                </Box>

                {stats && (
                    <>
                        <Chip label={`${stats.pending_chunks} pending`} size="small" variant="outlined" />
                        <Chip label={`${stats.queued} queued`} size="small" color="warning" />
                        <Chip label={`${stats.processing} processing`} size="small" color="info" />
                        <Chip label={`${stats.completed} completed`} size="small" color="success" />
                        {stats.failed > 0 && (
                            <Chip label={`${stats.failed} failed`} size="small" color="error" />
                        )}
                    </>
                )}

                <Box sx={{ flexGrow: 1 }} />

                <Button
                    variant="contained"
                    startIcon={<PlayIcon />}
                    onClick={() => addToQueue.mutate(Array.from(selectedVideos))}
                    disabled={selectedVideos.size === 0 || addToQueue.isPending}
                >
                    {addToQueue.isPending ? 'Adding...' : `Process Selected (${selectedVideos.size})`}
                </Button>

                <Button
                    variant="outlined"
                    color="error"
                    startIcon={<CancelIcon />}
                    onClick={() => cancelBulkJobs.mutate(Array.from(selectedVideos))}
                    disabled={selectedVideos.size === 0 || cancelBulkJobs.isPending}
                >
                    {cancelBulkJobs.isPending ? 'Cancelling...' : `Cancel Queued (${selectedVideos.size})`}
                </Button>

                <Tooltip title="Refresh list">
                    <IconButton onClick={() => refetch()}>
                        <RefreshIcon />
                    </IconButton>
                </Tooltip>

                <Tooltip title="View worker logs">
                    <Button
                        variant="outlined"
                        size="small"
                        startIcon={<LogIcon />}
                        onClick={() => setShowLogModal(true)}
                    >
                        View Logs
                    </Button>
                </Tooltip>
            </Paper>

            {/* Instructions */}
            {(!videos || videos.length === 0) && (
                <Alert severity="info" sx={{ mb: 3 }}>
                    No videos need processing. Upload videos using the Ingest GUI to see them here.
                </Alert>
            )}

            {/* Video table */}
            {videos && videos.length > 0 && (
                <TableContainer component={Paper}>
                    <Table>
                        <TableHead>
                            <TableRow>
                                <TableCell padding="checkbox">
                                    <Checkbox
                                        checked={selectedVideos.size === videos.length && videos.length > 0}
                                        indeterminate={selectedVideos.size > 0 && selectedVideos.size < videos.length}
                                        onChange={toggleAll}
                                    />
                                </TableCell>
                                <TableCell sx={{ minWidth: 350 }}>
                                    <TableSortLabel
                                        active={sortBy === 'title'}
                                        direction={sortBy === 'title' ? sortDir : 'asc'}
                                        onClick={() => handleSort('title')}
                                    >
                                        Video
                                    </TableSortLabel>
                                </TableCell>
                                <TableCell>
                                    <TableSortLabel
                                        active={sortBy === 'channel'}
                                        direction={sortBy === 'channel' ? sortDir : 'asc'}
                                        onClick={() => handleSort('channel')}
                                    >
                                        Channel
                                    </TableSortLabel>
                                </TableCell>
                                <TableCell>
                                    <TableSortLabel
                                        active={sortBy === 'duration'}
                                        direction={sortBy === 'duration' ? sortDir : 'asc'}
                                        onClick={() => handleSort('duration')}
                                    >
                                        Duration
                                    </TableSortLabel>
                                </TableCell>
                                <TableCell>
                                    <TableSortLabel
                                        active={sortBy === 'progress'}
                                        direction={sortBy === 'progress' ? sortDir : 'asc'}
                                        onClick={() => handleSort('progress')}
                                    >
                                        Progress
                                    </TableSortLabel>
                                </TableCell>
                                <TableCell>
                                    <TableSortLabel
                                        active={sortBy === 'status'}
                                        direction={sortBy === 'status' ? sortDir : 'asc'}
                                        onClick={() => handleSort('status')}
                                    >
                                        Status
                                    </TableSortLabel>
                                </TableCell>
                                <TableCell>Actions</TableCell>
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {sortedVideos.map(video => (
                                <TableRow
                                    key={video.video_id}
                                    sx={{
                                        bgcolor: selectedVideos.has(video.video_id)
                                            ? 'action.selected'
                                            : 'inherit'
                                    }}
                                >
                                    <TableCell padding="checkbox">
                                        <Checkbox
                                            checked={selectedVideos.has(video.video_id)}
                                            onChange={() => toggleVideo(video.video_id)}
                                        />
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 350 }}>
                                        <Typography
                                            variant="body2"
                                            sx={{
                                                maxWidth: 400,
                                                display: '-webkit-box',
                                                WebkitLineClamp: 2,
                                                WebkitBoxOrient: 'vertical',
                                                overflow: 'hidden',
                                                lineHeight: 1.4
                                            }}
                                        >
                                            {video.video_title}
                                        </Typography>
                                    </TableCell>
                                    <TableCell>
                                        <Typography variant="body2" color="text.secondary">
                                            {video.channel_name}
                                        </Typography>
                                    </TableCell>
                                    <TableCell>
                                        {formatDuration(video.duration_seconds)}
                                    </TableCell>
                                    <TableCell sx={{ minWidth: 150 }}>
                                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                            <LinearProgress
                                                variant="determinate"
                                                value={getProgress(video)}
                                                sx={{ flexGrow: 1, height: 6, borderRadius: 1 }}
                                            />
                                            <Typography variant="caption" color="text.secondary">
                                                {video.completed_chunks}/{video.total_chunks}
                                            </Typography>
                                        </Box>
                                    </TableCell>
                                    <TableCell>
                                        {getStatusChip(video)}
                                    </TableCell>
                                    <TableCell>
                                        {video.failed_chunks > 0 && (
                                            <Tooltip title={`Retry ${video.failed_chunks} failed chunks`}>
                                                <IconButton
                                                    size="small"
                                                    onClick={() => retryFailed.mutate(video.video_id)}
                                                    disabled={retryFailed.isPending}
                                                >
                                                    <RefreshIcon fontSize="small" />
                                                </IconButton>
                                            </Tooltip>
                                        )}
                                    </TableCell>
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                </TableContainer>
            )}

            {/* Instructions */}
            <Alert severity="info" sx={{ mt: 3 }}>
                <Typography variant="body2" gutterBottom>
                    <strong>How it works:</strong>
                </Typography>
                <Typography variant="body2">
                    1. Select videos and click "Process Selected" to add their chunks to the queue.<br />
                    2. The background worker processes one chunk at a time (run with: <code>python -m backend.processing.gemini_worker --queue</code>).<br />
                    3. Real-time updates show progress. Failed chunks can be retried using the refresh button.
                </Typography>
            </Alert>

            {/* Log Viewer Modal */}
            <Dialog
                open={showLogModal}
                onClose={() => setShowLogModal(false)}
                maxWidth="lg"
                fullWidth
            >
                <DialogTitle sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <LogIcon />
                    Gemini Worker Logs
                    <Box sx={{ flexGrow: 1 }} />
                    <Tooltip title="Refresh logs">
                        <IconButton
                            onClick={() => refetchLogs()}
                            disabled={loadingLogs}
                            size="small"
                        >
                            <RefreshIcon />
                        </IconButton>
                    </Tooltip>
                </DialogTitle>
                <DialogContent>
                    {logsData?.exists === false ? (
                        <Alert severity="warning">
                            {logsData.message || 'Log file not found. Start the worker to generate logs.'}
                        </Alert>
                    ) : (
                        <Box
                            sx={{
                                bgcolor: '#1e1e1e',
                                color: '#d4d4d4',
                                fontFamily: 'monospace',
                                fontSize: '12px',
                                p: 2,
                                borderRadius: 1,
                                maxHeight: '60vh',
                                overflow: 'auto',
                                whiteSpace: 'pre-wrap',
                                wordBreak: 'break-word',
                            }}
                        >
                            {logsData?.lines?.length ? (
                                logsData.lines.map((line, i) => (
                                    <Box key={i} sx={{
                                        py: 0.25,
                                        borderBottom: '1px solid #333',
                                        color: line.includes('[ERROR]') ? '#f48771' :
                                            line.includes('[WARNING]') ? '#dcdcaa' :
                                                line.includes('[INFO]') ? '#9cdcfe' : '#d4d4d4'
                                    }}>
                                        {line}
                                    </Box>
                                ))
                            ) : (
                                <Typography color="text.secondary">No log entries yet.</Typography>
                            )}
                        </Box>
                    )}
                    {logsData?.total_lines && (
                        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
                            Showing last 200 of {logsData.total_lines} lines
                        </Typography>
                    )}
                </DialogContent>
                <DialogActions>
                    <Button onClick={() => setShowLogModal(false)}>Close</Button>
                </DialogActions>
            </Dialog>
        </Box>
    )
}
