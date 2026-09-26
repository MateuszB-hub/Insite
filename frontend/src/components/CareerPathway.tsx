import { useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { FormEvent } from 'react'
import {
  Route,
  Loader2,
  Building2,
  TrendingUp,
  Info,
  ExternalLink,
  ArrowRight,
  Cpu,
  TriangleAlert,
} from 'lucide-react'
import {
  fetchCareerPathway,
  fetchPathwayNarrative,
  type CareerPathwayResult,
  type DataSourceInfo,
  type OccupationInfo,
} from '../lib/api'
import { useAuth } from '../auth/AuthContext'
import { markPathwayExplored } from '../lib/progress'
import { loadRecent, saveRecent } from '../lib/recent'
import MoveFacts from './MoveFacts'
import ReadinessBadge from './ReadinessBadge'
import SourceAttribution from './SourceAttribution'
import TransferableRoles from './TransferableRoles'

interface RecentPathway {
  role: string
  industry: string
  horizon: number
}

const recentKey = (r: RecentPathway) => `${r.role.toLowerCase()}|${r.industry.toLowerCase()}|${r.horizon}`

const HORIZONS = [
  { months: 6, label: '6 months' },
  { months: 12, label: '1 year' },
  { months: 24, label: '2 years' },
  { months: 60, label: '5 years' },
]

const money = (n?: number | null) =>
  n == null ? null : `$${Math.round(n).toLocaleString()}`

/**
 * "Doing this work, after N months, what opens up — and who's hiring, at what
 * pay?" Answers come from the labour-market sources, not from a model, so any
 * section backed by a fallback is labelled rather than quietly presented.
 */
export default function CareerPathway() {
  //: Home links here with ?role= (and ?industry=) from the profile. It fills
  //: the form but does not run it: the person picks the horizon first.
  const [params] = useSearchParams()
  const [role, setRole] = useState(() => params.get('role') ?? '')
  const [industry, setIndustry] = useState(() => params.get('industry') ?? '')
  const [horizon, setHorizon] = useState(12)
  const { user } = useAuth()
  const [recent, setRecent] = useState<RecentPathway[]>(() => loadRecent<RecentPathway>('pathway', user?.id))
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CareerPathwayResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  //: The facts arrive in a few seconds. The model's summary is optional and
  //: slow, so it is asked for, not waited on (testers found it generic).
  const [narrating, setNarrating] = useState(false)
  const [narrativeError, setNarrativeError] = useState<string | null>(null)
  //: A response that lands after a newer search started must not replace it.
  const requestId = useRef(0)
  const lastParams = useRef<{ currentRole: string; industry: string; horizonMonths: number } | null>(null)

  const submit = async (e?: FormEvent, from?: RecentPathway) => {
    e?.preventDefault()
    const wanted = from ?? { role: role.trim(), industry: industry.trim(), horizon }
    if (!wanted.role || loading) return
    if (from) {
      setRole(from.role)
      setIndustry(from.industry)
      setHorizon(from.horizon)
    }
    const id = ++requestId.current
    const params = {
      currentRole: wanted.role,
      industry: wanted.industry,
      horizonMonths: wanted.horizon,
    }
    lastParams.current = params
    setLoading(true)
    setError(null)
    setResult(null)
    setNarrating(false)
    setNarrativeError(null)
    try {
      const facts = await fetchCareerPathway({ ...params, includeNarrative: false })
      if (id !== requestId.current) return
      setResult(facts)
      markPathwayExplored()
      setRecent(saveRecent('pathway', user?.id, wanted, recentKey))
    } catch (err) {
      if (id === requestId.current) {
        setError(err instanceof Error ? err.message : 'Unexpected error')
      }
    } finally {
      if (id === requestId.current) setLoading(false)
    }
  }

  const requestSummary = async () => {
    const params = lastParams.current
    if (!params || narrating) return
    const id = requestId.current
    setNarrating(true)
    setNarrativeError(null)
    try {
      const narrated = await fetchPathwayNarrative(params)
      if (id !== requestId.current) return
      if (narrated.narrative) setResult(narrated)
      else setNarrativeError(narrated.narrative_status)
    } catch (err) {
      if (id === requestId.current) {
        setNarrativeError(err instanceof Error ? err.message : 'Unexpected error')
      }
    } finally {
      if (id === requestId.current) setNarrating(false)
    }
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Career Pathway</h1>
        <p className="text-slate-500 mt-1">
          Where this role leads, who has been hiring, and what it pays.
        </p>
      </header>

      <form
        onSubmit={submit}
        className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8"
      >
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <label htmlFor="role" className="block text-sm font-medium text-slate-700 mb-1">
              Your current role
            </label>
            <input
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="e.g. Senior Backend Software Engineer"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
            />
          </div>
          <div className="flex-1">
            <label htmlFor="ind" className="block text-sm font-medium text-slate-700 mb-1">
              Industry <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <input
              id="ind"
              value={industry}
              onChange={(e) => setIndustry(e.target.value)}
              placeholder="e.g. Fintech"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
            />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <span className="block text-sm font-medium text-slate-700">How soon do you want to move?</span>
            <span className="block text-xs text-slate-500 mb-2">
              Shows roles you could realistically reach in that time, from the training
              and experience they usually need.
            </span>
            <div className="flex flex-wrap gap-2">
              {HORIZONS.map((h) => (
                <button
                  key={h.months}
                  type="button"
                  onClick={() => setHorizon(h.months)}
                  className={`px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                    horizon === h.months
                      ? 'bg-indigo-600 border-indigo-600 text-white'
                      : 'bg-white border-slate-300 text-slate-700 hover:border-indigo-400'
                  }`}
                >
                  {h.label}
                </button>
              ))}
            </div>
          </div>
          <button
            type="submit"
            disabled={loading || !role.trim()}
            className="flex items-center gap-2 bg-indigo-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Route className="w-4 h-4" />}
            {loading ? 'Mapping…' : 'Map pathway'}
          </button>
        </div>
      </form>

      {!result && !loading && recent.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-6 text-sm" aria-label="Recent pathways">
          <span className="text-slate-500">Recent:</span>
          {recent.map((r) => (
            <button key={recentKey(r)} type="button" onClick={() => submit(undefined, r)}
              className="px-3 py-1 rounded-full border border-slate-300 bg-white text-slate-700 hover:border-indigo-400">
              {r.role}{r.industry ? ` · ${r.industry}` : ''} · {HORIZONS.find((h) => h.months === r.horizon)?.label ?? `${r.horizon} months`}
            </button>
          ))}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 mb-6">
          <p className="font-medium">Something went wrong</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <SourceBanner sources={result.data_sources} />

          <AtAGlance result={result} />

          {/* Starting point */}
          <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
            <p className="text-xs uppercase tracking-wide text-slate-400 mb-1">Starting from</p>
            <h2 className="text-lg font-semibold text-slate-900">
              {result.current_occupation.title}
              {result.current_occupation.code && (
                <span className="ml-2 text-xs font-mono text-slate-400">
                  SOC {result.current_occupation.code}
                </span>
              )}
            </h2>
            {result.current_occupation.wage && (
              <WageLine wage={result.current_occupation.wage} />
            )}
          </section>

          {/* Destinations */}
          <section>
            <h2 className="text-lg font-semibold text-slate-900 mb-3">
              Roles you could move into within {HORIZONS.find((h) => h.months === result.horizon_months)?.label ?? `${result.horizon_months} months`}
            </h2>
            {result.pathways.length === 0 ? (
              <p className="text-slate-500 text-sm bg-white border border-slate-200 rounded-xl p-6">
                No adjacent roles mapped for this title yet.
              </p>
            ) : (
              <div className="grid gap-3">
                {result.pathways.map((p) => (
                  <article
                    key={p.code || p.title}
                    className="bg-white border border-slate-200 rounded-lg p-4 flex items-start gap-3 hover:border-indigo-200 transition-colors"
                  >
                    <ArrowRight className="w-4 h-4 text-indigo-500 mt-1 shrink-0" />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="font-medium text-slate-900">
                          {p.title}
                          {p.code && (
                            <span className="ml-2 text-xs font-mono text-slate-400">{p.code}</span>
                          )}
                        </h3>
                        <ReadinessBadge readiness={p.readiness} />
                      </div>
                      {p.description && (
                        <p className="text-sm text-slate-600 mt-1">{p.description}</p>
                      )}
                      {p.wage ? (
                        <WageLine wage={p.wage} change={p.pay_change} />
                      ) : (
                        <p className="text-xs text-slate-400 mt-2">Wage data not configured</p>
                      )}
                      <MoveFacts training={p.training} gaps={p.skill_gaps} links={p.links} />
                    </div>
                  </article>
                ))}
              </div>
            )}
          </section>

          <TransferableRoles
            roles={result.transferable}
            currentPay={result.current_occupation.wage?.annual_median}
          />

          <SummaryPanel
            result={result}
            narrating={narrating}
            error={narrativeError}
            onRequest={requestSummary}
          />

          {/* Hiring market */}
          {result.hiring && <HiringSection hiring={result.hiring} />}

          {/* Licence condition: credit whichever sources actually fed this. */}
          <SourceAttribution sources={result.data_sources} />
        </div>
      )}
    </div>
  )
}

function WageLine({ wage, change }: {
  wage: NonNullable<OccupationInfo['wage']>
  change?: number | null
}) {
  const median = money(wage.annual_median)
  const mean = money(wage.annual_mean)
  if (!median && !mean) return null
  return (
    <p className="text-sm text-slate-700 mt-2">
      {median && <span className="font-semibold">{median} median</span>}
      {change != null && <PayChange change={change} />}
      {median && mean && <span className="text-slate-400"> · </span>}
      {mean && <span>{mean} mean</span>}
      {wage.year && <span className="text-slate-400"> · {wage.year}</span>}
      {wage.source && <span className="text-slate-400"> · {wage.source}</span>}
    </p>
  )
}

/** Sign outside the currency symbol: -$17,200, not $-17,200. */
const signedMoney = (n: number) =>
  `${n < 0 ? '-' : '+'}$${Math.abs(Math.round(n)).toLocaleString()}`

function PayChange({ change }: { change: number }) {
  return (
    <span data-testid="pay-change"
      className={`ml-2 text-xs font-medium ${change > 0 ? 'text-emerald-700' : 'text-slate-500'}`}>
      {signedMoney(change)} vs now
    </span>
  )
}

const READINESS_WORD = { ready: 'within reach now', stretch: 'a stretch', 'long-term': 'longer term' } as const

/**
 * The headline, computed from the facts below it -- never model-written, so
 * it cannot disagree with them.
 */
function AtAGlance({ result }: { result: CareerPathwayResult }) {
  const roles = result.pathways
  if (roles.length === 0) return null
  const count = (r: keyof typeof READINESS_WORD) => roles.filter((p) => p.readiness === r).length
  const parts = (Object.keys(READINESS_WORD) as (keyof typeof READINESS_WORD)[])
    .filter((r) => count(r) > 0)
    .map((r) => `${count(r)} ${READINESS_WORD[r]}`)
  const byPay = roles
    .filter((p) => p.pay_change != null && p.pay_change > 0)
    .sort((a, b) => (b.pay_change ?? 0) - (a.pay_change ?? 0))
  const top = byPay[0]
  const readyBest = byPay.find((p) => p.readiness === 'ready')
  // The skills panel can hold the better pay step, so the headline looks there too.
  const currentPay = result.current_occupation.wage?.annual_median
  const sideways = result.transferable
    .map((t) => ({ t, change: currentPay != null && t.wage?.annual_median != null ? t.wage.annual_median - currentPay : null }))
    .filter((x): x is { t: typeof x.t; change: number } => x.change != null && x.change > 0)
    .sort((a, b) => b.change - a.change)[0]

  return (
    <section aria-labelledby="at-a-glance"
      className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-100 p-6">
      <h2 id="at-a-glance" className="text-lg font-semibold text-indigo-900 mb-2">At a glance</h2>
      <ul className="space-y-1.5 text-slate-700">
        {parts.length > 0 && (
          <li>
            Of {roles.length} next {roles.length === 1 ? 'role' : 'roles'}: {parts.join(', ')}.
          </li>
        )}
        {top ? (
          <li>
            Biggest pay step: <span className="font-medium">{top.title}</span>,{' '}
            <span className="text-emerald-700 font-medium">{signedMoney(top.pay_change!)}</span> a year at
            the national median
            {top.readiness ? ` (${READINESS_WORD[top.readiness]}` : ''}
            {top.readiness && top.training ? `; ${top.training.charAt(0).toLowerCase()}${top.training.slice(1)})` : top.readiness ? ')' : ''}.
          </li>
        ) : (
          roles.some((p) => p.pay_change != null) && (
            <li>None of these pays more than your current role at the national median.</li>
          )
        )}
        {readyBest && readyBest !== top && (
          <li>
            Best-paid move within reach now: <span className="font-medium">{readyBest.title}</span>,{' '}
            <span className="text-emerald-700 font-medium">{signedMoney(readyBest.pay_change!)}</span>.
          </li>
        )}
        {sideways && (!top || sideways.change > top.pay_change!) && (
          <li>
            Where your skills also apply, the best pay step is{' '}
            <span className="font-medium">{sideways.t.title}</span>,{' '}
            <span className="text-emerald-700 font-medium">{signedMoney(sideways.change)}</span>
            {sideways.t.readiness ? ` (${READINESS_WORD[sideways.t.readiness]})` : ''}.
          </li>
        )}
      </ul>
      <p className="text-xs text-slate-500 mt-3">
        From O*NET and BLS data. Each role below links to what it involves and where to train.
      </p>
    </section>
  )
}

/** The model's take, only when asked for -- labelled, and after the facts. */
function SummaryPanel({ result, narrating, error, onRequest }: {
  result: CareerPathwayResult
  narrating: boolean
  error: string | null
  onRequest: () => void
}) {
  const n = result.narrative
  if (n) {
    return (
      <section className="bg-white rounded-xl border border-slate-200 p-6">
        <div className="flex items-start justify-between gap-4 mb-2">
          <h2 className="text-lg font-semibold text-slate-900">AI summary</h2>
          <span className="shrink-0 inline-flex items-center gap-1 text-xs text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-1 rounded-full">
            <Cpu className="w-3 h-3" />
            {n.provider_label}
          </span>
        </div>
        <p className="text-slate-700 leading-relaxed">{n.summary}</p>
        {n.risks.length > 0 && (
          <div className="mt-4">
            <h3 className="text-sm font-medium text-slate-900 mb-1.5 flex items-center gap-1.5">
              <TriangleAlert className="w-4 h-4" /> Worth weighing
            </h3>
            <ul className="list-disc list-inside space-y-1">
              {n.risks.map((r) => (
                <li key={r} className="text-sm text-slate-700">{r}</li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-xs text-slate-400 mt-3">Written by a model from the facts above; the facts win where they differ.</p>
      </section>
    )
  }
  return (
    <section className="bg-white rounded-xl border border-dashed border-slate-300 p-5 flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-slate-600">
        {narrating
          ? 'Writing a summary from the facts above. This takes about half a minute.'
          : error
            ? `Summary unavailable (${error}). The facts above are unaffected.`
            : 'Want it in words? An AI model can summarise these facts. It takes about half a minute.'}
      </p>
      <button type="button" onClick={onRequest} disabled={narrating}
        className="inline-flex items-center gap-2 text-sm font-medium px-4 py-2 rounded-lg border border-indigo-200 text-indigo-700 bg-indigo-50 hover:bg-indigo-100 disabled:opacity-60">
        {narrating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Cpu className="w-4 h-4" />}
        {narrating ? 'Writing…' : error ? 'Try again' : 'Write me a summary'}
      </button>
    </section>
  )
}

/** Makes the real/scaffolded distinction impossible to miss. */
function SourceBanner({ sources }: { sources: DataSourceInfo[] }) {
  const missing = sources.filter((s) => !s.live)
  if (missing.length === 0) return null
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
      <p className="text-sm font-medium text-amber-900 flex items-center gap-1.5">
        <Info className="w-4 h-4" />
        Partial data — {missing.length} of {sources.length} sources not yet connected
      </p>
      <ul className="mt-2 space-y-1">
        {missing.map((s) => (
          <li key={s.capability} className="text-xs text-amber-800 flex items-center gap-1.5">
            <span className="font-medium capitalize">{s.capability}:</span>
            <span>{s.reason}</span>
            {s.signup_url && (
              <a
                href={s.signup_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 underline hover:text-amber-950"
              >
                register <ExternalLink className="w-3 h-3" />
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}

function HiringSection({ hiring }: { hiring: NonNullable<CareerPathwayResult['hiring']> }) {
  const hasData =
    hiring.top_employers.length > 0 ||
    hiring.salary_distribution.length > 0 ||
    Object.keys(hiring.salary_history).length > 0

  if (!hasData) {
    return (
      <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
        <h2 className="text-lg font-semibold text-slate-900 mb-1">Who has been hiring</h2>
        <p className="text-sm text-slate-500">
          Connect a job-market source to see hiring employers and pay ranges.
        </p>
      </section>
    )
  }

  const maxCount = Math.max(...hiring.salary_distribution.map((b) => b.count), 1)
  const history = Object.entries(hiring.salary_history).sort(([a], [b]) => a.localeCompare(b))

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900">Who has been hiring</h2>
        {hiring.total_postings != null && (
          <p className="text-sm text-slate-500">
            {hiring.total_postings.toLocaleString()} postings for “{hiring.query}”
          </p>
        )}
      </div>

      {hiring.top_employers.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-1.5">
            <Building2 className="w-4 h-4 text-slate-400" /> Top employers
          </h3>
          <ul className="divide-y divide-slate-100">
            {hiring.top_employers.map((e) => (
              <li key={e.name} className="flex items-center justify-between py-2 text-sm">
                <span className="text-slate-800">{e.name}</span>
                <span className="text-slate-500">
                  {e.postings.toLocaleString()} postings
                  {e.average_salary != null && (
                    <span className="text-slate-400"> · {money(e.average_salary)} avg</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {hiring.salary_distribution.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-700 mb-2">Advertised salary spread</h3>
          <div className="space-y-1.5">
            {hiring.salary_distribution.map((b) => (
              <div key={b.lower} className="flex items-center gap-3 text-xs">
                <span className="w-32 shrink-0 text-slate-500 tabular-nums">
                  {money(b.lower)}
                  {b.upper ? `–${money(b.upper)}` : '+'}
                </span>
                <div className="flex-1 bg-slate-100 rounded-full h-2.5 overflow-hidden">
                  <div
                    className="bg-indigo-500 h-full rounded-full"
                    style={{ width: `${(b.count / maxCount) * 100}%` }}
                  />
                </div>
                <span className="w-12 text-right text-slate-500 tabular-nums">{b.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <h3 className="text-sm font-medium text-slate-700 mb-2 flex items-center gap-1.5">
            <TrendingUp className="w-4 h-4 text-slate-400" /> Average advertised pay over time
          </h3>
          <ul className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
            {history.map(([month, value]) => (
              <li key={month} className="text-slate-700">
                <span className="text-slate-400">{month}</span>{' '}
                <span className="font-medium tabular-nums">{money(value)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
