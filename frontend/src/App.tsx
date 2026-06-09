/**
 * Main App Component - 6-Tab Navigation System
 * 
 * Tabs:
 * 1. Dashboard - Channel overview
 * 2. Channel - Video list (Dynamic, appears when channel selected)
 * 3. Preprocessing - Gemini queue management
 * 4. Annotation - Workbench
 * 5. Export - Export wizard
 * 6. Settings - User/system config
 */

import { useState, useEffect } from 'react'
import {
    Box,
    Tabs,
    Tab,
    Select,
    MenuItem,
    FormControl,
    CircularProgress,
    Alert,
    Typography,
    Avatar,
    Chip,
} from '@mui/material'
import {
    Dashboard as DashboardIcon,
    VideoLibrary as ChannelIcon,
    Edit as AnnotationIcon,
    Psychology as PreprocessingIcon,
    FileDownload as ExportIcon,
    Settings as SettingsIcon,
    Person,
} from '@mui/icons-material'
import { useQuery } from '@tanstack/react-query'
import { api, setApiUserId } from './api/client'

// Page imports
import { DashboardPage } from './pages/DashboardPage'
import { ChannelPage } from './pages/ChannelPage'
import { PreprocessingPage } from './pages/PreprocessingPage'
import { WorkbenchPage } from './pages/WorkbenchPage'
import { ExportPage } from './pages/ExportPage'
import { SettingsPage } from './pages/SettingsPage'

// Types
interface User {
    id: number
    username: string
    role: string
}

// Tab configuration
type TabId = 'dashboard' | 'channel' | 'preprocessing' | 'annotation' | 'export' | 'settings'

interface TabConfig {
    id: TabId
    label: string
    icon: React.ReactElement
    dynamic?: boolean  // If true, only shows when condition is met
}

const TABS: TabConfig[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <DashboardIcon /> },
    { id: 'channel', label: 'Channel', icon: <ChannelIcon /> },
    { id: 'preprocessing', label: 'Preprocessing', icon: <PreprocessingIcon /> },
    { id: 'annotation', label: 'Annotation', icon: <AnnotationIcon /> },
    { id: 'export', label: 'Export', icon: <ExportIcon /> },
    { id: 'settings', label: 'Settings', icon: <SettingsIcon /> },
]

function App() {
    const [selectedUserId, setSelectedUserId] = useState<number | null>(null)
    const [currentTab, setCurrentTab] = useState<TabId>('dashboard')
    const [selectedVideoId, setSelectedVideoId] = useState<number | null>(null)
    const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null)

    // Channel Tab Persistence State
    const [channelTabSelectedChannelId, setChannelTabSelectedChannelId] = useState<number | null>(null)
    const [channelTabExpandedVideoId, setChannelTabExpandedVideoId] = useState<number | null>(null)

    // Fetch users
    const { data: users, isLoading, error } = useQuery<User[]>({
        queryKey: ['users'],
        queryFn: () => api.get('/users').then(res => res.data),
    })

    // Set default user on load
    useEffect(() => {
        if (users && users.length > 0 && !selectedUserId) {
            setSelectedUserId(users[0].id)
        }
    }, [users, selectedUserId])

    // Configure axios default header for all API calls across the app
    useEffect(() => {
        setApiUserId(selectedUserId)
    }, [selectedUserId])

    const selectedUser = users?.find(u => u.id === selectedUserId)

    // Navigation handlers
    const handleVideoSelect = (videoId: number, chunkId?: number) => {
        setSelectedVideoId(videoId)
        if (chunkId) setSelectedChunkId(chunkId)
        setCurrentTab('annotation')
    }

    const handleTabChange = (_: React.SyntheticEvent, newValue: TabId) => {
        // If switching away from channel tab, clear channel selection
        if (newValue !== 'channel') {
            // Keep channel in case user wants to go back
        }
        setCurrentTab(newValue)
    }

    // All tabs are visible (no dynamic filtering needed)
    const visibleTabs = TABS

    // Loading state
    if (isLoading) {
        return (
            <Box className="app-loading">
                <CircularProgress size={48} />
                <Typography>Loading application...</Typography>
            </Box>
        )
    }

    // Error state
    if (error) {
        return (
            <Box className="app-error">
                <Alert severity="error" sx={{ maxWidth: 500 }}>
                    <Typography variant="h6" gutterBottom>Connection Error</Typography>
                    <Typography>
                        Failed to connect to the backend API. Please ensure the FastAPI server
                        is running on port 8000.
                    </Typography>
                </Alert>
            </Box>
        )
    }

    // No user selected - User Selection Screen (gemini_ui_6)
    if (!selectedUserId) {
        return (
            <Box className="user-selection-screen">
                <Typography variant="h4" gutterBottom>
                    🎙️ Speech Translation Workbench
                </Typography>
                <Typography color="text.secondary" sx={{ mb: 3 }}>
                    Select your user profile to begin
                </Typography>

                <Box className="user-cards">
                    {users?.map(user => (
                        <Box
                            key={user.id}
                            className="user-card"
                            onClick={() => setSelectedUserId(user.id)}
                        >
                            <Avatar sx={{ width: 64, height: 64, bgcolor: 'primary.main' }}>
                                <Person sx={{ fontSize: 32 }} />
                            </Avatar>
                            <Typography fontWeight={600}>{user.username}</Typography>
                            <Chip
                                label={user.role}
                                size="small"
                                color={user.role === 'admin' ? 'error' : 'default'}
                            />
                        </Box>
                    ))}
                </Box>
            </Box>
        )
    }

    // Main app with tab navigation
    return (
        <Box className="app-container">
            {/* Header with tabs and user selector */}
            <Box className="app-header">
                {/* Logo removed as per user request */}

                <Box className="header-tabs">
                    <Tabs
                        value={currentTab}
                        onChange={handleTabChange}
                        textColor="inherit"
                        TabIndicatorProps={{
                            style: { backgroundColor: '#90caf9', height: 3 }
                        }}
                    >
                        {visibleTabs.map(tab => (
                            <Tab
                                key={tab.id}
                                value={tab.id}
                                icon={tab.icon}
                                iconPosition="start"
                                label={tab.label}
                                sx={{
                                    minHeight: 56,
                                    textTransform: 'none',
                                    fontSize: 14,
                                    fontWeight: 500,
                                    gap: 0.5,
                                }}
                            />
                        ))}
                    </Tabs>
                </Box>

                <Box className="header-right">
                    <FormControl size="small" sx={{ minWidth: 120 }}>
                        <Select
                            value={selectedUserId}
                            onChange={(e) => setSelectedUserId(Number(e.target.value))}
                            size="small"
                            sx={{ bgcolor: 'rgba(255,255,255,0.05)' }}
                        >
                            {users?.map(user => (
                                <MenuItem key={user.id} value={user.id}>
                                    {user.username}
                                </MenuItem>
                            ))}
                        </Select>
                    </FormControl>

                    {selectedUser && (
                        <Chip
                            label={selectedUser.role}
                            size="small"
                            color={selectedUser.role === 'admin' ? 'error' : 'default'}
                        />
                    )}
                </Box>
            </Box>

            {/* Tab content area */}
            <Box className="app-content">
                {currentTab === 'dashboard' && (
                    <DashboardPage userId={selectedUserId} />
                )}

                {currentTab === 'channel' && (
                    <ChannelPage
                        userId={selectedUserId}
                        onVideoSelect={handleVideoSelect}
                        persistedSelectedChannelId={channelTabSelectedChannelId}
                        onPersistChannelSelect={setChannelTabSelectedChannelId}
                        persistedExpandedVideoId={channelTabExpandedVideoId}
                        onPersistVideoExpand={setChannelTabExpandedVideoId}
                    />
                )}

                {currentTab === 'preprocessing' && (
                    <PreprocessingPage userId={selectedUserId} />
                )}

                {currentTab === 'annotation' && (
                    <WorkbenchPage
                        userId={selectedUserId}
                        username={selectedUser?.username || 'User'}
                        preselectedVideoId={selectedVideoId}
                        preselectedChunkId={selectedChunkId}
                        onBackToDashboard={() => {
                            // Clear selected IDs so we don't auto-reload the same chunk
                            setSelectedVideoId(null)
                            setSelectedChunkId(null)
                            setCurrentTab('channel')
                        }}
                    />
                )}

                {currentTab === 'export' && (
                    <ExportPage userId={selectedUserId} />
                )}

                {currentTab === 'settings' && (
                    <SettingsPage userId={selectedUserId} />
                )}
            </Box>
        </Box>
    )
}

export default App
