import type { ClaimsAnalytics, FastForwardStatus } from '../types/claim'

const BASE = import.meta.env.VITE_API_URL

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`)
  if (!res.ok) throw new Error(`${res.status}`)
  return res.json()
}

async function post<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { method: 'POST' })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail ?? `${res.status}`)
  }
  return res.json()
}

export const fetchAnalytics = () => get<ClaimsAnalytics>('/analytics/claims')

export const fetchFastForwardStatus = () => get<FastForwardStatus>('/demo/fast-forward/status')

export const startFastForward = () => post<{ message: string }>('/demo/fast-forward')
