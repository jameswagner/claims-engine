import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  adjudicateClaim, denyClaim, fetchClaim, payClaim,
  parseApiError, resubmitClaim, submitClaim, validateClaim,
} from '../api/claims'
import { NavBar } from '../components/NavBar'
import { StatusBadge } from '../components/StatusBadge'
import type { ClaimDetail as ClaimDetailType } from '../types/claim'

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: 'numeric', minute: '2-digit',
  })
}

function formatCurrency(n: number | null) {
  if (n === null) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n)
}

type Action = { label: string; handler: () => Promise<ClaimDetailType> }

function nextAction(claim: ClaimDetailType): Action | null {
  switch (claim.status) {
    case 'CREATED':
      return { label: 'Validate →', handler: () => validateClaim(claim.id) }
    case 'VALIDATED':
      return { label: 'Submit to Clearinghouse →', handler: () => submitClaim(claim.id) }
    case 'SUBMITTED':
      return {
        label: 'Record Adjudication →',
        handler: () => adjudicateClaim(claim.id, 150.00, 20.00, 'CO-45: charge exceeds fee schedule'),
      }
    case 'ADJUDICATED':
      return { label: 'Record Payment →', handler: () => payClaim(claim.id, 130.00) }
    case 'DENIED':
      return { label: 'Resubmit →', handler: () => resubmitClaim(claim.id, 'Corrected CPT codes and modifiers') }
    default:
      return null
  }
}

function denyAction(claim: ClaimDetailType): Action | null {
  if (claim.status !== 'ADJUDICATED') return null
  return { label: 'Deny', handler: () => denyClaim(claim.id, 'CO-97: procedure bundled') }
}

export function ClaimDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [claim, setClaim] = useState<ClaimDetailType | null>(null)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  function stopPolling() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }

  useEffect(() => {
    if (id) fetchClaim(id).then(c => { setClaim(c); maybeStartPolling(c) }).catch(() => setError('Claim not found'))
    return stopPolling
  }, [id])

  function maybeStartPolling(c: ClaimDetailType) {
    stopPolling()
    if (c.status === 'SUBMITTING') {
      pollRef.current = setInterval(() => {
        fetchClaim(c.id).then(updated => {
          setClaim(updated)
          if (updated.status !== 'SUBMITTING') stopPolling()
        }).catch(() => {})
      }, 2000)
    }
  }

  async function run(action: Action) {
    setWorking(true)
    setError(null)
    try {
      const updated = await action.handler()
      setClaim(updated)
      maybeStartPolling(updated)
    } catch (e) {
      setError(parseApiError(e))
    } finally {
      setWorking(false)
    }
  }

  if (!claim) {
    return (
      <div className="min-h-screen bg-gray-50">
        <NavBar />
        <div className="flex items-center justify-center py-32 text-gray-400">{error ?? 'Loading…'}</div>
      </div>
    )
  }

  const primary = nextAction(claim)
  const deny = denyAction(claim)
  const hasFinancials = claim.allowed_amount !== null || claim.paid_amount !== null
  const isSubmitting = claim.status === 'SUBMITTING'
  const isRejected = claim.status === 'CLEARINGHOUSE_REJECTED'

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <div className="max-w-2xl mx-auto px-4 py-10">

        <button
          onClick={() => navigate('/claims')}
          className="text-sm text-gray-500 hover:text-gray-800 mb-6 flex items-center gap-1 transition-colors"
        >
          ← Back to worklist
        </button>

        {/* Claim card */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 mb-4">
          <div className="flex items-start justify-between mb-5">
            <div>
              <h1 className="text-xl font-bold text-gray-900">{claim.patient_name}</h1>
              <p className="text-sm text-gray-400 mt-0.5">Created {formatDate(claim.created_at)}</p>
            </div>
            <StatusBadge status={claim.status} />
          </div>

          <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
            <div><dt className="text-gray-400">Provider</dt><dd className="font-medium text-gray-900 mt-0.5">{claim.provider_name}</dd></div>
            <div><dt className="text-gray-400">Payer</dt><dd className="font-medium text-gray-900 mt-0.5">{claim.insurance_payer}</dd></div>
            <div><dt className="text-gray-400">CPT Code</dt><dd className="font-medium font-mono text-gray-900 mt-0.5">{claim.cpt_code}</dd></div>
            <div><dt className="text-gray-400">Diagnosis</dt><dd className="font-medium font-mono text-gray-900 mt-0.5">{claim.diagnosis_code}</dd></div>
            <div><dt className="text-gray-400">Billed</dt><dd className="font-medium text-gray-900 mt-0.5">{formatCurrency(claim.billed_amount)}</dd></div>
          </dl>

          {hasFinancials && (
            <div className="mt-5 pt-5 border-t border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">Financials</p>
              <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
                {claim.allowed_amount !== null && (
                  <div><dt className="text-gray-400">Allowed</dt><dd className="font-medium text-gray-900 mt-0.5">{formatCurrency(claim.allowed_amount)}</dd></div>
                )}
                {claim.patient_responsibility !== null && (
                  <div><dt className="text-gray-400">Patient Resp.</dt><dd className="font-medium text-gray-900 mt-0.5">{formatCurrency(claim.patient_responsibility)}</dd></div>
                )}
                {claim.paid_amount !== null && (
                  <div><dt className="text-gray-400">Paid</dt><dd className="font-medium text-green-700 mt-0.5">{formatCurrency(claim.paid_amount)}</dd></div>
                )}
                {claim.adjustment_reason && (
                  <div className="col-span-2"><dt className="text-gray-400">Adjustment</dt><dd className="font-medium text-gray-900 mt-0.5">{claim.adjustment_reason}</dd></div>
                )}
              </dl>
            </div>
          )}
        </div>

        {/* SUBMITTING in-progress indicator */}
        {isSubmitting && (
          <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 flex items-center gap-3">
            <svg className="animate-spin h-4 w-4 text-amber-600" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="text-sm text-amber-800 font-medium">Processing with clearinghouse…</span>
          </div>
        )}

        {/* CLEARINGHOUSE_REJECTED alert */}
        {isRejected && (
          <div className="mb-4 bg-red-50 border border-red-200 rounded-lg px-4 py-4">
            <p className="text-sm font-semibold text-red-800 mb-1">Clearinghouse rejection</p>
            <p className="text-sm text-red-700 mb-3">
              {claim.events[claim.events.length - 1]?.reason ?? 'EDI validation failed'}
            </p>
            <button
              onClick={() => run({ label: 'Retry Submission', handler: () => resubmitClaim(claim.id, 'Resubmitting after clearinghouse rejection') })}
              disabled={working}
              className="px-3 py-1.5 text-sm font-medium bg-red-700 text-white rounded-lg hover:bg-red-800 disabled:opacity-40 transition-colors"
            >
              Retry Submission →
            </button>
          </div>
        )}

        {/* Action buttons */}
        {!isSubmitting && !isRejected && (
          <div className="flex gap-3 mb-4">
            {primary ? (
              <button
                onClick={() => run(primary)}
                disabled={working}
                className="flex-1 py-2.5 rounded-lg text-sm font-medium transition-colors bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {working ? 'Working…' : primary.label}
              </button>
            ) : (
              <div className="flex-1 py-2.5 rounded-lg text-sm font-medium text-center text-gray-400 bg-gray-100">
                Claim is {claim.status} — no further transitions
              </div>
            )}
            {deny && (
              <button
                onClick={() => run(deny)}
                disabled={working}
                className="px-4 py-2.5 rounded-lg text-sm font-medium transition-colors bg-red-50 text-red-700 hover:bg-red-100 disabled:opacity-40 disabled:cursor-not-allowed"
              >
                Deny
              </button>
            )}
          </div>
        )}

        {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

        {/* Event timeline */}
        {claim.events.length > 0 && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
            <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-5">Event Timeline</h2>
            <ol>
              {claim.events.map((event, i) => (
                <li key={event.id} className="flex gap-4">
                  <div className="flex flex-col items-center">
                    <div className="w-2.5 h-2.5 rounded-full bg-blue-400 mt-0.5 shrink-0" />
                    {i < claim.events.length - 1 && <div className="w-px flex-1 bg-gray-100 my-1" />}
                  </div>
                  <div className="pb-5 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm text-gray-500">{event.from_status} →</span>
                      <StatusBadge status={event.to_status} />
                    </div>
                    <p className="text-xs text-gray-400 mt-1">{formatDate(event.triggered_at)}</p>
                    {event.reason && <p className="text-xs text-gray-500 mt-1 italic">"{event.reason}"</p>}
                    {event.idempotency_key && (
                      <p className="text-xs text-gray-300 mt-1 font-mono" title={event.idempotency_key}>
                        key: {event.idempotency_key.slice(0, 8)}…
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
    </div>
  )
}
