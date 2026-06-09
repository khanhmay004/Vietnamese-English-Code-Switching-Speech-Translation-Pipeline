/**
 * Settings Page
 * 
 * User management and system configuration.
 */

import { Box, Typography, Card, CardContent, Grid, Chip, Avatar, Divider } from '@mui/material'
import { Person, AdminPanelSettings, Folder, Storage, Api } from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api/client'
import '../styles/workbench.css'

interface User {
    id: number
    username: string
    role: string
}

interface SystemConfig {
    data_root: string
    api_version: string
    database_url: string
}

interface SettingsPageProps {
    userId: number
}

export function SettingsPage({ userId }: SettingsPageProps) {

    // Fetch users
    const { data: users = [], isLoading: loadingUsers } = useQuery<User[]>({
        queryKey: ['users'],
        queryFn: () => api.get('/users').then(res => res.data),
    })

    // Fetch system config (stubbed if not available)
    const { data: config } = useQuery<SystemConfig>({
        queryKey: ['system', 'config'],
        queryFn: () => api.get('/system/config').then(res => res.data).catch(() => ({
            data_root: '/mnt/data/project_speech',
            api_version: '1.0.0',
            database_url: 'postgresql://localhost/speech_db'
        })),
    })

    return (
        <Box className="settings-container">
            {/* Header */}
            <Box className="settings-header">
                <Typography variant="h5">⚙️ Settings</Typography>
                <Typography variant="body2" color="text.secondary">
                    User management and system configuration
                </Typography>
            </Box>

            <Grid container spacing={3}>
                {/* Users Panel */}
                <Grid item xs={12} md={6}>
                    <Card className="settings-card">
                        <CardContent>
                            <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Person /> Users
                            </Typography>
                            <Divider sx={{ mb: 2 }} />

                            {loadingUsers ? (
                                <Typography>Loading users...</Typography>
                            ) : (
                                <Box className="user-list">
                                    {users.map(user => (
                                        <Box key={user.id} className="user-item">
                                            <Avatar sx={{ bgcolor: user.role === 'admin' ? '#f44336' : '#2196f3' }}>
                                                {user.role === 'admin' ? <AdminPanelSettings /> : <Person />}
                                            </Avatar>
                                            <Box sx={{ flex: 1 }}>
                                                <Typography fontWeight={600}>{user.username}</Typography>
                                                <Typography variant="body2" color="text.secondary">
                                                    ID: {user.id}
                                                </Typography>
                                            </Box>
                                            <Chip
                                                label={user.role}
                                                size="small"
                                                color={user.role === 'admin' ? 'error' : 'default'}
                                            />
                                            {user.id === userId && (
                                                <Chip label="You" size="small" color="primary" variant="outlined" />
                                            )}
                                        </Box>
                                    ))}
                                </Box>
                            )}
                        </CardContent>
                    </Card>
                </Grid>

                {/* System Info Panel */}
                <Grid item xs={12} md={6}>
                    <Card className="settings-card">
                        <CardContent>
                            <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                <Storage /> System Information
                            </Typography>
                            <Divider sx={{ mb: 2 }} />

                            <Box className="config-list">
                                <Box className="config-item">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Folder fontSize="small" sx={{ color: '#90caf9' }} />
                                        <Typography variant="body2" color="text.secondary">Data Root</Typography>
                                    </Box>
                                    <Typography variant="body2" sx={{ fontFamily: 'monospace', bgcolor: 'rgba(0,0,0,0.2)', p: 0.5, borderRadius: 1 }}>
                                        {config?.data_root || '/mnt/data/project_speech'}
                                    </Typography>
                                </Box>

                                <Box className="config-item">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Api fontSize="small" sx={{ color: '#81c784' }} />
                                        <Typography variant="body2" color="text.secondary">API Version</Typography>
                                    </Box>
                                    <Chip label={config?.api_version || 'v1.0.0'} size="small" color="success" />
                                </Box>

                                <Box className="config-item">
                                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                        <Storage fontSize="small" sx={{ color: '#ffb74d' }} />
                                        <Typography variant="body2" color="text.secondary">Database</Typography>
                                    </Box>
                                    <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                                        PostgreSQL (Local)
                                    </Typography>
                                </Box>
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>

                {/* Keyboard Shortcuts Panel */}
                <Grid item xs={12} md={6}>
                    <Card className="settings-card">
                        <CardContent>
                            <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                                ⌨️ Keyboard Shortcuts
                            </Typography>
                            <Divider sx={{ mb: 2 }} />

                            <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <Typography variant="body2">Play / Pause</Typography>
                                    <Chip label="Ctrl + Space" size="small" sx={{ fontFamily: 'monospace' }} />
                                </Box>
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <Typography variant="body2">Seek Backward 5s</Typography>
                                    <Chip label="Ctrl + ←" size="small" sx={{ fontFamily: 'monospace' }} />
                                </Box>
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <Typography variant="body2">Seek Forward 5s</Typography>
                                    <Chip label="Ctrl + →" size="small" sx={{ fontFamily: 'monospace' }} />
                                </Box>
                                <Divider />
                                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                    <Typography variant="body2">Save Changes</Typography>
                                    <Chip label="Ctrl + S" size="small" sx={{ fontFamily: 'monospace' }} />
                                </Box>
                            </Box>
                        </CardContent>
                    </Card>
                </Grid>
            </Grid>
        </Box>
    )
}
