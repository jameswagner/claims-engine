import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, Cell, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fetchAnalytics, fetchDenialRateTimeseries, resetFastForward, stepFastForward } from '../api/analytics'
import { NavBar } from '../components/NavBar'
import type { ClaimsAnalytics, DenialRateDailyPoint } from '../types/claim'

function MetricCard({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  )
}

const PAYER_COLORS: Record<string, string> = {
  Aetna: '#dc2626',
  BCBS: '#6366f1',
  Cigna: '#0ea5e9',
  UnitedHealthcare: '#10b981',
  Humana: '#f59e0b',
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

function isoDate(d: Date): string {
  return d.toISOString().slice(0, 10)
}

function addDays(d: Date, n: number): Date {
  const r = new Date(d)
  r.setDate(r.getDate() + n)
  return r
}

function buildTimeseriesChartData(points: DenialRateDailyPoint[], cutoff: Date) {
  // Show 8-day window ending at cutoff
  const windowStart = isoDate(addDays(cutoff, -7))
  const windowEnd = isoDate(cutoff)

  const visible = points.filter(p => p.date >= windowStart && p.date <= windowEnd)
  const days = [...new Set(visible.map(p => p.date))].sort()
  const payers = [...new Set(visible.map(p => p.payer))].sort()

  const chartData = days.map(date => {
    const row: Record<string, string | number | null> = { date: date.slice(5).replace('-', '/') }
    for (const payer of payers) {
      const pt = visible.find(p => p.date === date && p.payer === payer)
      row[payer] = pt?.denial_rate_pct ?? null
    }
    return row
  })

  return { chartData, payers }
}

export function Dashboard() {
  const [analytics, setAnalytics] = useState<ClaimsAnalytics | null>(null)
  const [timeseries, setTimeseries] = useState<DenialRateDailyPoint[] | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [, setTick] = useState(0)

  // Demo clock: starts 3 days in the past, advances one day per FF click
  const [demoCutoff, setDemoCutoff] = useState<Date>(() => addDays(new Date(), -3))
  const [ffDayIndex, setFfDayIndex] = useState(0)
  const [ffStepping, setFfStepping] = useState(false)
  const [ffError, setFfError] = useState<string | null>(null)
  const ffSteppingRef = useRef(false)

  useEffect(() => {
    const load = () => {
      if (ffSteppingRef.current) return Promise.resolve()
      return Promise.all([
        fetchAnalytics().then(a => { setAnalytics(a); setLastUpdated(new Date()) }),
        fetchDenialRateTimeseries().then(setTimeseries),
      ]).catch(() => {})
    }
    // Sync FF cursor from backend so page refresh shows correct button state
    import('../api/analytics').then(({ fetchFastForwardStatus }) =>
      fetchFastForwardStatus().then(s => {
        setFfDayIndex(s.day)
        setDemoCutoff(addDays(new Date(), -(3 - s.day)))
      }).catch(() => {})
    )
    load()
    const id = setInterval(load, 20_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 5_000)
    return () => clearInterval(id)
  }, [])

  async function handleStepFastForward() {
    ffSteppingRef.current = true
    setFfStepping(true)
    setFfError(null)
    try {
      const result = await stepFastForward()
      setFfDayIndex(result.day_index)
      // Advance the demo clock by one day
      setDemoCutoff(prev => addDays(prev, 1))
      // Refresh chart data immediately
      await Promise.all([
        fetchAnalytics().then(a => { setAnalytics(a); setLastUpdated(new Date()) }),
        fetchDenialRateTimeseries().then(setTimeseries),
      ])
    } catch (e: unknown) {
      setFfError(e instanceof Error ? e.message : 'Failed')
    } finally {
      ffSteppingRef.current = false
      setFfStepping(false)
    }
  }

  async function handleReset() {
    try {
      await resetFastForward()
      setFfDayIndex(0)
      setDemoCutoff(addDays(new Date(), -3))
      setFfError(null)
      await Promise.all([
        fetchAnalytics().then(a => { setAnalytics(a); setLastUpdated(new Date()) }),
        fetchDenialRateTimeseries().then(setTimeseries),
      ])
    } catch {
      // ignore
    }
  }

  const ffComplete = ffDayIndex >= 3
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

  const { chartData, payers } = timeseries
    ? buildTimeseriesChartData(timeseries, demoCutoff)
    : { chartData: [], payers: [] }

  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />

      <div className="max-w-6xl mx-auto px-6 py-8">

        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Claims Dashboard</h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Showing data through <span className="font-medium text-gray-600">{isoDate(demoCutoff)}</span>
            </p>
          </div>
          <div className="flex items-center gap-3">
            {ffError && <span className="text-xs text-red-600">{ffError}</span>}
            {ffComplete ? (
              <button
                onClick={handleReset}
                className="px-4 py-2 bg-gray-100 text-gray-700 text-sm font-medium rounded-lg hover:bg-gray-200 transition-colors"
              >
                ↺ Reset demo
              </button>
            ) : (
              <button
                onClick={handleStepFastForward}
                disabled={ffStepping}
                className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-lg hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {ffStepping
                  ? `Writing day ${ffDayIndex + 1}…`
                  : ffDayIndex === 0
                    ? '⏩ Advance one day'
                    : `⏩ Advance to ${isoDate(addDays(demoCutoff, 1))} (${ffDayIndex + 1}/3)`}
              </button>
            )}
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
            sub="resolved (paid or denied)"
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

          {/* Denial rate trend — full width */}
          <div className="lg:col-span-2 bg-white rounded-xl border border-gray-200 p-6">
            <h2 className="text-sm font-semibold text-gray-700 mb-0.5">Denial Rate by Payer — 8-Day Trend</h2>
            <p className="text-xs text-gray-400 mb-4">% of adjudicated claims denied per day · through {isoDate(demoCutoff)}</p>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={chartData} margin={{ top: 4, right: 16, left: -16, bottom: 0 }}>
                  <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} tickFormatter={v => `${v}%`} domain={[0, 'auto']} />
                  <Tooltip formatter={(v) => [`${Number(v ?? 0).toFixed(1)}%`, '']} />
                  <ReferenceLine y={20} stroke="#f97316" strokeDasharray="4 3" label={{ value: 'Alert threshold (20%)', position: 'insideTopRight', fontSize: 11, fill: '#f97316' }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {payers.map(payer => (
                    <Line
                      key={payer}
                      type="monotone"
                      dataKey={payer}
                      stroke={PAYER_COLORS[payer] ?? '#9ca3af'}
                      strokeWidth={payer === 'Aetna' ? 2.5 : 1.5}
                      dot={{ r: 3 }}
                      connectNulls
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[240px] flex items-center justify-center text-gray-400 text-sm">
                {timeseries === null ? 'Loading…' : 'No data in window'}
              </div>
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
                  <Tooltip formatter={(v) => [`${Number(v ?? 0).toFixed(1)}%`, 'Denial rate']} />
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
                  <Tooltip formatter={(v) => [`${Number(v ?? 0).toFixed(1)} days`, 'Avg days']} />
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
