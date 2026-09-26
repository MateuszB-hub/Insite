import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, ExternalLink, FileText, Loader2, Search, Trash2, Undo2 } from 'lucide-react'
import {
  fetchMyApplications,
  removeApplication,
  undoApplicationStatus,
  updateApplicationStatus,
  type Application,
  type ApplicationGroup,
  type ApplicationStatus,
} from '../lib/api'
import StatusBadge from './StatusBadge'

const when = (iso: string) => new Date(iso).toLocaleDateString()
const label = (status: string) => status.replace('_', ' ')

const PAGE = 25

/** Where Undo goes: replay the timeline like the server does (a change
 * pushes, an undo pops) and take the status under the top. */
function undoTarget(a: Application): string | null {
  const stack: string[] = []
  for (const e of a.events) {
    if (e.is_undo) stack.pop()
    else stack.push(e.to_status)
  }
  return stack.length >= 2 ? stack[stack.length - 2] : null
}

/**
 * What you can record next. Mirrors ALLOWED_TRANSITIONS on the server.
 *
 * This is a candidate-side tool: you are logging what happened to an
 * application you sent somewhere else, so every transition is yours. There
 * is no recruiter here moving you through a pipeline.
 */
const NEXT: Record<ApplicationStatus, ApplicationStatus[]> = {
  draft: ['submitted', 'withdrawn'],
  submitted: ['in_review', 'rejected', 'withdrawn'],
  in_review: ['interview', 'rejected', 'withdrawn'],
  interview: ['offer', 'rejected', 'withdrawn'],
  offer: ['rejected', 'withdrawn'],
  rejected: [],
  withdrawn: [],
}

const ACTION_LABEL: Record<ApplicationStatus, string> = {
  draft: 'Back to draft',
  submitted: 'Mark as sent',
  in_review: 'They responded',
  interview: 'Got an interview',
  offer: 'Got an offer',
  rejected: 'Rejected',
  withdrawn: 'Withdraw',
}

/** Closing an application is the misclick that hurts most, so it asks first. */
const CONFIRM: Partial<Record<ApplicationStatus, string>> = {
  rejected: 'Mark this application as rejected?',
  withdrawn: 'Withdraw this application?',
}

const TABS: { key: ApplicationGroup; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'active', label: 'Active' },
  { key: 'interviewing', label: 'Interviewing' },
  { key: 'offers', label: 'Offers' },
  { key: 'closed', label: 'Closed' },
]

export default function MyApplications() {
  const [apps, setApps] = useState<Application[]>([])
  const [total, setTotal] = useState(0)
  const [counts, setCounts] = useState<Record<ApplicationGroup, number> | null>(null)
  //: Home's count tiles link here as ?group=interviewing etc.
  const [params] = useSearchParams()
  const [group, setGroup] = useState<ApplicationGroup>(() => {
    const wanted = params.get('group')
    return TABS.find((t) => t.key === wanted)?.key ?? 'all'
  })
  const [query, setQuery] = useState('')
  const [search, setSearch] = useState('')
  const [sort, setSort] = useState<'updated' | 'added'>('updated')
  const [open, setOpen] = useState<Set<string>>(new Set())

  const [loading, setLoading] = useState(true)
  const [more, setMore] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Search as you type, without a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setSearch(query), 300)
    return () => clearTimeout(t)
  }, [query])

  // Responses can arrive out of order; only the latest request may land.
  const latest = useRef(0)

  /** Load the first `count` rows for the current tab/search/sort. */
  const load = useCallback((count = PAGE) => {
    const ticket = ++latest.current
    return fetchMyApplications({ group, q: search, sort, limit: Math.min(count, 100) })
      .then((page) => {
        if (ticket !== latest.current) return
        setApps(page.items)
        setTotal(page.total)
        setCounts(page.counts)
      })
      .catch((e) => setError(e.message))
      .finally(() => { if (ticket === latest.current) setLoading(false) })
  }, [group, search, sort])

  useEffect(() => { load() }, [load])

  const showMore = async () => {
    setMore(true)
    try {
      const page = await fetchMyApplications({ group, q: search, sort, limit: PAGE, offset: apps.length })
      setApps((prev) => [...prev, ...page.items])
      setTotal(page.total)
      setCounts(page.counts)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load more')
    } finally {
      setMore(false)
    }
  }

  /** Run a change, then refresh what's loaded: the row may change tab. */
  const act = async (id: string, change: () => Promise<unknown>) => {
    setBusy(id)
    setError(null)
    try {
      await change()
      await load(Math.max(PAGE, apps.length))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update')
    } finally {
      setBusy(null)
    }
  }

  const record = (a: Application, status: ApplicationStatus) => {
    const question = CONFIRM[status]
    if (question && !window.confirm(`${question}\n\n${a.position_title}`)) return
    act(a.id, () => updateApplicationStatus(a.id, status))
  }

  const remove = (a: Application) => {
    if (!window.confirm(`Remove "${a.position_title}" from your applications?\n\nIts history is deleted too.`)) return
    act(a.id, () => removeApplication(a.id))
  }

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const filtered = search.trim() !== '' || group !== 'all'
  const empty = !loading && counts?.all === 0 && !search.trim()

  return (
    <div className="p-8 max-w-4xl mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">My Applications</h1>
        <p className="text-slate-500 mt-1">
          Applications you've sent. Record what happens as you hear back.
        </p>
      </header>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm mb-4">
          {error}
        </div>
      )}

      {empty ? (
        <div className="text-center py-16">
          <div className="w-14 h-14 bg-indigo-50 rounded-full flex items-center justify-center mx-auto mb-3">
            <FileText className="w-7 h-7 text-indigo-400" />
          </div>
          <p className="text-slate-600 mb-1">You haven't applied to anything yet.</p>
          <Link to="/jobs" className="text-indigo-600 hover:underline text-sm">
            Find roles
          </Link>
        </div>
      ) : (
        <>
          <div className="flex flex-wrap gap-1 border-b border-slate-200 mb-4" role="tablist">
            {TABS.map((t) => (
              <button key={t.key} type="button" role="tab" aria-selected={group === t.key}
                onClick={() => setGroup(t.key)}
                className={`px-3 py-2 text-sm font-medium -mb-px border-b-2 transition ${
                  group === t.key
                    ? 'border-indigo-600 text-indigo-700'
                    : 'border-transparent text-slate-500 hover:text-slate-700'
                }`}>
                {t.label}
                {counts && <span className="ml-1.5 text-xs text-slate-400">{counts[t.key]}</span>}
              </button>
            ))}
          </div>

          <div className="flex flex-col sm:flex-row gap-3 mb-4">
            <label className="relative flex-1">
              <span className="sr-only">Search applications</span>
              <Search className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input id="app-search" value={query} onChange={(e) => setQuery(e.target.value)}
                placeholder="Search job title or company"
                className="w-full pl-9 pr-3 py-2 rounded-lg border border-slate-300 text-sm focus:ring-2 focus:ring-indigo-500 outline-none" />
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              Sort
              <select id="app-sort" value={sort} onChange={(e) => setSort(e.target.value as 'updated' | 'added')}
                className="rounded-lg border border-slate-300 text-sm py-2 pl-2 pr-7 focus:ring-2 focus:ring-indigo-500 outline-none">
                <option value="updated">Recently updated</option>
                <option value="added">Recently added</option>
              </select>
            </label>
          </div>

          {loading ? (
            <div className="flex items-center gap-2 text-slate-400 py-10 justify-center">
              <Loader2 className="w-5 h-5 animate-spin" /> Loading…
            </div>
          ) : apps.length === 0 ? (
            <p className="text-center text-slate-500 py-12">
              {filtered ? 'Nothing matches here.' : 'No applications yet.'}
            </p>
          ) : (
            <div className="grid gap-3">
              {apps.map((a) => {
                const undoTo = undoTarget(a)
                return (
                  <article key={a.id} className="bg-white border border-slate-200 rounded-xl p-5">
                    <div className="flex items-start justify-between gap-4">
                      <div className="min-w-0">
                        {/* External jobs link out; our own postings link inward. */}
                        {a.job_url ? (
                          <a href={a.job_url} target="_blank" rel="noopener noreferrer"
                            className="font-semibold text-slate-900 hover:text-indigo-700 inline-flex items-center gap-1">
                            {a.position_title}
                            <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                          </a>
                        ) : (
                          <span className="font-semibold text-slate-900">{a.position_title}</span>
                        )}
                        {(a.company || a.job_location) && (
                          <p className="text-sm text-slate-500 mt-0.5">
                            {[a.company, a.job_location].filter(Boolean).join(' · ')}
                          </p>
                        )}
                        <p className="text-xs text-slate-400 mt-0.5">
                          Added {when(a.created_at)}
                          {a.submitted_at && ` · Applied ${when(a.submitted_at)}`}
                        </p>
                      </div>
                      <StatusBadge status={a.status} />
                    </div>

                    <div className="flex flex-wrap items-center gap-2 mt-4">
                      {NEXT[a.status].map((target) => (
                        <button key={target} type="button" disabled={busy === a.id}
                          onClick={() => record(a, target)}
                          className={`text-sm px-3 py-1.5 rounded-lg font-medium border transition disabled:opacity-50 ${
                            target === 'rejected' || target === 'withdrawn'
                              ? 'border-slate-300 text-slate-600 hover:bg-slate-50'
                              : 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700'
                          }`}>
                          {ACTION_LABEL[target]}
                        </button>
                      ))}
                      {a.can_undo && (
                        <button type="button" disabled={busy === a.id}
                          onClick={() => act(a.id, () => undoApplicationStatus(a.id))}
                          title={undoTo ? `Back to "${label(undoTo)}"` : 'Back to the previous status'}
                          className="text-sm px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50 inline-flex items-center gap-1.5 disabled:opacity-50">
                          <Undo2 className="w-3.5 h-3.5" /> Undo
                        </button>
                      )}
                      <span className="flex-1" />
                      {a.events.length > 1 && (
                        <button type="button" onClick={() => toggle(a.id)}
                          aria-expanded={open.has(a.id)}
                          className="text-xs text-slate-500 hover:text-slate-700 inline-flex items-center gap-1">
                          History
                          <ChevronDown className={`w-3.5 h-3.5 transition ${open.has(a.id) ? 'rotate-180' : ''}`} />
                        </button>
                      )}
                      <button type="button" disabled={busy === a.id} onClick={() => remove(a)}
                        aria-label={`Remove ${a.position_title}`}
                        className="text-xs text-slate-400 hover:text-red-600 inline-flex items-center gap-1 disabled:opacity-50">
                        <Trash2 className="w-3.5 h-3.5" /> Remove
                      </button>
                    </div>

                    {open.has(a.id) && (
                      <ol className="mt-3 space-y-1 text-xs text-slate-500 border-t border-slate-100 pt-3">
                        {a.events.map((e, i) => (
                          <li key={i} className="flex gap-3">
                            <span className="text-slate-400 w-20 shrink-0">{when(e.occurred_at)}</span>
                            <span className={e.is_undo ? 'italic' : ''}>
                              {e.is_undo ? `Undo → ${label(e.to_status)}` : label(e.to_status)}
                            </span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </article>
                )
              })}
            </div>
          )}

          {!loading && apps.length < total && (
            <div className="text-center mt-4">
              <button type="button" onClick={showMore} disabled={more}
                className="text-sm px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 inline-flex items-center gap-2">
                {more && <Loader2 className="w-4 h-4 animate-spin" />}
                Show more ({total - apps.length} left)
              </button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
