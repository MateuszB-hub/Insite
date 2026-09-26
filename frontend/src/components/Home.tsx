import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, Building2, CheckCircle2, Circle, ExternalLink, FileText, Loader2, MapPin, Sparkles,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import {
  fetchMyApplications,
  fetchProfile,
  searchJobs,
  type Application,
  type ApplicationGroup,
  type ApplicationPage,
  type JobPosting,
  type Profile,
} from '../lib/api'
import { hasExploredPathway } from '../lib/progress'
import { PostedAgo, SalaryLine } from './JobBits'
import StatusBadge from './StatusBadge'

const PICKS = 5
//: Same default as Find Roles: testers found older adverts already filled.
const PICK_DAYS = 7

const GROUPS: { key: Exclude<ApplicationGroup, 'all'>; label: string }[] = [
  { key: 'active', label: 'Active' },
  { key: 'interviewing', label: 'Interviewing' },
  { key: 'offers', label: 'Offers' },
  { key: 'closed', label: 'Closed' },
]

//: Home is visited often and each search spends Adzuna quota, so picks are
//: kept for a few minutes in this tab. A miss or blocked storage just fetches.
const PICKS_KEY = 'insite.homePicks'
const PICKS_TTL_MS = 10 * 60 * 1000

function cachedPicks(key: string): JobPosting[] | null {
  try {
    const hit = JSON.parse(sessionStorage.getItem(PICKS_KEY) ?? 'null')
    return hit?.key === key && Date.now() - hit.at < PICKS_TTL_MS ? hit.postings : null
  } catch {
    return null
  }
}

function storePicks(key: string, postings: JobPosting[]): void {
  try {
    sessionStorage.setItem(PICKS_KEY, JSON.stringify({ key, at: Date.now(), postings }))
  } catch {
    // Storage full or blocked: the next visit fetches again.
  }
}

/** Link into Find Roles with the profile's search already filled in. */
function jobsLink(profile: Profile | null): string {
  const qs = new URLSearchParams()
  if (profile?.current_role) qs.set('q', profile.current_role)
  if (profile?.location) qs.append('where', profile.location)
  const query = qs.toString()
  return `/jobs${query ? `?${query}` : ''}`
}

function pathwayLink(profile: Profile | null): string {
  const qs = new URLSearchParams()
  if (profile?.current_role) qs.set('role', profile.current_role)
  if (profile?.industry) qs.set('industry', profile.industry)
  const query = qs.toString()
  return `/pathway${query ? `?${query}` : ''}`
}

/** The most recent thing that happened to an application. */
function lastActivity(app: Application): string {
  const latest = app.events.reduce<string>(
    (acc, e) => (e.occurred_at > acc ? e.occurred_at : acc), app.created_at)
  return new Date(latest).toLocaleDateString()
}

/**
 * What a signed-in person lands on: how to get going, jobs picked from their
 * profile, and where their applications stand. Everything here is a view onto
 * the other pages, so each section links to the page that does the work.
 */
export default function Home() {
  const { user } = useAuth()
  const [profile, setProfile] = useState<Profile | null>(null)
  const [profileLoaded, setProfileLoaded] = useState(false)
  const [apps, setApps] = useState<ApplicationPage | null>(null)

  const [picks, setPicks] = useState<JobPosting[] | null>(null)
  const [picksLoading, setPicksLoading] = useState(false)
  const [picksError, setPicksError] = useState<string | null>(null)

  useEffect(() => {
    fetchProfile()
      .then(setProfile)
      .catch(() => { /* treated as an empty profile */ })
      .finally(() => setProfileLoaded(true))
    fetchMyApplications({ sort: 'updated', limit: 3 })
      .then(setApps)
      .catch(() => { /* summary just stays hidden */ })
  }, [])

  const role = profile?.current_role?.trim() ?? ''
  const location = profile?.location?.trim() ?? ''

  useEffect(() => {
    if (!role) return
    const key = `${role}|${location}`.toLowerCase()
    const cached = cachedPicks(key)
    if (cached) {
      setPicks(cached)
      return
    }
    const controller = new AbortController()
    setPicksLoading(true)
    setPicksError(null)
    searchJobs({
      q: role,
      where: location ? [location] : [],
      maxDaysOld: PICK_DAYS,
      signal: controller.signal,
    })
      .then((data) => {
        const top = data.postings.slice(0, PICKS)
        storePicks(key, top)
        setPicks(top)
      })
      .catch((err) => {
        if (err instanceof DOMException && err.name === 'AbortError') return
        setPicksError(err instanceof Error ? err.message : 'Could not load jobs')
      })
      .finally(() => {
        if (!controller.signal.aborted) setPicksLoading(false)
      })
    return () => controller.abort()
  }, [role, location])

  const firstName = user?.full_name?.trim().split(/\s+/)[0]

  const steps = [
    {
      done: Boolean(role),
      title: 'Tell us your role and where you want to work',
      detail: 'Your profile picks the jobs below and fills in the other pages for you.',
      to: '/profile',
      cta: 'Fill in profile',
    },
    {
      done: (apps?.counts.all ?? 0) > 0,
      title: 'Find roles near you and track one you apply to',
      detail: 'Recent jobs only, with where the pay figure came from shown on each.',
      to: jobsLink(profile),
      cta: 'Find roles',
    },
    {
      done: hasExploredPathway(),
      title: 'See where your job can lead',
      detail: 'Next roles, what they pay, and what it takes to get there.',
      to: pathwayLink(profile),
      cta: 'Explore pathway',
    },
  ]
  const doneCount = steps.filter((s) => s.done).length

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-8">
      <header>
        <h1 className="text-3xl font-bold text-slate-900">
          {firstName ? `Welcome, ${firstName}` : 'Welcome'}
        </h1>
        <p className="text-slate-500 mt-1">Your job search and career planning in one place.</p>
      </header>

      {profileLoaded && doneCount < steps.length && (
        <section aria-labelledby="get-started"
          className="bg-gradient-to-r from-indigo-50 to-purple-50 rounded-xl border border-indigo-100 p-6">
          <div className="flex items-baseline justify-between gap-4 mb-4">
            <h2 id="get-started" className="text-lg font-semibold text-indigo-900">Get started</h2>
            <span className="text-sm text-indigo-700">{doneCount} of {steps.length} done</span>
          </div>
          <ol className="space-y-3">
            {steps.map((step) => (
              <li key={step.title} data-done={step.done}
                className="flex items-start gap-3 bg-white/80 rounded-lg border border-indigo-100 p-4">
                {step.done
                  ? <CheckCircle2 className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" aria-label="Done" />
                  : <Circle className="w-5 h-5 text-indigo-300 shrink-0 mt-0.5" aria-label="Not done" />}
                <div className="flex-1 min-w-0">
                  <p className={`font-medium ${step.done ? 'text-slate-500 line-through' : 'text-slate-900'}`}>
                    {step.title}
                  </p>
                  {!step.done && <p className="text-sm text-slate-500 mt-0.5">{step.detail}</p>}
                </div>
                {!step.done && (
                  <Link to={step.to}
                    className="shrink-0 inline-flex items-center gap-1 text-sm font-medium text-indigo-600 hover:text-indigo-800">
                    {step.cta} <ArrowRight className="w-4 h-4" />
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </section>
      )}

      <section aria-labelledby="picked-jobs">
        <div className="flex items-baseline justify-between gap-4 mb-3">
          <h2 id="picked-jobs" className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-indigo-500" /> Jobs picked for you
          </h2>
          {role && (
            <Link to={jobsLink(profile)} className="text-sm text-indigo-600 hover:underline">
              See all in Find Roles
            </Link>
          )}
        </div>

        {profileLoaded && !role && (
          <div className="bg-white rounded-xl border border-dashed border-slate-300 p-6 text-slate-600">
            Add your role (and where you want to work) to your{' '}
            <Link to="/profile" className="text-indigo-600 hover:underline">profile</Link>, and
            jobs posted in the past {PICK_DAYS} days will show up here.
          </div>
        )}

        {role && (
          <p className="text-sm text-slate-500 mb-3">
            <span className="font-medium text-slate-700">{role}</span>
            {location ? <> in <span className="font-medium text-slate-700">{location}</span></> : ', any location'}
            , posted in the past {PICK_DAYS} days.
          </p>
        )}

        {picksLoading && (
          <p className="text-sm text-slate-500 flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin" /> Finding recent jobs…
          </p>
        )}

        {picksError && !picksLoading && (
          <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
            Could not load jobs right now: {picksError}
          </div>
        )}

        {picks && !picksLoading && !picksError && picks.length === 0 && (
          <div className="bg-white rounded-xl border border-slate-200 p-6 text-slate-600">
            No new jobs matched in the past {PICK_DAYS} days.{' '}
            <Link to={jobsLink(profile)} className="text-indigo-600 hover:underline">
              Try a wider search
            </Link>.
          </div>
        )}

        {picks && !picksLoading && picks.length > 0 && (
          <ul className="space-y-3">
            {picks.map((job) => (
              <li key={job.id} data-testid="picked-job"
                className="bg-white border border-slate-200 rounded-xl p-4 hover:border-indigo-200 transition-colors">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <a href={job.url} target="_blank" rel="noopener noreferrer"
                      className="font-semibold text-slate-900 hover:text-indigo-700 inline-flex items-center gap-1">
                      {job.title} <ExternalLink className="w-3.5 h-3.5 text-slate-400" />
                    </a>
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
                      <PostedAgo created={job.created} />
                    </div>
                  </div>
                </div>
                <div className="mt-2"><SalaryLine job={job} /></div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-labelledby="my-applications">
        <div className="flex items-baseline justify-between gap-4 mb-3">
          <h2 id="my-applications" className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <FileText className="w-5 h-5 text-indigo-500" /> My applications
          </h2>
          <Link to="/applications" className="text-sm text-indigo-600 hover:underline">
            Open My Applications
          </Link>
        </div>

        {apps && apps.counts.all === 0 && (
          <div className="bg-white rounded-xl border border-dashed border-slate-300 p-6 text-slate-600">
            Nothing tracked yet. Press "Mark as applied" on a job in{' '}
            <Link to={jobsLink(profile)} className="text-indigo-600 hover:underline">Find Roles</Link>{' '}
            and it will be followed here.
          </div>
        )}

        {apps && apps.counts.all > 0 && (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
              {GROUPS.map((g) => (
                <Link key={g.key} to={`/applications?group=${g.key}`} data-testid={`count-${g.key}`}
                  className="bg-white rounded-xl border border-slate-200 p-4 hover:border-indigo-200 transition-colors">
                  <p className="text-2xl font-bold text-slate-900">{apps.counts[g.key]}</p>
                  <p className="text-sm text-slate-500">{g.label}</p>
                </Link>
              ))}
            </div>
            <ul className="bg-white rounded-xl border border-slate-200 divide-y divide-slate-100">
              {apps.items.map((app) => (
                <li key={app.id} className="flex items-center justify-between gap-4 px-4 py-3">
                  <div className="min-w-0">
                    <p className="font-medium text-slate-900 truncate">{app.position_title}</p>
                    <p className="text-sm text-slate-500 truncate">
                      {app.company ?? 'Company not recorded'} · updated {lastActivity(app)}
                    </p>
                  </div>
                  <StatusBadge status={app.status} />
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </div>
  )
}
