/**
 * Enhanced Segment Table Component - Refactored
 * 
 * Changes from previous version:
 * - Replaced renderCell TextFields with proper editable cells
 * - Fixed checkbox click propagation
 * - Added bulk operations (verify, reject)
 * - Removed maxRows to show full text
 * - Added selection mode
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import {
    Box,
    IconButton,
    Checkbox,
    TextField,
    Tooltip,
    Typography,
    Button,
    ButtonGroup,
} from '@mui/material'
import {
    PlayArrow as PlayIcon,
    CheckCircle,
    Circle,
    Delete,
    Check,
    Cancel,
} from '@mui/icons-material'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../api/client'

interface Segment {
    id: number
    chunk_id: number
    start_time_relative: number
    end_time_relative: number
    transcript: string
    translation: string
    is_verified: boolean
    is_rejected: boolean
}

interface SegmentTableProps {
    segments: Segment[]
    chunkId: number
    activeSegmentId?: number | null
    onPlaySegment?: (startTime: number, endTime: number, segmentId: number) => void
    onSegmentChange?: () => void
    onSegmentSaved?: () => void
    onActiveChange?: (segmentId: number | null) => void
    onSaveAll?: () => void  // Parent triggers this, we call saveAllChanges
    saveAllRef?: React.MutableRefObject<(() => void) | null>  // Expose save function to parent
}

// Format time as M:SS.mmm
function formatTime(seconds: number): string {
    const mins = Math.floor(seconds / 60)
    const secs = Math.floor(seconds % 60)
    const ms = Math.floor((seconds % 1) * 1000)
    return `${mins}:${secs.toString().padStart(2, '0')}.${ms.toString().padStart(3, '0')}`
}

// Parse time string M:SS.mmm to seconds
function parseTime(timeStr: string): number | null {
    const match = timeStr.match(/^(\d+):(\d{2})\.(\d{3})$/)
    if (match) {
        return parseInt(match[1]) * 60 + parseInt(match[2]) + parseInt(match[3]) / 1000
    }
    return null
}

export function SegmentTable({
    segments,
    chunkId,
    activeSegmentId,
    onPlaySegment,
    onSegmentChange,
    onSegmentSaved,
    onActiveChange,
    saveAllRef,
}: SegmentTableProps) {
    const queryClient = useQueryClient()
    const [editedRows, setEditedRows] = useState<Map<number, Partial<Segment>>>(new Map())
    const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
    const tableRef = useRef<HTMLDivElement>(null)

    // Update segment mutation
    const updateMutation = useMutation({
        mutationFn: ({ id, ...data }: { id: number } & Partial<Segment>) =>
            api.put(`/segments/${id}`, data),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
            onSegmentSaved?.()
        },
    })

    // Bulk verify mutation
    const bulkVerifyMutation = useMutation({
        mutationFn: (ids: number[]) => {
            console.log('[SegmentTable] bulkVerify called with IDs:', ids, 'chunkId:', chunkId)
            return api.post('/segments/bulk-verify', { segment_ids: ids })
        },
        onSuccess: (response) => {
            console.log('[SegmentTable] bulkVerify success:', response.data)
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
            setSelectedIds(new Set())
        },
        onError: (error: any) => {
            console.error('[SegmentTable] bulkVerify error:', error.response?.data || error.message)
        },
    })

    // Bulk reject (mark as rejected) mutation
    const bulkRejectMutation = useMutation({
        mutationFn: (ids: number[]) => {
            console.log('[SegmentTable] bulkReject called with IDs:', ids, 'chunkId:', chunkId)
            return api.post('/segments/bulk-reject', { segment_ids: ids })
        },
        onSuccess: (response) => {
            console.log('[SegmentTable] bulkReject success:', response.data)
            queryClient.invalidateQueries({ queryKey: ['segments', chunkId] })
            setSelectedIds(new Set())
        },
        onError: (error: any) => {
            console.error('[SegmentTable] bulkReject error:', error.response?.data || error.message)
        },
    })

    // Manual save function - called by parent via ref
    const saveAllChanges = useCallback(() => {
        if (editedRows.size > 0) {
            editedRows.forEach((changes, id) => {
                if (Object.keys(changes).length > 0) {
                    updateMutation.mutate({ id, ...changes })
                }
            })
            setEditedRows(new Map())
        }
    }, [editedRows, updateMutation])

    // Expose save function to parent via ref
    useEffect(() => {
        if (saveAllRef) {
            saveAllRef.current = saveAllChanges
        }
    }, [saveAllRef, saveAllChanges])

    // Handle cell edit
    const handleCellEdit = useCallback((id: number, field: string, value: string | number) => {
        setEditedRows(prev => {
            const newMap = new Map(prev)
            const existing = newMap.get(id) || {}
            newMap.set(id, { ...existing, [field]: value })
            return newMap
        })
        onSegmentChange?.()
    }, [onSegmentChange])

    // Get current value (edited or original)
    const getValue = useCallback((row: Segment, field: keyof Segment) => {
        const edited = editedRows.get(row.id)
        if (edited && field in edited) {
            return edited[field]
        }
        return row[field]
    }, [editedRows])

    // Check if row has unsaved changes
    const hasChanges = useCallback((id: number) => {
        return editedRows.has(id) && Object.keys(editedRows.get(id) || {}).length > 0
    }, [editedRows])

    // Selection handlers
    const toggleSelect = useCallback((id: number, e: React.MouseEvent) => {
        e.stopPropagation()
        setSelectedIds(prev => {
            const newSet = new Set(prev)
            if (newSet.has(id)) {
                newSet.delete(id)
            } else {
                newSet.add(id)
            }
            return newSet
        })
    }, [])

    const selectAll = useCallback(() => {
        if (selectedIds.size === segments.length) {
            setSelectedIds(new Set())
        } else {
            setSelectedIds(new Set(segments.map(s => s.id)))
        }
    }, [segments, selectedIds.size])

    // Scroll active row into view
    useEffect(() => {
        if (activeSegmentId && tableRef.current) {
            const row = tableRef.current.querySelector(`[data-id="${activeSegmentId}"]`)
            row?.scrollIntoView({ behavior: 'smooth', block: 'center' })
        }
    }, [activeSegmentId])

    const allSelected = selectedIds.size === segments.length && segments.length > 0

    return (
        <Box ref={tableRef} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
            {/* Bulk operations toolbar */}
            {selectedIds.size > 0 && (
                <Box sx={{
                    p: 1,
                    bgcolor: 'rgba(33, 150, 243, 0.1)',
                    borderBottom: '1px solid rgba(255,255,255,0.1)',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 2
                }}>
                    <Typography variant="body2">
                        {selectedIds.size} selected
                    </Typography>
                    <ButtonGroup size="small">
                        <Button
                            startIcon={<Check />}
                            onClick={() => bulkVerifyMutation.mutate(Array.from(selectedIds))}
                            disabled={bulkVerifyMutation.isPending}
                        >
                            Verify Chosen
                        </Button>
                        <Button
                            startIcon={<Delete />}
                            onClick={() => bulkRejectMutation.mutate(Array.from(selectedIds))}
                            disabled={bulkRejectMutation.isPending}
                            color="error"
                        >
                            Reject Chosen
                        </Button>
                    </ButtonGroup>
                </Box>
            )}

            {/* Table header */}
            <Box sx={{
                display: 'grid',
                gridTemplateColumns: '40px 40px 40px 90px 90px 1fr 1fr',
                bgcolor: 'rgba(0,0,0,0.3)',
                borderBottom: '1px solid rgba(255,255,255,0.1)',
                py: 1,
                px: 1,
                fontSize: 13,
                fontWeight: 600,
                gap: 1,
            }}>
                <Box>
                    <Checkbox
                        size="small"
                        checked={allSelected}
                        indeterminate={selectedIds.size > 0 && !allSelected}
                        onChange={selectAll}
                    />
                </Box>
                <Box>✓</Box>
                <Box></Box>
                <Box>Start</Box>
                <Box>End</Box>
                <Box>Transcript</Box>
                <Box>Translation</Box>
            </Box>

            {/* Table body - scrollable */}
            <Box sx={{ flex: 1, overflow: 'auto' }}>
                {segments.map((segment) => {
                    const isActive = segment.id === activeSegmentId
                    const isSelected = selectedIds.has(segment.id)
                    const hasUnsaved = hasChanges(segment.id)

                    return (
                        <Box
                            key={segment.id}
                            data-id={segment.id}
                            onClick={() => onActiveChange?.(segment.id)}
                            sx={{
                                display: 'grid',
                                gridTemplateColumns: '40px 40px 40px 90px 90px 1fr 1fr',
                                py: 1.5,
                                px: 1,
                                gap: 1,
                                borderBottom: '1px solid rgba(255,255,255,0.05)',
                                cursor: 'pointer',
                                transition: 'background 0.2s',
                                bgcolor: isActive
                                    ? 'rgba(255, 193, 7, 0.1)'
                                    : hasUnsaved
                                        ? 'rgba(33, 150, 243, 0.08)'
                                        : 'transparent',
                                borderLeft: isActive ? '3px solid #ffc107' : '3px solid transparent',
                                '&:hover': {
                                    bgcolor: isActive
                                        ? 'rgba(255, 193, 7, 0.15)'
                                        : 'rgba(255,255,255,0.05)',
                                },
                            }}
                        >
                            {/* Selection checkbox */}
                            <Box onClick={(e) => toggleSelect(segment.id, e)}>
                                <Checkbox
                                    size="small"
                                    checked={isSelected}
                                />
                            </Box>

                            {/* Status icon - 3 states: verified (✓), rejected (✗), unreviewed (○) */}
                            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                                <Tooltip title={
                                    segment.is_verified ? 'Verified - Good to export' :
                                        segment.is_rejected ? 'Rejected - Will not export' :
                                            'Unreviewed'
                                }>
                                    <Box sx={{ display: 'flex', alignItems: 'center' }}>
                                        {segment.is_verified ? (
                                            <CheckCircle fontSize="small" sx={{ color: '#4caf50' }} />
                                        ) : segment.is_rejected ? (
                                            <Cancel fontSize="small" sx={{ color: '#f44336' }} />
                                        ) : (
                                            <Circle fontSize="small" sx={{ color: 'rgba(255,255,255,0.3)' }} />
                                        )}
                                    </Box>
                                </Tooltip>
                            </Box>

                            {/* Play button */}
                            <Box>
                                <IconButton
                                    size="small"
                                    onClick={(e) => {
                                        e.stopPropagation()
                                        onPlaySegment?.(
                                            segment.start_time_relative,
                                            segment.end_time_relative,
                                            segment.id
                                        )
                                    }}
                                    sx={{ color: isActive ? '#ffc107' : 'inherit' }}
                                >
                                    <PlayIcon fontSize="small" />
                                </IconButton>
                            </Box>

                            {/* Start time */}
                            <Box>
                                <TextField
                                    size="small"
                                    variant="standard"
                                    value={formatTime(getValue(segment, 'start_time_relative') as number)}
                                    onChange={(e) => {
                                        const seconds = parseTime(e.target.value)
                                        if (seconds !== null) {
                                            handleCellEdit(segment.id, 'start_time_relative', seconds)
                                        }
                                    }}
                                    onClick={(e) => e.stopPropagation()}
                                    sx={{
                                        width: 80,
                                        '& input': {
                                            fontFamily: 'JetBrains Mono, monospace',
                                            fontSize: 13,
                                        }
                                    }}
                                />
                            </Box>

                            {/* End time */}
                            <Box>
                                <TextField
                                    size="small"
                                    variant="standard"
                                    value={formatTime(getValue(segment, 'end_time_relative') as number)}
                                    onChange={(e) => {
                                        const seconds = parseTime(e.target.value)
                                        if (seconds !== null) {
                                            handleCellEdit(segment.id, 'end_time_relative', seconds)
                                        }
                                    }}
                                    onClick={(e) => e.stopPropagation()}
                                    sx={{
                                        width: 80,
                                        '& input': {
                                            fontFamily: 'JetBrains Mono, monospace',
                                            fontSize: 13,
                                        }
                                    }}
                                />
                            </Box>

                            {/* Transcript */}
                            <Box>
                                <TextField
                                    size="small"
                                    variant="standard"
                                    fullWidth
                                    multiline
                                    value={getValue(segment, 'transcript') as string}
                                    onChange={(e) => handleCellEdit(segment.id, 'transcript', e.target.value)}
                                    onClick={(e) => e.stopPropagation()}
                                    placeholder="Original speech..."
                                    sx={{
                                        '& textarea': { fontSize: 14, lineHeight: 1.5 },
                                    }}
                                />
                            </Box>

                            {/* Translation */}
                            <Box>
                                <TextField
                                    size="small"
                                    variant="standard"
                                    fullWidth
                                    multiline
                                    value={getValue(segment, 'translation') as string}
                                    onChange={(e) => handleCellEdit(segment.id, 'translation', e.target.value)}
                                    onClick={(e) => e.stopPropagation()}
                                    placeholder="English translation..."
                                    sx={{
                                        '& textarea': { fontSize: 14, lineHeight: 1.5 },
                                    }}
                                />
                            </Box>
                        </Box>
                    )
                })}
            </Box>

            {/* Footer with count */}
            <Box sx={{
                py: 1,
                px: 2,
                borderTop: '1px solid rgba(255,255,255,0.1)',
                display: 'flex',
                justifyContent: 'space-between',
                fontSize: 13,
                color: 'rgba(255,255,255,0.5)'
            }}>
                <span>{segments.length} segments</span>
                <span>{segments.filter(s => s.is_verified).length} / {segments.length} verified</span>
            </Box>
        </Box>
    )
}
