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

/** How old the advert says it is. Past a week it is often already filled. */
export function PostedAgo({ created }: { created?: string | null }) {
  if (!created) return null
  const days = Math.floor((Date.now() - new Date(created).getTime()) / 86_400_000)
  if (Number.isNaN(days) || days < 0) return null
  const label = days === 0 ? 'Posted today' : days === 1 ? 'Posted yesterday' : `Posted ${days} days ago`
  return (
    <span className={`inline-flex items-center gap-1 ${days > 7 ? 'text-amber-700' : ''}`}
      title={days > 7 ? 'Older adverts are often already filled.' : undefined}>
      <Clock className="w-3.5 h-3.5" /> {label}
    </span>
  )
}
