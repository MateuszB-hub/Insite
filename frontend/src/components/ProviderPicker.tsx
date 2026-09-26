import { Cpu, Lock, Sparkles, CircleAlert } from 'lucide-react'
import type { ProviderInfo } from '../lib/api'

interface Props {
  providers: ProviderInfo[]
  paidEnabled: boolean
  /** undefined = let the server pick (auto). */
  selected?: string
  onSelect: (name: string | undefined) => void
  disabled?: boolean
}

function tierIcon(tier: ProviderInfo['tier']) {
  if (tier === 'paid') return <Sparkles className="w-3.5 h-3.5" />
  return <Cpu className="w-3.5 h-3.5" />
}

/**
 * Lets the applicant choose which model answers. Local models are the default;
 * paid providers render locked until the server reports paid access enabled.
 */
export default function ProviderPicker({
  providers,
  paidEnabled,
  selected,
  onSelect,
  disabled,
}: Props) {
  if (providers.length === 0) return null

  const options: { key: string | undefined; label: string; info?: ProviderInfo }[] = [
    { key: undefined, label: 'Auto' },
    ...providers.map((p) => ({ key: p.name, label: p.label, info: p })),
  ]

  return (
    <div>
      <span className="block text-sm font-medium text-slate-700 mb-2">Analysis engine</span>
      <div className="flex flex-wrap gap-2">
        {options.map((opt) => {
          const info = opt.info
          const isLocked = info?.locked ?? false
          const isUnavailable = info ? !info.available : false
          const isSelected = selected === opt.key
          const isDisabled = disabled || isLocked || isUnavailable

          return (
            <button
              key={opt.key ?? 'auto'}
              type="button"
              disabled={isDisabled}
              onClick={() => onSelect(opt.key)}
              title={info?.reason ?? undefined}
              className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium border transition-colors ${
                isSelected
                  ? 'bg-indigo-600 border-indigo-600 text-white'
                  : isDisabled
                    ? 'bg-slate-50 border-slate-200 text-slate-400 cursor-not-allowed'
                    : 'bg-white border-slate-300 text-slate-700 hover:border-indigo-400 hover:text-indigo-700'
              }`}
            >
              {info ? tierIcon(info.tier) : null}
              {opt.label}
              {isLocked && <Lock className="w-3 h-3" />}
              {!isLocked && isUnavailable && <CircleAlert className="w-3 h-3" />}
            </button>
          )
        })}
      </div>

      {!paidEnabled && providers.some((p) => p.tier === 'paid') && (
        <p className="text-xs text-slate-500 mt-2 flex items-center gap-1">
          <Lock className="w-3 h-3" />
          Premium engines are a paid upgrade. Runs locally and free by default.
        </p>
      )}
    </div>
  )
}
