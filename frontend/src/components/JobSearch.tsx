import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import type { FormEvent } from 'react'
import {
  Search, Loader2, MapPin, Building2, ExternalLink,
  TriangleAlert, Info, Copy, History, CheckCircle2, Plus, X,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { loadRecent, saveRecent } from '../lib/recent'
import {
  JOB_TYPE_LABELS,
  MAX_JOB_LOCATIONS,
  fetchProfile,
  fetchTrackedFingerprints,
  searchJobs,
  trackJob,
  type JobPosting,
  type JobSearchResponse,
  type JobType,
} from '../lib/api'
import { PostedAgo, SalaryLine } from './JobBits'

const AGE_CHOICES = [
  { value: '7', label: 'Past 7 days' },
  { value: '14', label: 'Past 14 days' },
  { value: '30', label: 'Past 30 days' },
  { value: '', label: 'Any time' },
]

const TYPE_CHOICES: { value: JobType | ''; label: string }[] = [
  { value: '', label: 'Any type' },
  ...(Object.entries(JOB_TYPE_LABELS) as [JobType, string][]).map(([value, label]) => ({ value, label })),
]

interface RecentSearch {
  q: string
  places: string[]
  jobType: JobType | ''
}

const recentKey = (r: RecentSearch) =>
  `${r.q.toLowerCase()}|${r.places.join(',').toLowerCase()}|${r.jobType}`

/** The site a link opens, so a job board is never mistaken for the employer. */
function siteOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '')
  } catch {
    return 'another site'
  }
}

export default function JobSearch() {
  //: Home links here as /jobs?q=...&where=..., and the search runs on arrival.
  const [params] = useSearchParams()
  const [q, setQ] = useState(() => params.get('q') ?? '')
  //: Places are tags, not free text: a comma is part of "Austin, TX", so it
  //: cannot separate cities.
  const [places, setPlaces] = useState<string[]>(
    () => params.getAll('where').filter(Boolean).slice(0, MAX_JOB_LOCATIONS))
  const [placeDraft, setPlaceDraft] = useState('')
  const [salaryMin, setSalaryMin] = useState('')
  //: Default a week: testers found older adverts are usually already filled.
  const [maxDaysOld, setMaxDaysOld] = useState('7')
  const [requireStated, setRequireStated] = useState(false)
  const [remoteOnly, setRemoteOnly] = useState(false)
  const [includeConflicted, setIncludeConflicted] = useState(false)
  const [jobType, setJobType] = useState<JobType | ''>('')
  const { user } = useAuth()
  const [recent, setRecent] = useState<RecentSearch[]>(() => loadRecent<RecentSearch>('jobs', user?.id))
  //: Mentor: Find Roles "should use your profile information".
  const [fromProfile, setFromProfile] = useState(false)

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

  // With no search in the link, start from the profile's role and place.
  useEffect(() => {
    if (params.get('q')) return
    fetchProfile()
      .then((p) => {
        const role = p.current_role?.trim()
        if (!role) return
        setQ((cur) => cur || role)
        const place = p.location?.trim()
        if (place) setPlaces((cur) => (cur.length ? cur : [place]))
        setFromProfile(true)
      })
      .catch(() => { /* no profile: the form just starts empty */ })
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  const runSearch = async (query: string, where: string[], type: JobType | '' = jobType) => {
    setLoading(true)
    setError(null)
    try {
      setData(await searchJobs({
        q: query,
        where,
        jobType: type || undefined,
        salaryMin: salaryMin ? Number(salaryMin) : undefined,
        maxDaysOld: maxDaysOld ? Number(maxDaysOld) : undefined,
        requireStatedSalary: requireStated,
        remoteOnly,
        includeConflictedRemote: includeConflicted,
      }))
      setRecent(saveRecent('jobs', user?.id, { q: query, places: where, jobType: type }, recentKey))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Search failed')
    } finally {
      setLoading(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!q.trim() || loading) return
    // Text still in the box counts, so nobody has to press Enter first.
    const where = withPlace(places, placeDraft)
    setPlaces(where)
    setPlaceDraft('')
    await runSearch(q.trim(), where)
  }

  const rerun = (r: RecentSearch) => {
    setQ(r.q)
    setPlaces(r.places)
    setPlaceDraft('')
    setJobType(r.jobType)
    setFromProfile(false)
    void runSearch(r.q, r.places, r.jobType)
  }

  // Arriving with ?q= (from Home) runs that search once, with the defaults.
  const ranFromLink = useRef(false)
  useEffect(() => {
    if (ranFromLink.current || !q.trim()) return
    ranFromLink.current = true
    void runSearch(q.trim(), places)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const renderJob = (job: JobPosting, section: 'stated' | 'estimated' | 'loose' = 'stated') => (
      <article key={job.id} data-section={section}
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
              {job.job_types && job.job_types.length > 0 && (
                <span>{job.job_types.map((t) => JOB_TYPE_LABELS[t]).join(' · ')}</span>
              )}
      <PostedAgo created={job.created} />
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
          {/* Mentor: "the url for the link makes it look fishy". Say where it goes. */}
          <a href={job.url} target="_blank" rel="noopener noreferrer"
            title={`Opens the listing on ${siteOf(job.url)}, a job board. From there, apply on the employer's own site.`}
            className="inline-flex items-center gap-1 text-sm text-indigo-600 hover:underline">
            View listing on {siteOf(job.url)} <ExternalLink className="w-3.5 h-3.5" />
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
  )

  const excluded = data
    ? data.excluded_estimated_salary + data.excluded_no_salary +
      data.excluded_not_remote + data.excluded_below_salary +
      (data.excluded_type_unstated ?? 0) + (data.excluded_other_type ?? 0)
    : 0
  const multiWord = q.trim().split(/\s+/).length >= 2
  const loose = data?.loose_matches ?? []
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
            <input id="q" value={q} onChange={(e) => { setQ(e.target.value); setFromProfile(false) }}
              placeholder="e.g. Registered Nurse" className={field} />
            {fromProfile && (
              <p className="text-xs text-slate-500 mt-1">Filled in from your profile. Change it to search anything.</p>
            )}
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
            Posted
            <select id="age" value={maxDaysOld} onChange={(e) => setMaxDaysOld(e.target.value)}
              className="rounded-lg border border-slate-300 text-sm py-1 pl-2 pr-7 focus:ring-2 focus:ring-indigo-500 outline-none">
              {AGE_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            Type
            <select id="type" value={jobType} onChange={(e) => setJobType(e.target.value as JobType | '')}
              className="rounded-lg border border-slate-300 text-sm py-1 pl-2 pr-7 focus:ring-2 focus:ring-indigo-500 outline-none">
              {TYPE_CHOICES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </label>
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

      {!data && !loading && recent.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-6 text-sm" aria-label="Recent searches">
          <span className="text-slate-500">Recent:</span>
          {recent.map((r) => (
            <button key={recentKey(r)} type="button" onClick={() => rerun(r)}
              className="px-3 py-1 rounded-full border border-slate-300 bg-white text-slate-700 hover:border-indigo-400">
              {r.q}{r.places.length ? ` · ${r.places.join(', ')}` : ''}{r.jobType ? ` · ${JOB_TYPE_LABELS[r.jobType]}` : ''}
            </button>
          ))}
        </div>
      )}

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

          {data.match === 'title' && (
            <p className="text-sm text-slate-500 mb-3" data-testid="match-note">
              Jobs with {multiWord ? <>every word of "{q.trim()}"</> : <>"{q.trim()}"</>} in the job title.
            </p>
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
                Showing {data.postings.length + data.estimated_matches.length} of{' '}
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
                  <li>{data.excluded_below_salary} were below your minimum</li>
                )}
                {data.excluded_not_remote > 0 && (
                  <li>{data.excluded_not_remote} said remote but were tied to a location</li>
                )}
                {(data.excluded_type_unstated ?? 0) > 0 && (
                  <li>{data.excluded_type_unstated} didn't say whether they're {jobType ? JOB_TYPE_LABELS[jobType].toLowerCase() : 'that type'} (most adverts don't)</li>
                )}
                {(data.excluded_other_type ?? 0) > 0 && (
                  <li>{data.excluded_other_type} were a different type</li>
                )}
              </ul>
            </div>
          )}

          {data.postings.length === 0 && data.estimated_matches.length === 0 && !loose.length ? (
            <p className="text-center text-slate-500 py-16">
              Nothing matched honestly. Try relaxing a filter{maxDaysOld ? ' or widening "Posted"' : ''}.
            </p>
          ) : (
            <>
              {data.postings.length > 0 ? (
                <div className="grid gap-3">
                  {data.postings.map((job) => renderJob(job))}
                </div>
              ) : (
                <p className="text-sm text-slate-500 bg-white border border-slate-200 rounded-xl p-4">
                  No employer in these results published pay at or above your minimum.
                </p>
              )}

              {/* Estimates that clear the floor: shown, never passed off as stated. */}
              {data.estimated_matches.length > 0 && (
                <section className="mt-8" aria-labelledby="estimated-heading">
                  <h2 id="estimated-heading" className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                    <TriangleAlert className="w-4 h-4 text-amber-600" />
                    Pay estimated by the job board, at or above your minimum
                  </h2>
                  <p className="text-sm text-slate-500 mt-1 mb-3">
                    These employers didn't publish a salary; the figure is the job board's
                    guess. Worth a look, but confirm the pay before you apply.
                  </p>
                  <div className="grid gap-3">
                    {data.estimated_matches.map((job) => renderJob(job, 'estimated'))}
                  </div>
                </section>
              )}

              {/* Only mention the words: kept apart, since this is where
                  off-topic results come from ("QA lead" -> "Lead Carpenter"). */}
              {loose.length > 0 && (
                <section className="mt-8" aria-labelledby="loose-heading" data-testid="loose-matches">
                  <h2 id="loose-heading" className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                    <Info className="w-4 h-4 text-slate-400" />
                    Also mention "{q.trim()}", but not in the job title
                  </h2>
                  <p className="text-sm text-slate-500 mt-1 mb-3">
                    {data.postings.length
                      ? 'Only a few jobs have it in the title, so here are adverts that use the words somewhere. Many will be other kinds of job.'
                      : 'No job titles match, so here are adverts that use the words somewhere. Many will be other kinds of job.'}
                  </p>
                  <div className="grid gap-3">
                    {loose.map((job) => renderJob(job, 'loose'))}
                  </div>
                </section>
              )}
            </>
          )}
        </>
      )}
    </div>
  )
}
