import { BadgeCheck, CircleHelp, Clock, TriangleAlert } from 'lucide-react'
import type { JobPosting } from '../lib/api'

/** Job-card pieces shared by Find Roles and Home, so a job reads the same everywhere. */

const money = (n?: number | null) =>
  n == null ? null : `$${Math.round(n).toLocaleString()}`

/** Salary provenance, stated plainly rather than buried. */
export function SalaryLine({ job }: { job: JobPosting }) {
  const range =
    job.salary_min && job.salary_max && job.salary_min !== job.salary_max
      ? `${money(job.salary_min)}–${money(job.salary_max)}`
      : money(job.salary_min ?? job.salary_max)

  if (job.salary_source === 'absent' || !range) {
    return (
      <span className="inline-flex items-center gap-1 text-sm text-slate-500">
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
        {job.estimate_low != null && job.estimate_high != null && (
          <span className="text-xs text-amber-800" data-testid="estimate-spread">
            · the board estimated {money(job.estimate_low)}–{money(job.estimate_high)} for copies of this same advert
          </span>
        )}
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

/**
 * What the pay is worth where the person lives. Mentor: "100k is basically
 * 70k here." An average of all living costs, from official data; housing
 * is most of it, and taxes aren't in it -- both said on hover.
 */
export function LivingCostLine({ job }: { job: JobPosting }) {
  const c = job.living_cost
  if (!c) return null
  const worth = c.equivalent_min === c.equivalent_max
    ? money(c.equivalent_min)
    : `${money(c.equivalent_min)}–${money(c.equivalent_max)}`
  const there = c.job_level === 'state' ? `${c.job_area} on average` : c.job_area
  const direction = c.difference_pct > 0 ? 'higher' : 'lower'
  const housing = c.housing_difference_pct != null && Math.abs(c.housing_difference_pct) >= 5
    ? `; housing ${Math.abs(c.housing_difference_pct)}% ${c.housing_difference_pct > 0 ? 'higher' : 'lower'}`
    : ''
  return (
    <p className="text-xs text-slate-600 mt-1" data-testid="living-cost"
      title={`${c.source}. An average of all living costs; taxes aren't included. `
        + `Your area: ${c.home_area}${c.home_level === 'state' ? ' (state average)' : ''}.`}>
      ≈ <span className="font-medium text-slate-800">{worth} in {c.home_area} terms</span>
      {' '}· living costs {Math.abs(c.difference_pct)}% {direction} in {there}{housing}
    </p>
  )
}

/** How old the advert says it is. Past a week it is often already filled. */
export function PostedAgo({ created }: { created?: string | null }) {
  if (!created) return null
  const ms = Date.now() - new Date(created).getTime()
  const days = Math.floor(ms / 86_400_000)
  if (Number.isNaN(days) || days < 0) return null
  const hours = Math.floor(ms / 3_600_000)
  // Under a day, hours matter: that's what "Past 24 hours" is for.
  const label = hours < 1 ? 'Posted within the hour'
    : hours < 24 ? `Posted ${hours} hour${hours === 1 ? '' : 's'} ago`
    : days === 1 ? 'Posted yesterday' : `Posted ${days} days ago`
  return (
    <span className={`inline-flex items-center gap-1 ${days > 7 ? 'text-amber-700' : ''}`}
      title={days > 7 ? 'Older adverts are often already filled.' : undefined}>
      <Clock className="w-3.5 h-3.5" /> {label}
    </span>
  )
}
