/**
 * Dashboard Page
 * 
 * Overview of all channels with statistics and system stats.
 * Stats-only view - navigation to channels is via Channel tab.
 */

import {
    Box,
    Typography,
    Chip,
    Skeleton,
    Alert,
    Table,
    TableBody,
    TableCell,
    TableContainer,
    TableHead,
    TableRow,
    Paper,
} from '@mui/material'
import { Folder, VideoLibrary, Pending, CheckCircle, AccessTime, Lock, HourglassEmpty, TrendingUp, Flag } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
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

interface SystemStats {
    total_channels: number
    total_videos: number
    total_chunks: number
    total_segments: number
    approved_segments: number
    total_hours: number
    // Project Progress
    verified_hours: number
    target_hours: number
    completion_percentage: number
    // Workflow Status
    chunks_pending_review: number
    active_locks: number
}

interface DashboardPageProps {
    userId: number
}

export function DashboardPage({ userId }: DashboardPageProps) {
    // Configure API header
    api.defaults.headers.common['X-User-ID'] = userId.toString()

    // Fetch channels
    const { data: channels = [], isLoading: loadingChannels, error: channelError } = useQuery<Channel[]>({
        queryKey: ['channels'],
        queryFn: () => api.get('/channels').then(res => res.data),
    })

    // Fetch channel stats
    const { data: channelStats = [] } = useQuery<ChannelStats[]>({
        queryKey: ['channels', 'stats'],
        queryFn: () => api.get('/channels/stats').then(res => res.data).catch(() => []),
    })

    // Fetch system stats
    const { data: systemStats } = useQuery<SystemStats>({
        queryKey: ['system', 'stats'],
        queryFn: () => api.get('/stats').then(res => res.data).catch(() => null),
    })

    // Get stats for a channel
    const getChannelStats = (channelId: number): ChannelStats | undefined => {
        return channelStats.find(s => s.channel_id === channelId)
    }

    if (channelError) {
        return (
            <Box className="dashboard-container" sx={{ height: '100%', overflow: 'auto', p: 3 }}>
                <Alert severity="error">Failed to load channels. Is the backend running?</Alert>
            </Box>
        )
    }

    return (
        <Box className="dashboard-container" sx={{ height: '100%', overflow: 'auto', p: 3 }}>
            {/* System Stats Panel - Volume & Inventory */}
            <Box className="stats-panel">
                <Typography variant="h5" className="panel-title">
                    📊 System Overview
                </Typography>
                <Box className="stats-grid">
                    <Box className="stat-card">
                        <Folder sx={{ fontSize: 40, color: '#90caf9' }} />
                        <Typography variant="h4">{systemStats?.total_channels || channels.length}</Typography>
                        <Typography color="text.secondary">Channels</Typography>
                    </Box>
                    <Box className="stat-card">
                        <VideoLibrary sx={{ fontSize: 40, color: '#80deea' }} />
                        <Typography variant="h4">{systemStats?.total_videos || 0}</Typography>
                        <Typography color="text.secondary">Videos</Typography>
                    </Box>
                    <Box className="stat-card">
                        <AccessTime sx={{ fontSize: 40, color: '#a5d6a7' }} />
                        <Typography variant="h4">{systemStats?.total_hours?.toFixed(1) || '0.0'}</Typography>
                        <Typography color="text.secondary">Hours</Typography>
                    </Box>
                    <Box className="stat-card">
                        <Pending sx={{ fontSize: 40, color: '#ffcc80' }} />
                        <Typography variant="h4">{systemStats?.total_chunks || 0}</Typography>
                        <Typography color="text.secondary">Total Chunks</Typography>
                    </Box>
                    <Box className="stat-card">
                        <CheckCircle sx={{ fontSize: 40, color: '#81c784' }} />
                        <Typography variant="h4">{systemStats?.total_segments || 0}</Typography>
                        <Typography color="text.secondary">Total Segments</Typography>
                    </Box>
                </Box>
            </Box>

            {/* Project Progress Panel */}
            <Box className="stats-panel">
                <Typography variant="h5" className="panel-title">
                    🎯 Project Progress
                </Typography>
                <Box className="stats-grid">
                    <Box className="stat-card">
                        <CheckCircle sx={{ fontSize: 40, color: '#4caf50' }} />
                        <Typography variant="h4">{systemStats?.verified_hours?.toFixed(2) || '0.00'}</Typography>
                        <Typography color="text.secondary">Verified Hours</Typography>
                    </Box>
                    <Box className="stat-card">
                        <Flag sx={{ fontSize: 40, color: '#2196f3' }} />
                        <Typography variant="h4">{systemStats?.target_hours || 50}</Typography>
                        <Typography color="text.secondary">Target Hours</Typography>
                    </Box>
                    <Box className="stat-card" sx={{
                        background: `linear-gradient(90deg, rgba(76, 175, 80, 0.2) ${systemStats?.completion_percentage || 0}%, transparent ${systemStats?.completion_percentage || 0}%)`
                    }}>
                        <TrendingUp sx={{ fontSize: 40, color: (systemStats?.completion_percentage || 0) >= 50 ? '#4caf50' : '#ff9800' }} />
                        <Typography variant="h4">{systemStats?.completion_percentage?.toFixed(1) || '0.0'}%</Typography>
                        <Typography color="text.secondary">Completion</Typography>
                    </Box>
                </Box>
            </Box>

            {/* Workflow Status Panel */}
            <Box className="stats-panel">
                <Typography variant="h5" className="panel-title">
                    ⚡ Workflow Status
                </Typography>
                <Box className="stats-grid">
                    <Box className="stat-card">
                        <HourglassEmpty sx={{ fontSize: 40, color: '#ff9800' }} />
                        <Typography variant="h4">{systemStats?.chunks_pending_review || 0}</Typography>
                        <Typography color="text.secondary">Pending Review</Typography>
                    </Box>
                    <Box className="stat-card">
                        <Lock sx={{ fontSize: 40, color: '#4caf50' }} />
                        <Typography variant="h4">{systemStats?.active_locks || 0}</Typography>
                        <Typography color="text.secondary">Active Locks</Typography>
                    </Box>
                </Box>
            </Box>

            {/* Channel List */}
            <Box className="channel-section">
                <Typography variant="h5" className="section-title">
                    📁 Channels
                </Typography>

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
                                </TableRow>
                            </TableHead>
                            <TableBody>
                                {channels.map(channel => {
                                    const stats = getChannelStats(channel.id)
                                    const hasPending = (stats?.pending_chunks || 0) > 0

                                    return (
                                        <TableRow
                                            key={channel.id}
                                            sx={{
                                                '&:hover': { bgcolor: 'rgba(255,255,255,0.02)' }
                                            }}
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
                                                    <Chip
                                                        label="Needs review"
                                                        size="small"
                                                        color="warning"
                                                    />
                                                ) : (stats?.approved_chunks || 0) > 0 ? (
                                                    <Chip
                                                        label="Up to date"
                                                        size="small"
                                                        color="success"
                                                        variant="outlined"
                                                    />
                                                ) : (
                                                    <Chip
                                                        label="Empty"
                                                        size="small"
                                                        variant="outlined"
                                                    />
                                                )}
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
