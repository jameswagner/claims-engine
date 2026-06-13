import type { ClaimsAnalytics, DenialRateDailyPoint, FastForwardResult, FastForwardStatus } from '../types/claim'

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

export const fetchDenialRateTimeseries = () => get<DenialRateDailyPoint[]>('/analytics/denial-rate-timeseries')

export const fetchFastForwardStatus = () => get<FastForwardStatus>('/demo/fast-forward/status')

export const stepFastForward = () => post<FastForwardResult>('/demo/fast-forward')

export const resetFastForward = () => post<{ message: string }>('/demo/fast-forward/reset')
