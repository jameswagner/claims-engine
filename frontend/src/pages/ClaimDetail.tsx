import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  adjudicateClaim, denyClaim, fetchClaim, payClaim,
  parseApiError, resubmitClaim, submitClaim, validateClaim,
} from '../api/claims'
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

type Action = {
  label: string
  handler: () => Promise<ClaimDetailType>
}

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
      return {
        label: 'Resubmit →',
        handler: () => resubmitClaim(claim.id, 'Corrected CPT codes and modifiers'),
      }
    default:
      return null
  }
}

function denyAction(claim: ClaimDetailType): Action | null {
  if (claim.status !== 'ADJUDICATED') return null
  return {
    label: 'Deny',
    handler: () => denyClaim(claim.id, 'CO-97: procedure bundled'),
  }
}

export function ClaimDetail() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const [claim, setClaim] = useState<ClaimDetailType | null>(null)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (id) fetchClaim(id).then(setClaim).catch(() => setError('Claim not found'))
  }, [id])

  async function run(action: Action) {
    setWorking(true)
    setError(null)
    try {
      setClaim(await action.handler())
    } catch (e) {
      setError(parseApiError(e))
    } finally {
      setWorking(false)
    }
  }

  if (!claim) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-400">
        {error ?? 'Loading…'}
      </div>
    )
  }

  const primary = nextAction(claim)
  const deny = denyAction(claim)
  const hasFinancials = claim.allowed_amount !== null || claim.paid_amount !== null

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-2xl mx-auto px-4 py-10">

        <button
          onClick={() => navigate('/')}
          className="text-sm text-gray-500 hover:text-gray-800 mb-6 flex items-center gap-1 transition-colors"
        >
          ← Back to claims
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

        {/* Action buttons */}
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
