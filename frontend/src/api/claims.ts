import type { Claim, ClaimDetail } from '../types/claim'

const BASE = import.meta.env.VITE_API_URL

export interface RequestMeta {
  requestId: string
  durationMs: number
}

let _lastMeta: RequestMeta | null = null
export const getLastRequestMeta = () => _lastMeta

interface ApiError {
  status: number
  detail: string | { errors: string[] }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const t0 = performance.now()
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  _lastMeta = {
    requestId: res.headers.get('X-Request-ID') ?? '',
    durationMs: Math.round(performance.now() - t0),
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw { status: res.status, detail: body.detail } as ApiError
  }
  return res.json() as Promise<T>
}

function withKey(extra?: Record<string, string>): HeadersInit {
  return { 'Content-Type': 'application/json', 'Idempotency-Key': crypto.randomUUID(), ...extra }
}

export const fetchClaims = () => request<Claim[]>('/claims')

export const fetchClaim = (id: string) => request<ClaimDetail>(`/claims/${id}`)

export const createClaim = (data: object) =>
  request<Claim>('/claims', { method: 'POST', body: JSON.stringify(data) })

export const validateClaim = (id: string) =>
  request<ClaimDetail>(`/claims/${id}/validate`, { method: 'POST', headers: withKey() })

export const submitClaim = (id: string, clearinghouse_ref?: string) =>
  request<ClaimDetail>(`/claims/${id}/submit`, {
    method: 'POST',
    headers: withKey(),
    body: JSON.stringify({ clearinghouse_ref: clearinghouse_ref ?? null }),
  })

export const adjudicateClaim = (id: string, allowed_amount: number, patient_responsibility: number, adjustment_reason?: string) =>
  request<ClaimDetail>(`/claims/${id}/adjudicate`, {
    method: 'POST',
    headers: withKey(),
    body: JSON.stringify({ allowed_amount, patient_responsibility, adjustment_reason: adjustment_reason ?? null }),
  })

export const payClaim = (id: string, paid_amount: number) =>
  request<ClaimDetail>(`/claims/${id}/pay`, {
    method: 'POST',
    headers: withKey(),
    body: JSON.stringify({ paid_amount }),
  })

export const denyClaim = (id: string, denial_reason: string) =>
  request<ClaimDetail>(`/claims/${id}/deny`, {
    method: 'POST',
    headers: withKey(),
    body: JSON.stringify({ denial_reason }),
  })

export const resubmitClaim = (id: string, correction_notes: string) =>
  request<ClaimDetail>(`/claims/${id}/resubmit`, {
    method: 'POST',
    headers: withKey(),
    body: JSON.stringify({ correction_notes }),
  })

export function parseApiError(e: unknown): string {
  const err = e as ApiError
  if (!err?.detail) return 'Something went wrong'
  if (typeof err.detail === 'string') return err.detail
  if (err.detail.errors) return err.detail.errors.join(' · ')
  return 'Something went wrong'
}
