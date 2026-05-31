import { useEffect, useState } from 'react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchAnalytics, fetchFastForwardStatus, startFastForward } from '../api/analytics'
import { NavBar } from '../components/NavBar'
import type { ClaimsAnalytics, FastForwardStatus } from '../types/claim'

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

function denialColor(rate: number): string {
  if (rate >= 30) return '#dc2626'
  if (rate >= 20) return '#f97316'
  if (rate >= 15) return '#f59e0b'
  return '#6b7280'
}

function secondsAgo(d: Date) {
  const s = Math.round((Date.now() - d.getTime()) / 1000)
  return s < 60 ? `${s}s ago` : `${Math.floor(s / 60)}m ago`
}

export function Dashboard() {
  const [analytics, setAnalytics] = useState<ClaimsAnalytics | null>(null)
  const [fastForward, setFastForward] = useState<FastForwardStatus>({ running: false, day: 0, total_days: 0, claims_created: 0 })
  const [dismissed, setDismissed] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [, setTick] = useState(0)
  const [launching, setLaunching] = useState(false)
  const [fastForwardError, setFastForwardError] = useState<string | null>(null)

  useEffect(() => {
    const load = () => fetchAnalytics().then(a => { setAnalytics(a); setLastUpdated(new Date()) }).catch(() => {})
    load()
    const id = setInterval(load, 20_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const poll = () => fetchFastForwardStatus().then(r => {
      setFastForward(prev => {
        if (r.running && !prev.running) setDismissed(false)
        return r
      })
    }).catch(() => {})
    poll()
    const id = setInterval(poll, 3_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 5_000)
    return () => clearInterval(id)
  }, [])

  async function handleStartFastForward() {
    setLaunching(true)
    setFastForwardError(null)
    try {
      await startFastForward()
      setDismissed(false)
    } catch (e: unknown) {
      setFastForwardError(e instanceof Error ? e.message : 'Failed to start fast-forward')
    } finally {
      setLaunching(false)
    }
  }

  const showBanner = fastForward.running && !dismissed
  const totalClaims = analytics
    ? Object.values(analytics.claims_by_status).reduce((a, b) => a + b, 0)
    : null
  const networkDenialRate = analytics
    ? (() => {
        const total = analytics.denial_rate_by_payer.reduce((a, r) => a + r.total, 0)
        const denied = analytics.denial_rate_by_payer.reduce((a, r) => a + r.denied, 0)
        return total > 0 ? ((denied / total) * 100).toFixed(1) : '—'
      })()
    : null
  const avgAdjDays = analytics?.avg_days_to_adjudication_by_payer.length
    ? (
        analytics.avg_days_to_adjudication_by_payer.reduce((a, r) => a + r.avg_days, 0) /
        analytics.avg_days_to_adjudication_by_payer.length
      ).toFixed(1)
    : null

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      {/* Fast-forward banner */}
      {showBanner && (
        <div className="bg-amber-50 border-b border-amber-200 px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse inline-block" />
            <span className="text-sm text-amber-800 font-medium">
              Fast-forwarding billing activity — Day {fastForward.day} of {fastForward.total_days} · {fastForward.claims_created} claims submitted
            </span>
            <div className="w-32 bg-amber-200 rounded-full h-1.5">
              <div
                className="bg-amber-500 h-1.5 rounded-full transition-all"
                style={{ width: `${fastForward.total_days ? (fastForward.day / fastForward.total_days) * 100 : 0}%` }}
              />
            </div>
          </div>
          <button onClick={() => setDismissed(true)} className="text-amber-500 hover:text-amber-700 text-sm ml-4">✕</button>
        </div>
      )}

      <div className="max-w-6xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Claims Dashboard</h1>
            <p className="text-sm text-gray-400 mt-0.5">Network-wide billing activity</p>
          </div>
          <div className="flex items-center gap-3">
            {fastForwardError && <span className="text-xs text-red-600">{fastForwardError}</span>}
            <button
              onClick={handleStartFastForward}
              disabled={launching || fastForward.running}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {fastForward.running ? 'Fast-forwarding…' : launching ? 'Starting…' : '⏩ Fast-forward'}
            </button>
          </div>
        </div>

        {/* Aging alert */}
        {analytics && analytics.aging_summary.over_30_days > 0 && (
          <div className="mb-6 bg-red-50 border border-red-200 rounded-lg px-4 py-3 flex items-center gap-3">
            <span className="text-red-500 font-bold">!</span>
            <span className="text-sm text-red-700">
              <strong>{analytics.aging_summary.over_30_days}</strong> claims past 30-day SLA —{' '}
              <a href="/claims" className="underline hover:no-underline">view aging queue →</a>
            </span>
          </div>
        )}

        {/* Metric cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
          <MetricCard
            label="Claims last 24h"
            value={analytics?.throughput_last_24h.created ?? '—'}
            sub="new claims created"
          />
          <MetricCard
            label="Network denial rate"
            value={networkDenialRate !== null ? `${networkDenialRate}%` : '—'}
            sub="across all payers"
          />
          <MetricCard
            label="Past 30-day SLA"
            value={analytics?.aging_summary.over_30_days ?? '—'}
            sub="claims in SUBMITTED"
          />
          <MetricCard
            label="Avg days to payment"
            value={avgAdjDays !== null ? `${avgAdjDays}d` : '—'}
            sub="SUBMITTED → ADJUDICATED"
          />
        </div>

        {/* Charts */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

          {/* Denial rate by payer */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Denial Rate by Payer</h2>
            {analytics?.denial_rate_by_payer.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={analytics.denial_rate_by_payer} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <XAxis dataKey="payer" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v}%`} domain={[0, 'auto']} />
                  <Tooltip formatter={(v: number | string) => [`${Number(v).toFixed(1)}%`, 'Denial rate']} />
                  <Bar dataKey="denial_rate_pct" radius={[4, 4, 0, 0]}>
                    {analytics.denial_rate_by_payer.map((entry, i) => (
                      <Cell key={i} fill={denialColor(entry.denial_rate_pct)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-gray-400 text-sm">Loading…</div>
            )}
          </div>

          {/* Denial rate by CPT code */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Denial Rate by CPT Code</h2>
            {analytics?.denial_rate_by_cpt.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={analytics.denial_rate_by_cpt} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <XAxis dataKey="cpt_code" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v}%`} domain={[0, 'auto']} />
                  <Tooltip formatter={(v: number | string) => [`${Number(v).toFixed(1)}%`, 'Denial rate']} />
                  <Bar dataKey="denial_rate_pct" radius={[4, 4, 0, 0]}>
                    {analytics.denial_rate_by_cpt.map((entry, i) => (
                      <Cell key={i} fill={denialColor(entry.denial_rate_pct)} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-gray-400 text-sm">Loading…</div>
            )}
          </div>

          {/* Avg days to adjudication */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Avg Days to Adjudication by Payer</h2>
            {analytics?.avg_days_to_adjudication_by_payer.length ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={analytics.avg_days_to_adjudication_by_payer} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                  <XAxis dataKey="payer" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v}d`} domain={[0, 'auto']} />
                  <Tooltip formatter={(v: number | string) => [`${Number(v).toFixed(1)} days`, 'Avg days']} />
                  <Bar dataKey="avg_days" fill="#6366f1" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-gray-400 text-sm">Loading…</div>
            )}
          </div>

          {/* Claims by status */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Claims by Status</h2>
            {analytics ? (
              <div className="space-y-2">
                {Object.entries(analytics.claims_by_status)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => (
                    <div key={status} className="flex items-center gap-3">
                      <span className="text-xs w-36 text-gray-600 font-mono">{status}</span>
                      <div className="flex-1 bg-gray-100 rounded-full h-2">
                        <div
                          className="bg-indigo-400 h-2 rounded-full"
                          style={{ width: `${totalClaims ? (count / totalClaims) * 100 : 0}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-500 w-8 text-right">{count}</span>
                    </div>
                  ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">Loading…</div>
            )}
          </div>

          {/* Throughput 24h */}
          <div className="bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-4">Throughput — Last 24h</h2>
            {analytics ? (
              <div className="grid grid-cols-2 gap-4">
                {[
                  { label: 'Created', value: analytics.throughput_last_24h.created, color: 'text-gray-700' },
                  { label: 'Submitted', value: analytics.throughput_last_24h.submitted, color: 'text-yellow-700' },
                  { label: 'Paid', value: analytics.throughput_last_24h.paid, color: 'text-green-700' },
                  { label: 'Denied', value: analytics.throughput_last_24h.denied, color: 'text-red-700' },
                ].map(({ label, value, color }) => (
                  <div key={label} className="bg-gray-50 rounded-lg p-4 text-center">
                    <p className={`text-2xl font-bold ${color}`}>{value}</p>
                    <p className="text-xs text-gray-400 mt-1">{label}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-gray-400 text-sm">Loading…</div>
            )}
          </div>
        </div>

        {/* Last updated ticker */}
        {lastUpdated && (
          <p className="text-right text-xs text-gray-300 mt-6" suppressHydrationWarning>
            Updated {secondsAgo(lastUpdated)}
          </p>
        )}
      </div>
    </div>
  )
}
