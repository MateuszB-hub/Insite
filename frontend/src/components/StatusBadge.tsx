import type { ApplicationStatus } from '../lib/api'

const STYLES: Record<ApplicationStatus, { label: string; cls: string }> = {
  draft: { label: 'Draft', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
  submitted: { label: 'Submitted', cls: 'bg-blue-50 text-blue-700 border-blue-200' },
  in_review: { label: 'In review', cls: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
  interview: { label: 'Interview', cls: 'bg-violet-50 text-violet-700 border-violet-200' },
  offer: { label: 'Offer', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  rejected: { label: 'Not selected', cls: 'bg-rose-50 text-rose-700 border-rose-200' },
  withdrawn: { label: 'Withdrawn', cls: 'bg-slate-100 text-slate-500 border-slate-200' },
}

export default function StatusBadge({ status }: { status: ApplicationStatus }) {
  const s = STYLES[status] ?? STYLES.draft
  return (
    <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full border font-medium ${s.cls}`}>
      {s.label}
    </span>
  )
}
