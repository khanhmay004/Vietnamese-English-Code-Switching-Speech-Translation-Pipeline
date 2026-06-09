/**
 * Export Page (gemini_ui_7)
 * 
 * Export configuration and dataset generation wizard.
 */

import { useState } from 'react'
import {
    Box,
    Typography,
    Button,
    Alert,

    CircularProgress,
    LinearProgress,
    FormControl,
    InputLabel,
    Select,
    MenuItem,
    Card,
    CardContent,
    Grid,
    Slider,
    FormControlLabel,
    Switch,
    Tooltip,
} from '@mui/material'
import {
    FileDownload,
    Folder,
    CheckCircle,
    Warning,
    Description,
    Speed,
    Timer,
} from '@mui/icons-material'
import { useQuery, useMutation } from '@tanstack/react-query'
import { api } from '../api/client'
import '../styles/workbench.css'

interface Channel {
    id: number
    name: string
}

interface ExportStats {
    total_approved_chunks: number
    total_verified_segments: number
    estimated_duration_hours: number
}

interface ExportResult {
    success: boolean
    manifest_path: string
    clips_count: number
    total_hours: number
    elapsed_seconds: number
    dry_run: boolean
}

interface ExportPageProps {
    userId: number
}

export function ExportPage({ userId: _userId }: ExportPageProps) {
    const [exportScope, setExportScope] = useState<'all' | 'channel'>('all')
    const [selectedChannel, setSelectedChannel] = useState<number | ''>('')
    const [exportResult, setExportResult] = useState<ExportResult | null>(null)
    const [workers, setWorkers] = useState<number>(8)
    const [dryRun, setDryRun] = useState<boolean>(false)

    // Fetch channels for selection
    const { data: channels = [] } = useQuery<Channel[]>({
        queryKey: ['channels'],
        queryFn: () => api.get('/channels').then(res => res.data),
    })

    // Fetch export preview stats
    const { data: stats, isLoading: loadingStats } = useQuery<ExportStats>({
        queryKey: ['export', 'stats', exportScope, selectedChannel],
        queryFn: () => {
            const params = exportScope === 'channel' && selectedChannel
                ? `?channel_id=${selectedChannel}`
                : ''
            return api.get(`/export/preview${params}`).then(res => res.data).catch(() => ({
                total_approved_chunks: 0,
                total_verified_segments: 0,
                estimated_duration_hours: 0
            }))
        },
    })

    // Export mutation
    const exportMutation = useMutation({
        mutationFn: () => {
            const params = exportScope === 'channel' && selectedChannel
                ? `?channel_id=${selectedChannel}`
                : ''
            return api.post(`/export/run${params}`, {
                workers,
                dry_run: dryRun
            }).then(res => res.data)
        },
        onSuccess: (data) => setExportResult(data),
    })

    const canExport = stats && stats.total_verified_segments > 0

    return (
        <Box className="export-container">
            {/* Header */}
            <Box className="export-header">
                <Box>
                    <Typography variant="h5">📦 Export Dataset</Typography>
                    <Typography variant="body2" color="text.secondary">
                        Generate training data from verified segments
                    </Typography>
                </Box>
            </Box>

            <Grid container spacing={3}>
                {/* Configuration Panel */}
                <Grid item xs={12} md={6}>
                    <Card className="export-config-card">
                        <CardContent>
                            <Typography variant="h6" gutterBottom>
                                Export Configuration
                            </Typography>

                            {/* Scope Selection */}
                            <FormControl fullWidth sx={{ mb: 2 }}>
                                <InputLabel>Export Scope</InputLabel>
                                <Select
                                    value={exportScope}
                                    label="Export Scope"
                                    onChange={(e) => {
                                        setExportScope(e.target.value as 'all' | 'channel')
                                        if (e.target.value === 'all') setSelectedChannel('')
                                    }}
                                >
                                    <MenuItem value="all">All Channels</MenuItem>
                                    <MenuItem value="channel">Specific Channel</MenuItem>
                                </Select>
                            </FormControl>

                            {/* Channel Selection (when scope is channel) */}
                            {exportScope === 'channel' && (
                                <FormControl fullWidth sx={{ mb: 2 }}>
                                    <InputLabel>Select Channel</InputLabel>
                                    <Select
                                        value={selectedChannel}
                                        label="Select Channel"
                                        onChange={(e) => setSelectedChannel(e.target.value as number)}
                                    >
                                        {channels.map(ch => (
                                            <MenuItem key={ch.id} value={ch.id}>
                                                {ch.name}
                                            </MenuItem>
                                        ))}
                                    </Select>
                                </FormControl>
                            )}

                            {/* Workers Slider */}
                            <Box sx={{ mb: 2 }}>
                                <Typography variant="body2" color="text.secondary" gutterBottom>
                                    <Speed sx={{ fontSize: 16, mr: 0.5, verticalAlign: 'text-bottom' }} />
                                    Parallel Workers: {workers}
                                </Typography>
                                <Slider
                                    value={workers}
                                    onChange={(_, value) => setWorkers(value as number)}
                                    min={1}
                                    max={32}
                                    step={1}
                                    marks={[
                                        { value: 1, label: '1' },
                                        { value: 8, label: '8' },
                                        { value: 16, label: '16' },
                                        { value: 32, label: '32' },
                                    ]}
                                    valueLabelDisplay="auto"
                                />
                            </Box>

                            {/* Dry Run Toggle */}
                            <Tooltip title="Generate manifest without cutting audio files (for testing)">
                                <FormControlLabel
                                    control={
                                        <Switch
                                            checked={dryRun}
                                            onChange={(e) => setDryRun(e.target.checked)}
                                            color="warning"
                                        />
                                    }
                                    label="Dry Run (manifest only)"
                                    sx={{ mb: 2 }}
                                />
                            </Tooltip>

                            {/* Export Button */}
                            <Button
                                variant="contained"
                                color={dryRun ? "warning" : "success"}
                                size="large"
                                fullWidth
                                startIcon={exportMutation.isPending ? <CircularProgress size={20} /> : <FileDownload />}
                                onClick={() => exportMutation.mutate()}
                                disabled={!canExport || exportMutation.isPending}
                            >
                                {exportMutation.isPending
                                    ? 'Exporting...'
                                    : dryRun
                                        ? 'Run Dry Export'
                                        : 'Start Export'}
                            </Button>

                            {!canExport && (
                                <Alert severity="warning" sx={{ mt: 2 }}>
                                    No verified segments available for export.
                                </Alert>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                {/* Preview Stats Panel */}
                <Grid item xs={12} md={6}>
                    <Card className="export-preview-card">
                        <CardContent>
                            <Typography variant="h6" gutterBottom>
                                Export Preview
                            </Typography>

                            {loadingStats ? (
                                <CircularProgress size={32} />
                            ) : (
                                <Box className="export-stats">
                                    <Box className="stat-row">
                                        <Folder sx={{ color: '#90caf9' }} />
                                        <Box>
                                            <Typography variant="h5">{stats?.total_approved_chunks || 0}</Typography>
                                            <Typography variant="body2" color="text.secondary">
                                                Approved Chunks
                                            </Typography>
                                        </Box>
                                    </Box>

                                    <Box className="stat-row">
                                        <CheckCircle sx={{ color: '#81c784' }} />
                                        <Box>
                                            <Typography variant="h5">{stats?.total_verified_segments || 0}</Typography>
                                            <Typography variant="body2" color="text.secondary">
                                                Verified Segments
                                            </Typography>
                                        </Box>
                                    </Box>

                                    <Box className="stat-row">
                                        <Description sx={{ color: '#ffb74d' }} />
                                        <Box>
                                            <Typography variant="h5">
                                                {stats?.estimated_duration_hours?.toFixed(1) || '0.0'}h
                                            </Typography>
                                            <Typography variant="body2" color="text.secondary">
                                                Estimated Duration
                                            </Typography>
                                        </Box>
                                    </Box>
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>

            {/* Export Progress */}
            {exportMutation.isPending && (
                <Box sx={{ mt: 3 }}>
                    <Alert severity="info">
                        <Typography>
                            {dryRun ? 'Generating manifest...' : 'Exporting dataset...'}
                            {' '}Using {workers} parallel workers.
                        </Typography>
                        <LinearProgress sx={{ mt: 1 }} />
                    </Alert>
                </Box>
            )}

            {/* Export Result */}
            {exportResult && (
                <Box sx={{ mt: 3 }}>
                    <Alert
                        severity={exportResult.dry_run ? "warning" : "success"}
                        icon={<CheckCircle />}
                    >
                        <Typography variant="h6">
                            Export Complete! {exportResult.dry_run && '(Dry Run)'}
                        </Typography>
                        <Typography>
                            Generated {exportResult.clips_count.toLocaleString()} clips
                            ({exportResult.total_hours.toFixed(1)} hours)
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 2, mt: 1, alignItems: 'center' }}>
                            <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                                📁 {exportResult.manifest_path}
                            </Typography>
                            <Typography variant="body2" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                                <Timer sx={{ fontSize: 16 }} />
                                {exportResult.elapsed_seconds}s
                            </Typography>
                        </Box>
                    </Alert>
                </Box>
            )}

            {/* Export Error */}
            {exportMutation.isError && (
                <Box sx={{ mt: 3 }}>
                    <Alert severity="error" icon={<Warning />}>
                        <Typography>Export failed. Please check server logs.</Typography>
                    </Alert>
                </Box>
            )}
        </Box>
    )
}
