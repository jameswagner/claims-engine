import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { fetchClaims, getLastRequestMeta } from '../api/claims'
import { NavBar } from '../components/NavBar'
import { StatusBadge } from '../components/StatusBadge'
import type { Claim, ClaimStatus } from '../types/claim'

type Tab = 'all' | 'denied' | 'aging'

const TABS: { key: Tab; label: string }[] = [
  { key: 'all', label: 'All Claims' },
  { key: 'denied', label: 'Exceptions (Denied)' },
  { key: 'aging', label: 'Aging (>30 days)' },
]

const PAYERS = ['Aetna', 'Cigna', 'BCBS', 'UnitedHealthcare', 'Humana']

const STATUSES: ClaimStatus[] = [
  'CREATED', 'VALIDATED', 'SUBMITTING', 'SUBMITTED',
  'CLEARINGHOUSE_REJECTED', 'ADJUDICATED', 'PAID', 'DENIED',
]

function ageDays(claim: Claim): number {
  return Math.floor((Date.now() - new Date(claim.created_at).getTime()) / 86_400_000)
}

function isAging(claim: Claim): boolean {
  if (claim.status !== 'SUBMITTED') return false
  return ageDays(claim) > 30
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatCurrency(n: number | null) {
  if (n === null) return '—'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(n)
}

export function ClaimsList() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState<Tab>('all')
  const [filterPayer, setFilterPayer] = useState('')
  const [filterStatus, setFilterStatus] = useState<ClaimStatus | ''>('')
  const [requestBadge, setRequestBadge] = useState<{ id: string; ms: number } | null>(null)
  const navigate = useNavigate()
  const badgeTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  async function load() {
    setLoading(true)
    try {
      const data = await fetchClaims()
      setClaims(data)
      const meta = getLastRequestMeta()
      if (meta?.requestId) {
        setRequestBadge({ id: meta.requestId.slice(0, 8), ms: meta.durationMs })
        if (badgeTimer.current) clearTimeout(badgeTimer.current)
        badgeTimer.current = setTimeout(() => setRequestBadge(null), 4000)
      }
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 20_000)
    return () => { clearInterval(id); if (badgeTimer.current) clearTimeout(badgeTimer.current) }
  }, [])

  const visible = claims.filter(c => {
    if (tab === 'denied' && c.status !== 'DENIED') return false
    if (tab === 'aging' && !isAging(c)) return false
    if (filterPayer && c.insurance_payer !== filterPayer) return false
    if (filterStatus && c.status !== filterStatus) return false
    return true
  })

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      <div className="max-w-6xl mx-auto px-6 py-8">

        <div className="flex items-center justify-between mb-6">
          <h1 className="text-xl font-bold text-gray-900">Worklist</h1>
          <span className="text-sm text-gray-400">{visible.length} claims</span>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 mb-4 border-b border-gray-200">
          {TABS.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
                tab === t.key
                  ? 'border-indigo-600 text-indigo-700'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              {t.label}
              {t.key === 'denied' && claims.filter(c => c.status === 'DENIED').length > 0 && (
                <span className="ml-2 bg-red-100 text-red-700 text-xs rounded-full px-1.5 py-0.5">
                  {claims.filter(c => c.status === 'DENIED').length}
                </span>
              )}
              {t.key === 'aging' && claims.filter(isAging).length > 0 && (
                <span className="ml-2 bg-amber-100 text-amber-700 text-xs rounded-full px-1.5 py-0.5">
                  {claims.filter(isAging).length}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Filters */}
        <div className="flex gap-3 mb-4">
          <select
            value={filterPayer}
            onChange={e => setFilterPayer(e.target.value)}
            className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
          >
            <option value="">All payers</option>
            {PAYERS.map(p => <option key={p}>{p}</option>)}
          </select>

          {tab === 'all' && (
            <select
              value={filterStatus}
              onChange={e => setFilterStatus(e.target.value as ClaimStatus | '')}
              className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-300"
            >
              <option value="">All statuses</option>
              {STATUSES.map(s => <option key={s}>{s}</option>)}
            </select>
          )}
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          {loading && claims.length === 0 ? (
            <div className="py-16 text-center text-gray-400 text-sm">Loading…</div>
          ) : visible.length === 0 ? (
            <div className="py-16 text-center text-gray-400 text-sm">No claims match the current filters.</div>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-200 text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  <th className="text-left px-4 py-3">Patient</th>
                  <th className="text-left px-4 py-3">Provider</th>
                  <th className="text-left px-4 py-3">Payer</th>
                  <th className="text-left px-4 py-3">CPT</th>
                  <th className="text-left px-4 py-3">Status</th>
                  <th className="text-right px-4 py-3">Billed</th>
                  <th className="text-left px-4 py-3">Created</th>
                  <th className="text-right px-4 py-3">Age</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {visible.map(claim => {
                  const age = ageDays(claim)
                  const aging = isAging(claim)
                  return (
                    <tr
                      key={claim.id}
                      onClick={() => navigate(`/claims/${claim.id}`)}
                      className={`cursor-pointer transition-colors hover:bg-gray-50 ${aging ? 'bg-amber-50/40' : ''}`}
                    >
                      <td className="px-4 py-3 font-medium text-gray-900">{claim.patient_name}</td>
                      <td className="px-4 py-3 text-gray-500">{claim.provider_name}</td>
                      <td className="px-4 py-3 text-gray-600">{claim.insurance_payer}</td>
                      <td className="px-4 py-3 font-mono text-gray-600">{claim.cpt_code}</td>
                      <td className="px-4 py-3"><StatusBadge status={claim.status} /></td>
                      <td className="px-4 py-3 text-right text-gray-700">{formatCurrency(claim.billed_amount)}</td>
                      <td className="px-4 py-3 text-gray-400">{formatDate(claim.created_at)}</td>
                      <td className={`px-4 py-3 text-right font-mono text-xs ${aging ? 'text-amber-700 font-semibold' : 'text-gray-400'}`}>
                        {age}d
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Request tracer badge */}
        {requestBadge && (
          <div className="fixed bottom-4 right-4 bg-gray-900 text-gray-300 text-xs px-3 py-2 rounded-lg font-mono shadow-lg">
            ↩ {requestBadge.ms}ms · req-{requestBadge.id}
          </div>
        )}
      </div>
    </div>
  )
}
