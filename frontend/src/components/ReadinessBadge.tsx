import type { Readiness } from '../lib/api'

const READINESS_STYLE: Record<Readiness, { label: string; cls: string }> = {
  ready: { label: 'Ready now', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
  stretch: { label: 'Stretch', cls: 'bg-amber-50 text-amber-700 border-amber-200' },
  'long-term': { label: 'Longer term', cls: 'bg-slate-100 text-slate-600 border-slate-200' },
}

/** One readiness vocabulary for every list on the pathway page. */
export default function ReadinessBadge({ readiness }: { readiness?: Readiness | null }) {
  if (!readiness) return null
  const style = READINESS_STYLE[readiness]
  if (!style) return null
  return (
    <span className={`shrink-0 text-xs px-2 py-0.5 rounded-full border font-medium ${style.cls}`}
      title="From O*NET: the training level this role needs and how far its skill levels are above yours. A guide, not a verdict.">
      {style.label}
    </span>
  )
}
