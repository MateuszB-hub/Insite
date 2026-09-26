import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import {
  Search,
  TrendingUp,
  Briefcase,
  Zap,
  BookOpen,
  Loader2,
  ExternalLink,
  Cpu,
} from 'lucide-react'
import {
  fetchFutureOfWork,
  fetchProviders,
  type FutureOfWorkResult,
  type ProviderInfo,
} from '../lib/api'
import ProviderPicker from './ProviderPicker'

type TabKey = 'trends' | 'skills' | 'outlook'

const TABS: { key: TabKey; label: string; icon: ReactNode }[] = [
  { key: 'trends', label: 'Trends', icon: <TrendingUp className="w-4 h-4" /> },
  { key: 'skills', label: 'Skills in Demand', icon: <Zap className="w-4 h-4" /> },
  { key: 'outlook', label: 'Career Outlook', icon: <BookOpen className="w-4 h-4" /> },
]

export default function Dashboard() {
  const [industry, setIndustry] = useState('')
  const [jobTitle, setJobTitle] = useState('')
  const [provider, setProvider] = useState<string | undefined>(undefined)
  const [providers, setProviders] = useState<ProviderInfo[]>([])
  const [paidEnabled, setPaidEnabled] = useState(false)

  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<FutureOfWorkResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TabKey>('trends')

  const abortRef = useRef<AbortController | null>(null)

  // Load the engine inventory once so the picker reflects what is really up.
  useEffect(() => {
    let cancelled = false
    fetchProviders()
      .then((data) => {
        if (cancelled) return
        setProviders(data.providers)
        setPaidEnabled(data.paid_enabled)
      })
      .catch(() => {
        // Non-fatal: the picker just stays hidden and the server uses auto.
      })
    return () => {
      cancelled = true
    }
  }, [])

  // Abandon an in-flight request if the component goes away.
  useEffect(() => () => abortRef.current?.abort(), [])

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!industry.trim() || loading) return

    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)
    setResult(null)

    try {
      const data = await fetchFutureOfWork({
        industry: industry.trim(),
        jobTitle: jobTitle.trim(),
        provider,
        signal: controller.signal,
      })
      setResult(data)
      setActiveTab('trends')
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return
      setError(err instanceof Error ? err.message : 'An unexpected error occurred')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <header className="mb-8">
        <h1 className="text-3xl font-bold text-slate-900">Future of Work</h1>
        <p className="text-slate-500 mt-1">
          Discover emerging trends, in-demand skills, and career outlook for any industry.
        </p>
      </header>

      <form
        onSubmit={handleSubmit}
        className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8"
      >
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <label htmlFor="industry" className="block text-sm font-medium text-slate-700 mb-1">
              Industry
            </label>
            <div className="relative">
              <Briefcase className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
              <input
                id="industry"
                type="text"
                value={industry}
                onChange={(e) => setIndustry(e.target.value)}
                placeholder="e.g. Fintech, Healthcare, Renewable Energy"
                className="w-full pl-10 pr-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
              />
            </div>
          </div>

          <div className="flex-1">
            <label htmlFor="jobTitle" className="block text-sm font-medium text-slate-700 mb-1">
              Job Title <span className="text-slate-400 font-normal">(optional)</span>
            </label>
            <input
              id="jobTitle"
              type="text"
              value={jobTitle}
              onChange={(e) => setJobTitle(e.target.value)}
              placeholder="e.g. Grid Engineer"
              className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
            />
          </div>

          <div className="flex items-end">
            <button
              type="submit"
              disabled={loading || !industry.trim()}
              className="flex items-center gap-2 bg-indigo-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Search className="w-4 h-4" />
              )}
              {loading ? 'Analyzing…' : 'Discover'}
            </button>
          </div>
        </div>

        {providers.length > 0 && (
          <div className="mt-5 pt-5 border-t border-slate-100">
            <ProviderPicker
              providers={providers}
              paidEnabled={paidEnabled}
              selected={provider}
              onSelect={setProvider}
              disabled={loading}
            />
          </div>
        )}
      </form>

      {loading && <LoadingSkeleton />}

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-red-700">
          <p className="font-medium">Something went wrong</p>
          <p className="text-sm mt-1">{error}</p>
        </div>
      )}

      {result && (
        <div className="space-y-6">
          <section className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-100 p-6">
            <div className="flex items-start justify-between gap-4 mb-2">
              <h2 className="text-lg font-semibold text-indigo-900">Executive Summary</h2>
              {/* Attribution: never leave the applicant guessing what wrote this. */}
              <span className="shrink-0 inline-flex items-center gap-1 text-xs text-indigo-700 bg-white/70 border border-indigo-200 px-2 py-1 rounded-full">
                <Cpu className="w-3 h-3" />
                {result.provider_label}
              </span>
            </div>
            <p className="text-slate-700 leading-relaxed">{result.executive_summary}</p>
          </section>

          <section className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
            <div className="flex border-b border-slate-200">
              {TABS.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-2 px-6 py-3 text-sm font-medium transition-colors border-b-2 ${
                    activeTab === tab.key
                      ? 'border-indigo-600 text-indigo-600'
                      : 'border-transparent text-slate-500 hover:text-slate-700'
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </div>

            <div className="p-6">
              {activeTab === 'trends' && (
                <div className="grid gap-4">
                  {result.trends.map((trend, idx) => (
                    <article
                      key={idx}
                      className="border border-slate-200 rounded-lg p-4 hover:border-indigo-200 transition-colors"
                    >
                      <h3 className="font-semibold text-slate-900 mb-2">{trend.title}</h3>
                      <p className="text-sm text-slate-600 leading-relaxed">{trend.summary}</p>
                      {trend.source && (
                        <div className="mt-3 flex items-center gap-1 text-xs text-indigo-600">
                          <ExternalLink className="w-3 h-3" />
                          {trend.source_url ? (
                            <a
                              href={trend.source_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:underline"
                            >
                              {trend.source}
                            </a>
                          ) : (
                            <span>{trend.source}</span>
                          )}
                        </div>
                      )}
                    </article>
                  ))}
                </div>
              )}

              {activeTab === 'skills' && (
                <div className="flex flex-wrap gap-2">
                  {result.skills_in_demand.map((skill, idx) => (
                    <span
                      key={idx}
                      className="inline-flex items-center gap-1 bg-indigo-50 text-indigo-700 px-3 py-1.5 rounded-full text-sm font-medium"
                    >
                      <Zap className="w-3 h-3" />
                      {skill}
                    </span>
                  ))}
                </div>
              )}

              {activeTab === 'outlook' && (
                <p className="text-slate-700 leading-relaxed whitespace-pre-line">
                  {result.outlook}
                </p>
              )}
            </div>
          </section>
        </div>
      )}

      {!loading && !result && !error && <EmptyState />}
    </div>
  )
}

function LoadingSkeleton() {
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-500 flex items-center gap-2">
        <Loader2 className="w-3.5 h-3.5 animate-spin" />
        Running the analysis. A local model can take up to a minute.
      </p>
      <div className="space-y-4 animate-pulse">
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <div className="h-6 bg-slate-200 rounded w-1/3 mb-4" />
          <div className="space-y-3">
            <div className="h-4 bg-slate-200 rounded w-full" />
            <div className="h-4 bg-slate-200 rounded w-5/6" />
            <div className="h-4 bg-slate-200 rounded w-4/6" />
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {[0, 1, 2].map((i) => (
            <div key={i} className="bg-white rounded-xl border border-slate-200 p-4">
              <div className="h-4 bg-slate-200 rounded w-2/3 mb-3" />
              <div className="h-3 bg-slate-200 rounded w-full mb-2" />
              <div className="h-3 bg-slate-200 rounded w-4/5" />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="text-center py-16">
      <div className="w-16 h-16 bg-indigo-50 rounded-full flex items-center justify-center mx-auto mb-4">
        <Search className="w-8 h-8 text-indigo-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-900 mb-2">Explore Your Industry</h3>
      <p className="text-slate-500 max-w-md mx-auto">
        Enter an industry and an optional job title to pull together trends, in-demand skills,
        and career outlook.
      </p>
    </div>
  )
}
