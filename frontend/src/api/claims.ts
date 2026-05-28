import type { Claim, ClaimDetail } from '../types/claim'

const BASE = import.meta.env.VITE_API_URL

interface ApiError {
  status: number
  detail: string | { errors: string[] }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw { status: res.status, detail: body.detail } as ApiError
  }
  return res.json() as Promise<T>
}

export const fetchClaims = () =>
  request<Claim[]>('/claims')

export const fetchClaim = (id: string) =>
  request<ClaimDetail>(`/claims/${id}`)

export const createClaim = (data: object) =>
  request<Claim>('/claims', { method: 'POST', body: JSON.stringify(data) })

export interface AdvanceBody {
  reason?: string
  allowed_amount?: number
  patient_responsibility?: number
  adjustment_reason?: string
}

export const advanceClaim = (id: string, body: AdvanceBody = {}) =>
  request<ClaimDetail>(`/claims/${id}/advance`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ reason: null, ...body }),
  })

export function parseApiError(e: unknown): string {
  const err = e as ApiError
  if (!err?.detail) return 'Something went wrong'
  if (typeof err.detail === 'string') return err.detail
  if (err.detail.errors) return err.detail.errors.join(' · ')
  return 'Something went wrong'
}
