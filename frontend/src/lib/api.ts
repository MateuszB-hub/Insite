/** Types mirror the Pydantic models in backend/app/routes/future_of_work.py */

export interface TrendFinding {
  title: string
  summary: string
  source?: string | null
  source_url?: string | null
}

export interface FutureOfWorkResult {
  industry: string
  job_title?: string | null
  /** Which backend actually produced this report. */
  provider: string
  provider_label: string
  executive_summary: string
  trends: TrendFinding[]
  skills_in_demand: string[]
  outlook: string
}

export type ProviderTier = 'local' | 'free' | 'paid'

export interface ProviderInfo {
  name: string
  label: string
  tier: ProviderTier
  /** Usable right now (daemon up, model pulled, key present). */
  available: boolean
  /** Paid provider held back because paid access is disabled. */
  locked: boolean
  reason?: string | null
}

export interface ProvidersResponse {
  providers: ProviderInfo[]
  paid_enabled: boolean
}

/** Cookie auth: every request must carry the session cookie. */
const withCreds: RequestInit = { credentials: 'same-origin' }

/**
 * Every API call goes through here so the CSRF header is never forgotten.
 * The backend rejects state-changing browser requests without it
 * (backend/app/middleware/csrf.py).
 */
function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  headers.set('X-Insite-CSRF', '1')
  return fetch(input, { ...withCreds, ...init, headers })
}

/** FastAPI returns errors as {detail: string}. Pull that out when present. */
async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body?.detail === 'string') return body.detail
  } catch {
    // non-JSON error body; fall through to the status line
  }
  return `Request failed with status ${res.status}`
}

// Vite proxies /api to the FastAPI server on :8000 (see vite.config.ts).

export async function fetchProviders(): Promise<ProvidersResponse> {
  const res = await apiFetch('/api/providers', { ...withCreds })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function fetchFutureOfWork(params: {
  industry: string
  jobTitle?: string
  provider?: string
  signal?: AbortSignal
}): Promise<FutureOfWorkResult> {
  const res = await apiFetch('/api/future-of-work', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: params.signal,
    body: JSON.stringify({
      industry: params.industry,
      job_title: params.jobTitle || undefined,
      provider: params.provider || undefined,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}


// ---------------------------------------------------------------------------
// Career pathway
// ---------------------------------------------------------------------------

export interface WageInfo {
  annual_median?: number | null
  annual_mean?: number | null
  employment?: number | null
  year?: string | null
  area?: string | null
  source?: string | null
}

export type Readiness = 'ready' | 'stretch' | 'long-term'

export interface OccupationInfo {
  code: string
  title: string
  description: string
  skills: string[]
  job_zone?: number | null
  wage?: WageInfo | null
  /** Model-written guidance, joined onto the facts by SOC code. */
  rationale?: string | null
  readiness?: Readiness | null
  steps: string[]
  /** Target minus current BLS median. */
  pay_change?: number | null
  /** O*NET Job Zone in plain words. */
  training?: string | null
  skill_gaps?: SkillGap[]
  links?: LearningLink[]
}

export interface LearningLink {
  label: string
  url: string
  source: string
}

export interface NarrativeInfo {
  summary: string
  skill_gaps: string[]
  risks: string[]
  provider: string
  provider_label: string
}

export interface EmployerInfo {
  name: string
  postings: number
  average_salary?: number | null
}

export interface SalaryBandInfo {
  lower: number
  upper?: number | null
  count: number
}

export interface HiringInfo {
  query: string
  total_postings?: number | null
  top_employers: EmployerInfo[]
  salary_distribution: SalaryBandInfo[]
  salary_history: Record<string, number>
}

export interface DataSourceInfo {
  capability: string
  name: string
  label: string
  /** False means this section is scaffolding, not measured data. */
  live: boolean
  reason?: string | null
  signup_url?: string | null
}

export interface SkillGap {
  skill: string
  gap: number
}

export interface TransferableRole {
  code: string
  title: string
  description: string
  /** Cosine similarity of the 35-dimension O*NET skill profile. */
  similarity: number
  /** O*NET places this in a higher Job Zone than the current role. */
  requires_more_training: boolean
  /** Same rule as the pathway list's badge. */
  readiness?: Readiness | null
  job_zone?: number | null
  skill_gaps: SkillGap[]
  wage?: WageInfo | null
  training?: string | null
  links?: LearningLink[]
}

export interface CareerPathwayResult {
  current_role: string
  industry?: string | null
  horizon_months: number
  current_occupation: OccupationInfo
  pathways: OccupationInfo[]
  transferable: TransferableRole[]
  hiring?: HiringInfo | null
  data_sources: DataSourceInfo[]
  /** Null when the model was unavailable; the facts above remain valid. */
  narrative?: NarrativeInfo | null
  narrative_status: string
}

export interface CareerPathwayParams {
  currentRole: string
  industry?: string
  horizonMonths?: number
  location?: string
  includeNarrative?: boolean
  signal?: AbortSignal
}

async function postPathway(path: string, params: CareerPathwayParams): Promise<CareerPathwayResult> {
  const res = await apiFetch(path, {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: params.signal,
    body: JSON.stringify({
      current_role: params.currentRole,
      industry: params.industry || undefined,
      horizon_months: params.horizonMonths ?? 12,
      location: params.location || undefined,
      include_narrative: params.includeNarrative ?? true,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export const fetchCareerPathway = (params: CareerPathwayParams) =>
  postPathway('/api/career-pathway', params)

/** The same report with the model's summary: the slow part, asked for after
 *  the facts are already on screen. */
export const fetchPathwayNarrative = (params: CareerPathwayParams) =>
  postPathway('/api/career-pathway/narrative', params)


// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface AuthUser {
  id: string
  email: string
  full_name?: string | null
  auth_provider: string
  retention_until?: string | null
}

export async function register(params: {
  email: string
  password: string
  fullName?: string
  acceptTerms: boolean
  inviteCode?: string
}): Promise<AuthUser> {
  const res = await apiFetch('/api/auth/register', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email: params.email,
      password: params.password,
      full_name: params.fullName || undefined,
      accept_terms: params.acceptTerms,
      invite_code: params.inviteCode || undefined,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function login(email: string, password: string): Promise<AuthUser> {
  const res = await apiFetch('/api/auth/login', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function logout(): Promise<void> {
  await apiFetch('/api/auth/logout', { ...withCreds, method: 'POST' })
}

/** Returns null when not signed in, rather than throwing. */
export async function fetchMe(): Promise<AuthUser | null> {
  const res = await apiFetch('/api/auth/me', { ...withCreds })
  if (res.status === 401) return null
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function exportMyData(): Promise<unknown> {
  const res = await apiFetch('/api/me/export', { ...withCreds })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function eraseMyAccount(): Promise<void> {
  const res = await apiFetch('/api/me', { ...withCreds, method: 'DELETE' })
  if (!res.ok) throw new Error(await readError(res))
}

// ---------------------------------------------------------------------------
// Applicant portal
// ---------------------------------------------------------------------------

export type ApplicationStatus =
  | 'draft' | 'submitted' | 'in_review' | 'interview'
  | 'offer' | 'rejected' | 'withdrawn'

export interface ApplicationEvent {
  from_status?: string | null
  to_status: string
  note?: string | null
  /** This entry reverses the previous change (a misclick fix). */
  is_undo?: boolean
  occurred_at: string
}

export interface Application {
  id: string
  position_title: string
  status: ApplicationStatus
  cover_letter?: string | null
  created_at: string
  submitted_at?: string | null
  events: ApplicationEvent[]
  company?: string | null
  job_location?: string | null
  job_url?: string | null
  fingerprint?: string | null
  source: string
  /** There is a previous status to go back to. */
  can_undo: boolean
}

/** Tabs on the Applications page; mirrors STATUS_GROUPS on the server. */
export type ApplicationGroup = 'all' | 'active' | 'interviewing' | 'offers' | 'closed'

export interface ApplicationPage {
  items: Application[]
  total: number
  counts: Record<ApplicationGroup, number>
}

export interface Profile {
  current_role?: string | null
  industry?: string | null
  years_experience?: number | null
  location?: string | null
  skills: string[]
  summary?: string | null
  updated_at?: string | null
}

async function getJson<T>(url: string): Promise<T> {
  const res = await apiFetch(url, { ...withCreds })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export function fetchMyApplications(params: {
  group?: ApplicationGroup
  q?: string
  sort?: 'updated' | 'added'
  limit?: number
  offset?: number
} = {}): Promise<ApplicationPage> {
  const qs = new URLSearchParams()
  if (params.group && params.group !== 'all') qs.set('group', params.group)
  if (params.q?.trim()) qs.set('q', params.q.trim())
  if (params.sort) qs.set('sort', params.sort)
  if (params.limit) qs.set('limit', String(params.limit))
  if (params.offset) qs.set('offset', String(params.offset))
  const query = qs.toString()
  return getJson<ApplicationPage>(`/api/applications${query ? `?${query}` : ''}`)
}

/** Go back to the previous status. Recorded in the timeline, not erased. */
export async function undoApplicationStatus(id: string): Promise<Application> {
  const res = await apiFetch(`/api/applications/${id}/undo`, { ...withCreds, method: 'POST' })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

export async function removeApplication(id: string): Promise<void> {
  const res = await apiFetch(`/api/applications/${id}`, { ...withCreds, method: 'DELETE' })
  if (!res.ok) throw new Error(await readError(res))
}

export const fetchProfile = () => getJson<Profile>('/api/me/profile')

export async function saveProfile(p: Profile): Promise<Profile> {
  const res = await apiFetch('/api/me/profile', {
    ...withCreds,
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_role: p.current_role || null,
      industry: p.industry || null,
      years_experience: p.years_experience ?? null,
      location: p.location || null,
      skills: p.skills,
      summary: p.summary || null,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}



export async function updateApplicationStatus(
  id: string,
  status: ApplicationStatus,
  note?: string,
): Promise<Application> {
  const res = await apiFetch(`/api/applications/${id}/status`, {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status, note: note || null }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}


export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<void> {
  const res = await apiFetch('/api/auth/change-password', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
}


export async function requestPasswordReset(email: string): Promise<string> {
  const res = await apiFetch('/api/auth/forgot-password', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return (await res.json()).detail as string
}

export async function resetPassword(token: string, newPassword: string): Promise<void> {
  const res = await apiFetch('/api/auth/reset-password', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ token, new_password: newPassword }),
  })
  if (!res.ok) throw new Error(await readError(res))
}


// ---------------------------------------------------------------------------
// Job search (honest provenance)
// ---------------------------------------------------------------------------

export type SalarySource = 'stated' | 'estimated' | 'absent'
export type RemoteClaim = 'remote' | 'conflicted' | 'onsite' | 'unknown'

export interface JobPosting {
  id: string
  title: string
  company?: string | null
  location?: string | null
  url: string
  created?: string | null
  contract_time?: string | null
  salary_min?: number | null
  salary_max?: number | null
  /** How the salary was obtained. Never hidden from the user. */
  salary_source: SalarySource
  remote_claim: RemoteClaim
  remote_note?: string | null
  /** Identical adverts share a fingerprint. */
  fingerprint: string
  /** How many identical adverts this row stands for. */
  duplicate_count: number
  duplicate_locations: string[]
  /** When WE first saw this text, regardless of its claimed post date. */
  first_seen?: string | null
  /** Seen circulating materially earlier than the advert claims. */
  is_repost: boolean
}

export interface JobSearchResponse {
  postings: JobPosting[]
  total_available?: number | null
  excluded_estimated_salary: number
  excluded_no_salary: number
  excluded_not_remote: number
  excluded_below_salary: number
  collapsed_duplicates: number
  locations_searched: string[]
  failed_locations: string[]
  /** With a salary floor: board-ESTIMATED pay at or above it, kept apart. */
  estimated_matches: JobPosting[]
  pages_fetched: number
}

/** Adzuna takes one place per query; the backend runs up to this many. */
export const MAX_JOB_LOCATIONS = 3

export async function searchJobs(params: {
  q: string
  where?: string[]
  salaryMin?: number
  requireStatedSalary?: boolean
  remoteOnly?: boolean
  includeConflictedRemote?: boolean
  maxDaysOld?: number
  signal?: AbortSignal
}): Promise<JobSearchResponse> {
  const qs = new URLSearchParams({ q: params.q })
  for (const place of params.where ?? []) qs.append('where', place)
  if (params.salaryMin) qs.set('salary_min', String(params.salaryMin))
  if (params.requireStatedSalary) qs.set('require_stated_salary', 'true')
  if (params.remoteOnly) qs.set('remote_only', 'true')
  if (params.includeConflictedRemote) qs.set('include_conflicted_remote', 'true')
  if (params.maxDaysOld) qs.set('max_days_old', String(params.maxDaysOld))

  const res = await apiFetch(`/api/jobs/search?${qs}`, { ...withCreds, signal: params.signal })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}


/** Record that you applied to a job found through search. */
export async function trackJob(job: {
  fingerprint: string
  title: string
  company?: string | null
  location?: string | null
  url?: string | null
  externalId?: string
  salaryMin?: number | null
  salaryMax?: number | null
  applied?: boolean
}): Promise<Application> {
  const res = await apiFetch('/api/applications/track', {
    ...withCreds,
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fingerprint: job.fingerprint,
      title: job.title,
      company: job.company || null,
      location: job.location || null,
      url: job.url || null,
      external_id: job.externalId || null,
      salary_min: job.salaryMin ?? null,
      salary_max: job.salaryMax ?? null,
      applied: job.applied ?? true,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return res.json()
}

/** Fingerprints already applied to, for marking search results. */
export async function fetchTrackedFingerprints(): Promise<Set<string>> {
  const res = await apiFetch('/api/applications/tracked', { ...withCreds })
  if (!res.ok) throw new Error(await readError(res))
  const body = (await res.json()) as { fingerprints: string[] }
  return new Set(body.fingerprints)
}
