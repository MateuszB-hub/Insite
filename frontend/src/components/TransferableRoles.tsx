import { ArrowUpRight } from 'lucide-react'
import type { TransferableRole } from '../lib/api'
import MoveFacts from './MoveFacts'
import ReadinessBadge from './ReadinessBadge'

/** Sign goes outside the currency symbol: -$17,200, not $-17,200. */
const money = (n?: number | null) => {
  if (n == null) return null
  const sign = n < 0 ? '-' : ''
  return `${sign}$${Math.abs(Math.round(n)).toLocaleString()}`
}

/**
 * "What else do my current skills apply to?"
 *
 * Distinct from the pathway list above it, which answers "what is the next
 * rung up". Most people are not choosing between two offers; they want to
 * know where else they already fit. Matches come from O*NET skill profiles,
 * and each carries the same readiness badge as the pathway list above.
 */
export default function TransferableRoles({
  roles,
  currentPay,
}: {
  roles: TransferableRole[]
  currentPay?: number | null
}) {
  if (roles.length === 0) return null

  return (
    <section className="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
      <h2 className="text-lg font-semibold text-slate-900">
        Your skills also apply to
      </h2>
      <p className="text-sm text-slate-500 mt-1 mb-4">
        Occupations with a similar skill profile, from O*NET. Pay is the
        national median.
      </p>

      <div className="grid gap-3">
        {roles.map((role) => {
          const pay = role.wage?.annual_median
          const delta =
            pay != null && currentPay != null ? pay - currentPay : null

          return (
            <article
              key={role.code}
              className="border border-slate-200 rounded-lg p-4 hover:border-indigo-200 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h3 className="font-medium text-slate-900">
                    {role.title}
                    <span className="ml-2 text-xs font-mono text-slate-400">
                      {role.code}
                    </span>
                  </h3>

                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-sm">
                    {pay != null && (
                      <span className="font-semibold text-slate-800">{money(pay)}</span>
                    )}
                    {delta != null && delta !== 0 && (
                      <span
                        className={
                          delta > 0
                            ? 'text-emerald-700 inline-flex items-center gap-0.5'
                            : 'text-slate-500'
                        }
                      >
                        {delta > 0 && <ArrowUpRight className="w-3.5 h-3.5" />}
                        {delta > 0 ? '+' : ''}
                        {money(delta)} vs now
                      </span>
                    )}
                  </div>
                </div>

                <ReadinessBadge readiness={role.readiness} />
              </div>

              <MoveFacts training={role.training} gaps={role.skill_gaps} links={role.links} />
            </article>
          )
        })}
      </div>
    </section>
  )
}
