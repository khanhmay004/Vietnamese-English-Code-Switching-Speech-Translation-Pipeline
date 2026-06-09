/**
 * Channel Page - Two-View Navigation
 * 
 * View 1: Channel List (default) - Shows all channels with stats
 * View 2: Video List - Shows videos for selected channel
 * 
 * Back button returns to channel list (not dashboard).
 */

import React from 'react'
import {
    Box,
    Typography,
    IconButton,
    Chip,
    Button,
    Alert,
    Skeleton,
    Collapse,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper,
} from '@mui/material'
import {
    ArrowBack,
    ExpandMore,
    ExpandLess,
    Lock,
    LockOpen,
    CheckCircle,
    HourglassEmpty,
    PlayArrow,
    AccessTime,
    Build,
    Folder,
    VideoLibrary,
    Pending,
    ChevronRight,
} from '@mui/icons-material'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'
import '../styles/workbench.css'

interface Channel {
    id: number
    name: string
    url: string
}

interface ChannelStats {
    channel_id: number
    total_videos: number
    total_chunks: number
    pending_chunks: number
    approved_chunks: number
}

interface Video {
    id: number
    title: string
    channel_id: number
    duration_seconds: number
    original_url: string
    status: string
    created_at: string
}

interface VideoStats {
    video_id: number
    total_chunks: number
    pending_chunks: number
    approved_chunks: number
    total_segments: number
    verified_segments: number
}

interface ChunkInfo {
    id: number
    video_id: number
    chunk_index: number
    audio_path: string
    status: string
    locked_by_user_id: number | null
    locked_by_username: string | null
    lock_expires_at: string | null
    segment_count: number
}

interface ChannelPageProps {
    userId: number
    onVideoSelect: (videoId: number, chunkId?: number) => void
    persistedSelectedChannelId: number | null
    onPersistChannelSelect: (id: number | null) => void
    persistedExpandedVideoId: number | null
    onPersistVideoExpand: (id: number | null) => void
}

export function ChannelPage({
    userId,
    onVideoSelect,
    persistedSelectedChannelId,
    onPersistChannelSelect,
    persistedExpandedVideoId,
    onPersistVideoExpand
}: ChannelPageProps) {
    // Local state replaced by props-driven state
    // const [selectedChannel, setSelectedChannel] = useState<Channel | null>(null)
    // const [expandedVideoId, setExpandedVideoId] = useState<number | null>(null)

    const queryClient = useQueryClient()

    // Configure API header
    api.defaults.headers.common['X-User-ID'] = userId.toString()

    // ==================== CHANNEL LIST VIEW ====================

    // Fetch all channels
    const { data: channels = [], isLoading: loadingChannels } = useQuery<Channel[]>({
        queryKey: ['channels'],
        queryFn: () => api.get('/channels').then(res => res.data),
    })

    // Derive selected channel from persisted ID
    const selectedChannel = channels.find(c => c.id === persistedSelectedChannelId) || null

    // Fetch channel stats
    const { data: channelStats = [] } = useQuery<ChannelStats[]>({
        queryKey: ['channels', 'stats'],
        queryFn: () => api.get('/channels/stats').then(res => res.data).catch(() => []),
    })

    const getChannelStats = (channelId: number): ChannelStats | undefined => {
        return channelStats.find(s => s.channel_id === channelId)
    }

    // ==================== VIDEO LIST VIEW ====================

    // Fetch videos for selected channel
    const { data: videos = [], isLoading: loadingVideos, error: videoError } = useQuery<Video[]>({
        queryKey: ['videos', selectedChannel?.id],
        queryFn: () => api.get(`/channels/${selectedChannel!.id}/videos`).then(res => res.data),
        enabled: !!selectedChannel,
    })

    // Fetch video stats
    const { data: videoStats = [] } = useQuery<VideoStats[]>({
        queryKey: ['videos', 'stats', selectedChannel?.id],
        queryFn: () => api.get(`/channels/${selectedChannel!.id}/videos/stats`).then(res => res.data).catch(() => []),
        enabled: !!selectedChannel,
        refetchOnMount: 'always',  // Always refetch when tab becomes visible
    })

    // Fetch chunks for expanded video
    const { data: chunks = [], isLoading: loadingChunks } = useQuery<ChunkInfo[]>({
        queryKey: ['video', 'chunks', persistedExpandedVideoId],
        queryFn: () => api.get(`/videos/${persistedExpandedVideoId}/chunks`).then(res => res.data),
        enabled: !!persistedExpandedVideoId,
        refetchOnMount: 'always',  // Always refetch when tab becomes visible
    })

    const getVideoStats = (videoId: number): VideoStats | undefined => {
        return videoStats.find(s => s.video_id === videoId)
    }

    // ==================== MUTATIONS ====================

    // Unlock chunk mutation
    const unlockMutation = useMutation({
        mutationFn: (chunkId: number) => api.post(`/chunks/${chunkId}/unlock`),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['video', 'chunks', persistedExpandedVideoId] })
        },
    })

    // Manual chunking mutation
    const chunkMutation = useMutation({
        mutationFn: (videoId: number) => api.post(`/videos/${videoId}/chunk`),
        onSuccess: (_, videoId) => {
            queryClient.invalidateQueries({ queryKey: ['video', 'chunks', videoId] })
            queryClient.invalidateQueries({ queryKey: ['videos', 'stats', selectedChannel?.id] })
        },
    })

    // ==================== HELPERS ====================

    const formatDuration = (seconds: number): string => {
        const hours = Math.floor(seconds / 3600)
        const mins = Math.floor((seconds % 3600) / 60)
        if (hours > 0) return `${hours}h ${mins}m`
        return `${mins}m`
    }

    const toggleExpand = (videoId: number) => {
        onPersistVideoExpand(persistedExpandedVideoId === videoId ? null : videoId)
    }

    const getChunkStatusChip = (chunk: ChunkInfo) => {
        const isLockedByMe = chunk.locked_by_user_id === userId

        // Check APPROVED status FIRST - approved chunks should show approved, not locked
        if (chunk.status === 'approved' || chunk.status === 'APPROVED') {
            return <Chip icon={<CheckCircle fontSize="small" />} label="Approved" size="small" color="success" />
        }

        // Then check lock status for non-approved chunks
        if (chunk.locked_by_username) {
            if (isLockedByMe) {
                return (
                    <Chip
                        icon={<Lock fontSize="small" />}
                        label="Locked by you"
                        size="small"
                        color="success"
                        variant="outlined"
                    />
                )
            }
            return (
                <Chip
                    icon={<Lock fontSize="small" />}
                    label={`Locked by ${chunk.locked_by_username}`}
                    size="small"
                    color="warning"
                    variant="outlined"
                />
            )
        }

        switch (chunk.status) {
            case 'review_ready':
            case 'REVIEW_READY':
            case 'in_review':
            case 'IN_REVIEW':
                return <Chip icon={<PlayArrow fontSize="small" />} label="Ready" size="small" color="info" />
            case 'pending':
            case 'PENDING':
                return <Chip icon={<HourglassEmpty fontSize="small" />} label="Processing" size="small" color="default" />
            default:
                return <Chip label={chunk.status} size="small" />
        }
    }

    // ==================== CHANNEL LIST RENDER ====================

    if (!selectedChannel) {
        return (
            <Box className="channel-page" sx={{ height: '100%', overflow: 'auto', p: 3 }}>
                <Box className="channel-page-header">
                    <Typography variant="h5">📁 Channels</Typography>
                </Box>

                <Box className="video-section" sx={{ mt: 2 }}>
                    {loadingChannels ? (
                        <Box>
                            {[1, 2, 3].map(i => (
                                <Skeleton key={i} variant="rounded" height={56} sx={{ mb: 1 }} />
                            ))}
                        </Box>
                    ) : channels.length === 0 ? (
                        <Alert severity="info">
                            No channels yet. Use the ingestion tool to add YouTube channels.
                        </Alert>
                    ) : (
                        <TableContainer component={Paper} sx={{ bgcolor: 'rgba(255,255,255,0.02)', maxHeight: 500, overflow: 'auto' }}>
                            <Table stickyHeader>
                                <TableHead>
                                    <TableRow>
                                        <TableCell>Channel Name</TableCell>
                                        <TableCell width={100}>Videos</TableCell>
                                        <TableCell width={120}>Pending</TableCell>
                                        <TableCell width={120}>Approved</TableCell>
                                        <TableCell width={140}>Status</TableCell>
                                        <TableCell width={100}>Action</TableCell>
                                    </TableRow>
                                </TableHead>
                                <TableBody>
                                    {channels.map(channel => {
                                        const stats = getChannelStats(channel.id)
                                        const hasPending = (stats?.pending_chunks || 0) > 0

                                        return (
                                            <TableRow
                                                key={channel.id}
                                                hover
                                                sx={{
                                                    cursor: 'pointer',
                                                    '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' }
                                                }}
                                                onClick={() => onPersistChannelSelect(channel.id)}
                                            >
                                                <TableCell>
                                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                                        <Folder sx={{ color: '#90caf9' }} />
                                                        <Typography fontWeight={500}>
                                                            {channel.name}
                                                        </Typography>
                                                    </Box>
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        icon={<VideoLibrary sx={{ fontSize: 16 }} />}
                                                        label={stats?.total_videos || 0}
                                                        size="small"
                                                        variant="outlined"
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        icon={<Pending sx={{ fontSize: 16 }} />}
                                                        label={stats?.pending_chunks || 0}
                                                        size="small"
                                                        color={hasPending ? 'warning' : 'default'}
                                                        variant={hasPending ? 'filled' : 'outlined'}
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        icon={<CheckCircle sx={{ fontSize: 16 }} />}
                                                        label={stats?.approved_chunks || 0}
                                                        size="small"
                                                        color={(stats?.approved_chunks || 0) > 0 ? 'success' : 'default'}
                                                        variant="outlined"
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    {hasPending ? (
                                                        <Chip label="Needs review" size="small" color="warning" />
                                                    ) : (stats?.approved_chunks || 0) > 0 ? (
                                                        <Chip label="Up to date" size="small" color="success" variant="outlined" />
                                                    ) : (
                                                        <Chip label="Empty" size="small" variant="outlined" />
                                                    )}
                                                </TableCell>
                                                <TableCell>
                                                    <Button
                                                        size="small"
                                                        endIcon={<ChevronRight />}
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            onPersistChannelSelect(channel.id)
                                                        }}
                                                    >
                                                        View
                                                    </Button>
                                                </TableCell>
                                            </TableRow>
                                        )
                                    })}
                                </TableBody>
                            </Table>
                        </TableContainer>
                    )}
                </Box>
            </Box>
        )
    }

    // ==================== VIDEO LIST RENDER ====================

    if (videoError) {
        return (
            <Box className="channel-page">
                <Alert severity="error">Failed to load videos for this channel.</Alert>
            </Box>
        )
    }

    return (
        <Box className="channel-page" sx={{ height: '100%', overflow: 'auto', p: 3 }}>
            {/* Header with back button */}
            <Box className="channel-page-header">
                <IconButton onClick={() => onPersistChannelSelect(null)} sx={{ color: 'white', mr: 2 }}>
                    <ArrowBack />
                </IconButton>
                <Box>
                    <Typography variant="h5">{selectedChannel.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                        {videos.length} videos
                    </Typography>
                </Box>
            </Box>

            {/* Video List */}
            <Box className="video-section" sx={{ mt: 2 }}>
                {loadingVideos ? (
                    <Box>
                        {[1, 2, 3].map(i => (
                            <Skeleton key={i} variant="rounded" height={60} sx={{ mb: 1 }} />
                        ))}
                    </Box>
                ) : videos.length === 0 ? (
                    <Alert severity="info">
                        No videos in this channel yet. Use the ingestion tool to add videos.
                    </Alert>
                ) : (
                    <TableContainer component={Paper} sx={{ bgcolor: 'rgba(255,255,255,0.02)', maxHeight: 700, overflow: 'auto' }}>
                        <Table stickyHeader sx={{ minWidth: 1000 }}>
                            <TableHead>
                                <TableRow>
                                    <TableCell width={40}></TableCell>
                                    <TableCell>Video Title</TableCell>
                                    <TableCell width={120}>Duration</TableCell>
                                    <TableCell width={100}>Chunks</TableCell>
                                    <TableCell width={180}>Progress</TableCell>
                                    <TableCell width={160}>Actions</TableCell>
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {videos.map(video => {
                                    const stats = getVideoStats(video.id)
                                    const isExpanded = persistedExpandedVideoId === video.id
                                    const readyCount = (stats?.pending_chunks || 0)
                                    const approvedCount = stats?.approved_chunks || 0
                                    const totalCount = stats?.total_chunks || 0

                                    return (
                                        <React.Fragment key={video.id}>
                                            {/* Video Row */}
                                            <TableRow
                                                hover
                                                sx={{
                                                    cursor: 'pointer',
                                                    bgcolor: isExpanded ? 'rgba(144, 202, 249, 0.08)' : 'inherit',
                                                    '&:hover': { bgcolor: 'rgba(255,255,255,0.05)' }
                                                }}
                                                onClick={() => toggleExpand(video.id)}
                                            >
                                                <TableCell>
                                                    <IconButton size="small">
                                                        {isExpanded ? <ExpandLess /> : <ExpandMore />}
                                                    </IconButton>
                                                </TableCell>
                                                <TableCell>
                                                    <Typography
                                                        variant="body1"
                                                        sx={{
                                                            fontWeight: 500,
                                                            maxWidth: 500,
                                                            overflow: 'hidden',
                                                            display: '-webkit-box',
                                                            WebkitLineClamp: 2,
                                                            WebkitBoxOrient: 'vertical',
                                                            lineHeight: 1.3,
                                                        }}
                                                        title={video.title}
                                                    >
                                                        {video.title}
                                                    </Typography>
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        icon={<AccessTime sx={{ fontSize: 14 }} />}
                                                        label={formatDuration(video.duration_seconds)}
                                                        size="small"
                                                        variant="outlined"
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Chip
                                                        label={totalCount}
                                                        size="small"
                                                        color={totalCount === 0 ? 'error' : 'default'}
                                                        variant={totalCount === 0 ? 'filled' : 'outlined'}
                                                    />
                                                </TableCell>
                                                <TableCell>
                                                    <Typography variant="body2" color="text.secondary">
                                                        {totalCount > 0 ? `${approvedCount}/${totalCount} approved` : 'No chunks'}
                                                        {readyCount > 0 && ` • ${readyCount} ready`}
                                                    </Typography>
                                                </TableCell>
                                                <TableCell>
                                                    {totalCount === 0 ? (
                                                        <Button
                                                            size="small"
                                                            variant="contained"
                                                            color="warning"
                                                            startIcon={chunkMutation.isPending ? <HourglassEmpty /> : <Build />}
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                chunkMutation.mutate(video.id)
                                                            }}
                                                            disabled={chunkMutation.isPending}
                                                        >
                                                            {chunkMutation.isPending ? 'Chunking...' : 'Run Chunking'}
                                                        </Button>
                                                    ) : (
                                                        <Button
                                                            size="small"
                                                            variant="text"
                                                            onClick={(e) => {
                                                                e.stopPropagation()
                                                                toggleExpand(video.id)
                                                            }}
                                                        >
                                                            {isExpanded ? 'Collapse' : 'Show Chunks'}
                                                        </Button>
                                                    )}
                                                </TableCell>
                                            </TableRow>

                                            {/* Chunk List (Expanded) */}
                                            <TableRow key={`${video.id}-chunks`}>
                                                <TableCell colSpan={6} sx={{ p: 0, border: 0 }}>
                                                    <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                                                        <Box sx={{
                                                            bgcolor: 'rgba(0,0,0,0.2)',
                                                            p: 2,
                                                            borderLeft: '3px solid #90caf9'
                                                        }}>
                                                            {loadingChunks ? (
                                                                <Skeleton variant="rounded" height={100} />
                                                            ) : chunks.length === 0 ? (
                                                                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 2 }}>
                                                                    <Typography color="text.secondary">
                                                                        No chunks found for this video.
                                                                    </Typography>
                                                                    <Button
                                                                        variant="contained"
                                                                        color="warning"
                                                                        startIcon={chunkMutation.isPending ? <HourglassEmpty /> : <Build />}
                                                                        onClick={() => chunkMutation.mutate(video.id)}
                                                                        disabled={chunkMutation.isPending}
                                                                    >
                                                                        {chunkMutation.isPending ? 'Chunking...' : 'Run Chunking'}
                                                                    </Button>
                                                                    {chunkMutation.isError && (
                                                                        <Typography color="error" variant="body2">
                                                                            Chunking failed. Check server logs.
                                                                        </Typography>
                                                                    )}
                                                                </Box>
                                                            ) : (
                                                                <Table size="small" sx={{ minWidth: 550 }}>
                                                                    <TableHead>
                                                                        <TableRow>
                                                                            <TableCell>Chunk</TableCell>
                                                                            <TableCell>Status</TableCell>
                                                                            <TableCell>Segments</TableCell>
                                                                            <TableCell>Action</TableCell>
                                                                        </TableRow>
                                                                    </TableHead>
                                                                    <TableBody>
                                                                        {chunks.map(chunk => (
                                                                            <TableRow
                                                                                key={chunk.id}
                                                                                hover
                                                                                sx={{ '&:hover': { bgcolor: 'rgba(255,255,255,0.03)' } }}
                                                                            >
                                                                                <TableCell>
                                                                                    <Typography fontWeight={500}>
                                                                                        #{chunk.chunk_index + 1}
                                                                                    </Typography>
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {getChunkStatusChip(chunk)}
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {chunk.segment_count} segments
                                                                                </TableCell>
                                                                                <TableCell>
                                                                                    {(() => {
                                                                                        const isLockedByMe = chunk.locked_by_user_id === userId
                                                                                        const isLockedByOther = chunk.locked_by_username && !isLockedByMe
                                                                                        const isProcessing = chunk.status === 'pending' || chunk.status === 'PENDING'

                                                                                        return (
                                                                                            <Box sx={{ display: 'flex', gap: 1 }}>
                                                                                                <Button
                                                                                                    size="small"
                                                                                                    variant="contained"
                                                                                                    disabled={isLockedByOther || isProcessing}
                                                                                                    onClick={() => onVideoSelect(video.id, chunk.id)}
                                                                                                >
                                                                                                    {chunk.status === 'approved' || chunk.status === 'APPROVED' ? 'Re-review' : 'Review'}
                                                                                                </Button>
                                                                                                {isLockedByMe && (
                                                                                                    <Button
                                                                                                        size="small"
                                                                                                        variant="outlined"
                                                                                                        color="warning"
                                                                                                        startIcon={<LockOpen fontSize="small" />}
                                                                                                        onClick={(e) => {
                                                                                                            e.stopPropagation()
                                                                                                            unlockMutation.mutate(chunk.id)
                                                                                                        }}
                                                                                                        disabled={unlockMutation.isPending}
                                                                                                    >
                                                                                                        Unlock
                                                                                                    </Button>
                                                                                                )}
                                                                                            </Box>
                                                                                        )
                                                                                    })()}
                                                                                </TableCell>
                                                                            </TableRow>
                                                                        ))}
                                                                    </TableBody>
                                                                </Table>
                                                            )}
                                                        </Box>
                                                    </Collapse>
                                                </TableCell>
                                            </TableRow>
                                        </React.Fragment>
                                    )
                                })}
                            </TableBody>
                        </Table>
                    </TableContainer>
                )}
            </Box>
        </Box>
    )
}
