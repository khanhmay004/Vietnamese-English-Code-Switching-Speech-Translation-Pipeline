/**
 * Shared Axios API Client
 * 
 * All components should import this instead of creating their own axios instance.
 * Auth headers are configured globally here.
 */

import axios from 'axios'

// Create single shared API instance
export const api = axios.create({
    baseURL: '/api',
})

// Function to set the user ID header (called from App.tsx when user is selected)
export function setApiUserId(userId: number | null) {
    if (userId) {
        api.defaults.headers.common['X-User-ID'] = userId.toString()
    } else {
        delete api.defaults.headers.common['X-User-ID']
    }
}
