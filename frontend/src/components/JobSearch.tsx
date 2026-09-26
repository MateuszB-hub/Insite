import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Search, Loader2, MapPin, Building2, ExternalLink,
  TriangleAlert, BadgeCheck, CircleHelp, Info, Copy, History, CheckCircle2, Plus, X,
} from 'lucide-react'
import {
  MAX_JOB_LOCATIONS,
  fetchTrackedFingerprints,
  searchJobs,
  trackJob,
  type JobPosting,
  type JobSearchResponse,
} from '../lib/api'

const money = (n?: number | null) =>
  n == null ? null : `$${Math.round(n).toLocaleString()}`

/** Salary provenance, stated plainly rather than buried. */
function SalaryLine({ job }: { job: JobPosting }) {
  const range =
    job.salary_min && job.salary_max && job.salary_min !== job.salary_max
      ? `${money(job.salary_min)}–${money(job.salary_max)}`
      : money(job.salary_min ?? job.salary_max)

  if (job.salary_source === 'absent' || !range) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-slate-400">
        <CircleHelp className="w-3.5 h-3.5" /> No salary stated
      </span>
    )
  }
  if (job.salary_source === 'estimated') {
    return (
      <span
        className="inline-flex items-center gap-1 text-sm text-amber-700"
        title="This figure was estimated by the job board, not published by the employer."
      >
        <TriangleAlert className="w-3.5 h-3.5" />
        {range} <span className="text-xs">(estimated, not from employer)</span>
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1 text-sm font-semibold text-emerald-700">
      <BadgeCheck className="w-3.5 h-3.5" />
      {range} <span className="text-xs font-normal">(employer stated)</span>
    </span>
  )
}

export default function JobSearch() {
  const [q, setQ] = useState('')
  //: Places are tags, not free text: a comma is part of "Austin, TX", so it
  //: cannot separate cities.
  const [places, setPlaces] = useState<string[]>([])
  const [placeDraft, setPlaceDraft] = useState('')
  const [salaryMin, setSalaryMin] = useState('')
  const [requireStated, setRequireStated] = useState(false)
  const [remoteOnly, setRemoteOnly] = useState(false)
  const [includeConflicted, setIncludeConflicted] = useState(false)

  const [data, setData] = useState<JobSearchResponse | null>(null)
  //: Fingerprints of jobs already applied to. Matching on content rather
  //: than advert id means a repost under a new id is still recognised.
  const [tracked, setTracked] = useState<Set<string>>(new Set())
  const [tracking, setTracking] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchTrackedFingerprints().then(setTracked).catch(() => { /* non-fatal */ })
  }, [])

  const markApplied = async (job: JobPosting) => {
    setTracking(job.id)
    setError(null)
    try {
      await trackJob({
        fingerprint: job.fingerprint,
        title: job.title,
        company: job.company,
        location: job.location,
        url: job.url,
        externalId: job.id,
        salaryMin: job.salary_min,
        salaryMax: job.salary_max,
      })
      setTracked((prev) => new Set(prev).add(job.fingerprint))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not track this job')
    } finally {
      setTracking(null)
    }
  }

  const withPlace = (list: string[], place: string) => {
    const p = place.trim()
    if (!p || list.length >= MAX_JOB_LOCATIONS) return list
    return list.some((x) => x.toLowerCase() === p.toLowerCase()) ? list : [...list, p]
  }

  const addPlace = () => {
    setPlaces((prev) => withPlace(prev, placeDraft))
    setPlaceDraft('')
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!q.trim() || loading) return
    // Text still in the box counts, so nobody has to press Enter first.
    const where = withPlace(places, placeDraft)
    setPlaces(where)
    setPlaceDraft('')
    setLoading(true)
    setError(null)
    try {
      setData(await searchJobs({
        q: q.trim(),
        where,
        salaryMin: salaryMin ? Number(salaryMin) : undefined,
        requireStatedSalary: requireStated,
        remoteOnly,
        includeConflictedRemote: includeConflicted,
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  const excluded = data
    ? data.excluded_estimated_salary + data.excluded_no_salary +
      data.excluded_not_remote + data.excluded_below_salary
    : 0
  const folded = data?.collapsed_duplicates ?? 0

  const field =
    'w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition'

  return (
    <div className="p-8 max-w-5xl mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Find Roles</h1>
        <p className="text-slate-500 mt-1">
          Filters that tell you where the numbers came from.
        </p>
      </header>

      <form onSubmit={submit} className="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-6">
        <div className="flex flex-col sm:flex-row gap-4">
          <div className="flex-1">
            <label htmlFor="q" className="block text-sm font-medium text-slate-700 mb-1">
              Role
            </label>
            <input id="q" value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="e.g. Registered Nurse" className={field} />
          </div>
          <div className="flex-1">
            <label htmlFor="where" className="block text-sm font-medium text-slate-700 mb-1">
              Locations{' '}
              <span className="text-slate-400 font-normal">
                (optional, up to {MAX_JOB_LOCATIONS})
              </span>
            </label>
            <input id="where" value={placeDraft}
              onChange={(e) => setPlaceDraft(e.target.value)}
              onKeyDown={(e) => {
                // Enter adds the place as a tag instead of submitting the search.
                if (e.key === 'Enter' && placeDraft.trim()) {
                  e.preventDefault()
                  addPlace()
                } else if (e.key === 'Backspace' && !placeDraft && places.length) {
                  setPlaces((prev) => prev.slice(0, -1))
                }
              }}
              disabled={places.length >= MAX_JOB_LOCATIONS}
              placeholder={
                places.length >= MAX_JOB_LOCATIONS
                  ? `Up to ${MAX_JOB_LOCATIONS} places`
                  : places.length ? 'Add another, press Enter' : 'e.g. Austin, then Enter'
              }
              className={`${field} disabled:bg-slate-50`} />
            {places.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-2" aria-label="Selected locations">
                {places.map((place) => (
                  <span key={place}
                    className="inline-flex items-center gap-1 bg-indigo-50 text-indigo-700 text-sm rounded-full pl-3 pr-1.5 py-0.5">
                    {place}
                    <button type="button" aria-label={`Remove ${place}`}
                      onClick={() => setPlaces((prev) => prev.filter((p) => p !== place))}
                      className="rounded-full p-0.5 hover:bg-indigo-100">
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="w-full sm:w-40">
            <label htmlFor="sal" className="block text-sm font-medium text-slate-700 mb-1">
              Min salary
            </label>
            <input id="sal" type="number" min={0} step={5000} value={salaryMin}
              onChange={(e) => setSalaryMin(e.target.value)}
              placeholder="120000" className={field} />
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-2">
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={requireStated}
              onChange={(e) => setRequireStated(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
            Only employer-stated salaries
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={remoteOnly}
              onChange={(e) => setRemoteOnly(e.target.checked)}
              className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
            Genuinely remote only
          </label>
          {remoteOnly && (
            <label className="flex items-center gap-2 text-sm text-slate-500">
              <input type="checkbox" checked={includeConflicted}
                onChange={(e) => setIncludeConflicted(e.target.checked)}
                className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
              Include "remote" roles tied to a city
            </label>
          )}
          <button type="submit" disabled={loading || !q.trim()}
            className="ml-auto inline-flex items-center gap-2 bg-indigo-600 text-white px-6 py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Search
          </button>
        </div>
      </form>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700 text-sm mb-4">
          {error}
        </div>
      )}

      {data && (
        <>
          {data.failed_locations.length > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 mb-4">
              <p className="text-sm text-amber-800 flex items-center gap-1.5">
                <TriangleAlert className="w-4 h-4" />
                Couldn't search {data.failed_locations.join(', ')} just now. Showing results
                for the other{data.locations_searched.length - data.failed_locations.length === 1 ? '' : 's'}.
              </p>
            </div>
          )}

          {/* Explain a short list rather than letting it look broken. */}
          {folded > 0 && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
              <p className="text-sm text-slate-700 flex items-center gap-1.5">
                <Copy className="w-4 h-4 text-slate-400" />
                {folded} duplicate advert{folded === 1 ? '' : 's'} folded in — the same
                job posted repeatedly counts once here.
              </p>
            </div>
          )}

          {excluded > 0 && (
            <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 mb-4">
              <p className="text-sm text-slate-700 flex items-center gap-1.5">
                <Info className="w-4 h-4 text-slate-400" />
                Showing {data.postings.length} of{' '}
                {data.total_available?.toLocaleString() ?? 'many'} — {excluded} hidden by your filters
              </p>
              <ul className="mt-1.5 text-xs text-slate-500 space-y-0.5">
                {data.excluded_estimated_salary > 0 && (
                  <li>{data.excluded_estimated_salary} had a salary estimated by the board, not the employer</li>
                )}
                {data.excluded_no_salary > 0 && (
                  <li>{data.excluded_no_salary} stated no salary at all</li>
                )}
                {data.excluded_below_salary > 0 && (
                  <li>{data.excluded_below_salary} were genuinely below your minimum</li>
                )}
                {data.excluded_not_remote > 0 && (
                  <li>{data.excluded_not_remote} said remote but were tied to a location</li>
                )}
              </ul>
            </div>
          )}

          {data.postings.length === 0 ? (
            <p className="text-center text-slate-500 py-16">
              Nothing matched honestly. Try relaxing a filter.
            </p>
          ) : (
            <div className="grid gap-3">
              {data.postings.map((job) => (
                <article key={job.id}
                  className={`border rounded-xl p-5 transition-colors ${
                    tracked.has(job.fingerprint)
                      ? 'bg-slate-50 border-slate-200 opacity-75'
                      : 'bg-white border-slate-200 hover:border-indigo-200'
                  }`}>
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <h2 className="font-semibold text-slate-900">{job.title}</h2>
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-sm text-slate-500">
                        {job.company && (
                          <span className="inline-flex items-center gap-1">
                            <Building2 className="w-3.5 h-3.5" /> {job.company}
                          </span>
                        )}
                        {job.location && (
                          <span className="inline-flex items-center gap-1">
                            <MapPin className="w-3.5 h-3.5" /> {job.location}
                          </span>
                        )}
                        {job.contract_time && <span>{job.contract_time.replace('_', ' ')}</span>}
                      </div>
                    </div>
                    {job.remote_claim === 'remote' && (
                      <span className="shrink-0 text-xs px-2 py-0.5 rounded-full border bg-emerald-50 text-emerald-700 border-emerald-200">
                        Remote
                      </span>
                    )}
                    {job.remote_claim === 'conflicted' && (
                      <span className="shrink-0 text-xs px-2 py-0.5 rounded-full border bg-amber-50 text-amber-700 border-amber-200">
                        Remote? unclear
                      </span>
                    )}
                  </div>

                  <div className="mt-3"><SalaryLine job={job} /></div>

                  {job.duplicate_count > 1 && (
                    <p className="mt-2 text-xs text-slate-500 flex items-start gap-1.5">
                      <Copy className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      The same advert appears {job.duplicate_count} times
                      {job.duplicate_locations.length > 0 && (
                        <> — also in {job.duplicate_locations.slice(0, 3).join(', ')}
                        {job.duplicate_locations.length > 3 &&
                          ` and ${job.duplicate_locations.length - 3} more`}</>
                      )}
                    </p>
                  )}

                  {job.is_repost && (
                    <p className="mt-2 text-xs text-amber-700 flex items-start gap-1.5">
                      <History className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      We first saw this advert on{' '}
                      {new Date(job.first_seen!).toLocaleDateString()} — it has been
                      reposted since, which resets the date the board shows.
                    </p>
                  )}

                  {job.remote_note && (
                    <p className="mt-2 text-xs text-amber-700 flex items-start gap-1.5">
                      <TriangleAlert className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                      {job.remote_note}
                    </p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-4">
                    <a href={job.url} target="_blank" rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline">
                      View posting <ExternalLink className="w-3.5 h-3.5" />
                    </a>

                    {tracked.has(job.fingerprint) ? (
                      <span className="inline-flex items-center gap-1.5 text-sm text-emerald-700 font-medium">
                        <CheckCircle2 className="w-4 h-4" /> Already applied
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={tracking === job.id}
                        onClick={() => markApplied(job)}
                        className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 disabled:opacity-50 transition"
                      >
                        {tracking === job.id
                          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          : <Plus className="w-3.5 h-3.5" />}
                        Mark as applied
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
