import { useState } from 'react'
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
  Target,
  TriangleAlert,
} from 'lucide-react'
import {
  fetchCareerPathway,
  type CareerPathwayResult,
  type DataSourceInfo,
  type OccupationInfo,
  type Readiness,
} from '../lib/api'
import SourceAttribution from './SourceAttribution'
import TransferableRoles from './TransferableRoles'

const HORIZONS = [
  { months: 6, label: '6 months' },
  { months: 12, label: '1 year' },
  { months: 24, label: '2 years' },
  { months: 60, label: '5 years' },
]

const READINESS_STYLE: Record<Readiness, { label: string; cls: string }> = {
  ready: { label: 'Ready now', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  stretch: { label: 'Stretch', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  'long-term': { label: 'Longer term', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
}

const money = (n?: number | null) =>
  n == null ? null : `$${Math.round(n).toLocaleString()}`

/**
 * "Doing this work, after N months, what opens up — and who's hiring, at what
 * pay?" Answers come from the labour-market sources, not from a model, so any
 * section backed by a fallback is labelled rather than quietly presented.
 */
export default function CareerPathway() {
  const [role, setRole] = useState('')
  const [industry, setIndustry] = useState('')
  const [horizon, setHorizon] = useState(12)
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CareerPathwayResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!role.trim() || loading) return
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      setResult(
        await fetchCareerPathway({
          currentRole: role.trim(),
          industry: industry.trim(),
          horizonMonths: horizon,
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unexpected error')
    } finally {
      setLoading(false)
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
            <span className="block text-sm font-medium text-slate-700 mb-2">Looking ahead</span>
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

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700 mb-6">
          <p className="font-medium">Something went wrong</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <SourceBanner sources={result.data_sources} />

          {result.narrative ? (
            <section className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-100 p-6">
              <div className="flex items-start justify-between gap-4 mb-2">
                <h2 className="text-lg font-semibold text-indigo-900">What this means for you</h2>
                <span className="shrink-0 inline-flex items-center gap-1 text-xs text-indigo-700 bg-white/70 border border-indigo-200 px-2 py-1 rounded-full">
                  <Cpu className="w-3 h-3" />
                  {result.narrative.provider_label}
                </span>
              </div>
              <p className="text-slate-700 leading-relaxed">{result.narrative.summary}</p>

              {result.narrative.skill_gaps.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-medium text-indigo-900 mb-2 flex items-center gap-1.5">
                    <Target className="w-4 h-4" /> Skills to build
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {result.narrative.skill_gaps.map((s) => (
                      <span key={s} className="bg-white/80 border border-indigo-200 text-indigo-800 px-3 py-1 rounded-full text-sm">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {result.narrative.risks.length > 0 && (
                <div className="mt-4">
                  <h3 className="text-sm font-medium text-indigo-900 mb-1.5 flex items-center gap-1.5">
                    <TriangleAlert className="w-4 h-4" /> Worth weighing
                  </h3>
                  <ul className="list-disc list-inside space-y-1">
                    {result.narrative.risks.map((r) => (
                      <li key={r} className="text-sm text-slate-700">{r}</li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          ) : (
            <p className="text-sm text-slate-500 bg-white border border-slate-200 rounded-xl p-4">
              Guidance unavailable ({result.narrative_status}). The data below is unaffected.
            </p>
          )}

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
              Roles open to you after {HORIZONS.find((h) => h.months === result.horizon_months)?.label ?? `${result.horizon_months} months`}
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
                      {p.rationale && (
                        <p className="text-sm text-slate-600 mt-1.5">{p.rationale}</p>
                      )}
                      {!p.rationale && p.description && (
                        <p className="text-sm text-slate-600 mt-1">{p.description}</p>
                      )}
                      {p.steps.length > 0 && (
                        <ul className="mt-2 space-y-1">
                          {p.steps.map((s) => (
                            <li key={s} className="text-sm text-slate-600 flex gap-2">
                              <span className="text-indigo-400 mt-0.5">·</span>
                              <span>{s}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                      {p.wage ? (
                        <WageLine wage={p.wage} />
                      ) : (
                        <p className="text-xs text-slate-400 mt-2">Wage data not configured</p>
                      )}
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

          {/* Hiring market */}
          {result.hiring && <HiringSection hiring={result.hiring} />}

          {/* Licence condition: credit whichever sources actually fed this. */}
          <SourceAttribution sources={result.data_sources} />
        </div>
      )}
    </div>
  )
}

function ReadinessBadge({ readiness }: { readiness?: Readiness | null }) {
  if (!readiness) return null
  const style = READINESS_STYLE[readiness]
  if (!style) return null
  return (
    <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full border font-medium ${style.cls}`}>
      {style.label}
    </span>
  )
}

function WageLine({ wage }: { wage: NonNullable<OccupationInfo['wage']> }) {
  const median = money(wage.annual_median)
  const mean = money(wage.annual_mean)
  if (!median && !mean) return null
  return (
    <p className="text-sm text-slate-700 mt-2">
      {median && <span className="font-semibold">{median} median</span>}
      {median && mean && <span className="text-slate-400"> · </span>}
      {mean && <span>{mean} mean</span>}
      {wage.year && <span className="text-slate-400"> · {wage.year}</span>}
      {wage.source && <span className="text-slate-400"> · {wage.source}</span>}
    </p>
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
