import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ExternalLink, FileText, Loader2 } from 'lucide-react'
import {
  fetchMyApplications,
  updateApplicationStatus,
  type Application,
  type ApplicationStatus,
} from '../lib/api'
import StatusBadge from './StatusBadge'

const when = (iso: string) => new Date(iso).toLocaleDateString()

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

export default function MyApplications() {
  const [apps, setApps] = useState<Application[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(() => {
    fetchMyApplications()
      .then(setApps)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  useEffect(load, [load])

  const record = async (id: string, status: ApplicationStatus) => {
    setBusy(id)
    setError(null)
    try {
      const updated = await updateApplicationStatus(id, status)
      setApps((prev) => prev.map((a) => (a.id === id ? { ...a, ...updated } : a)))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not update')
    } finally {
      setBusy(null)
    }
  }

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

      {loading ? (
        <div className="flex items-center gap-2 text-slate-400 py-10 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading…
        </div>
      ) : apps.length === 0 ? (
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
        <div className="grid gap-3">
          {apps.map((a) => (
            <article key={a.id} className="bg-white border border-slate-200 rounded-xl p-5">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  {/* External jobs link out; our own postings link inward. */}
                  {a.job_url ? (
                    <a
                      href={a.job_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="font-semibold text-slate-900 hover:text-indigo-700 inline-flex items-center gap-1"
                    >
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

              {a.events.length > 1 && (
                <ol className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
                  {a.events.map((e, i) => (
                    <li key={i} className="flex items-center gap-2">
                      {i > 0 && <span className="text-slate-300">→</span>}
                      <span>{e.to_status.replace('_', ' ')}</span>
                    </li>
                  ))}
                </ol>
              )}

              {NEXT[a.status].length > 0 && (
                <div className="flex flex-wrap gap-2 mt-4">
                  {NEXT[a.status].map((target) => (
                    <button
                      key={target}
                      type="button"
                      disabled={busy === a.id}
                      onClick={() => record(a.id, target)}
                      className={`text-sm px-3 py-1.5 rounded-lg font-medium border transition disabled:opacity-50 ${
                        target === 'rejected' || target === 'withdrawn'
                          ? 'border-slate-300 text-slate-600 hover:bg-slate-50'
                          : 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700'
                      }`}
                    >
                      {ACTION_LABEL[target]}
                    </button>
                  ))}
                </div>
              )}
            </article>
          ))}
        </div>
      )}
    </div>
  )
}
