import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createClaim, fetchClaims, parseApiError } from '../api/claims'
import { StatusBadge } from '../components/StatusBadge'
import type { Claim } from '../types/claim'

const SAMPLE_CLAIM = {
  patient_name: 'Alex Rivera',
  provider_name: 'Dr. Sarah Chen',
  cpt_code: '90837',
  diagnosis_code: 'F32.1',
  insurance_payer: 'Aetna',
  billed_amount: 200.00,
}

export function ClaimsList() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const navigate = useNavigate()

  useEffect(() => {
    fetchClaims().then(setClaims).catch(() => setError('Failed to load claims'))
  }, [])

  async function handleCreate() {
    setCreating(true)
    setError(null)
    try {
      const claim = await createClaim(SAMPLE_CLAIM)
      navigate(`/claims/${claim.id}`)
    } catch (e) {
      setError(parseApiError(e))
      setCreating(false)
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-5xl mx-auto px-4 py-10">

        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Claims</h1>
            <p className="text-sm text-gray-500 mt-0.5">Lifecycle tracker</p>
          </div>
          <button
            onClick={handleCreate}
            disabled={creating}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {creating ? 'Creating…' : '+ Create Test Claim'}
          </button>
        </div>

        {error && (
          <p className="mb-4 text-sm text-red-600">{error}</p>
        )}

        {claims.length === 0 ? (
          <div className="text-center py-20 text-gray-400">
            <p className="text-lg">No claims yet.</p>
            <p className="text-sm mt-1">Hit "Create Test Claim" to get started.</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {claims.map(claim => (
              <button
                key={claim.id}
                onClick={() => navigate(`/claims/${claim.id}`)}
                className="text-left bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md hover:border-gray-200 transition-all"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="min-w-0">
                    <p className="font-semibold text-gray-900 truncate">{claim.patient_name}</p>
                    <p className="text-sm text-gray-500 truncate">{claim.provider_name}</p>
                  </div>
                  <div className="ml-2 shrink-0">
                    <StatusBadge status={claim.status} />
                  </div>
                </div>
                <div className="text-sm text-gray-500 space-y-0.5">
                  <p>{claim.insurance_payer} · CPT {claim.cpt_code}</p>
                  <p className="font-mono text-xs text-gray-400">{claim.diagnosis_code}</p>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
