import { useState } from 'react'
import type { FormEvent } from 'react'
import { Check, KeyRound, Loader2 } from 'lucide-react'
import { changePassword } from '../lib/api'

const MIN = 12

export default function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setError(null)
    setDone(false)

    // Check the confirmation here; everything else is the server's call so
    // the rules can't drift between client and API.
    if (next !== confirm) {
      setError('New passwords do not match.')
      return
    }

    setBusy(true)
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setDone(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not change password')
    } finally {
      setBusy(false)
    }
  }

  const field =
    'w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition'

  return (
    <section className="bg-white border border-slate-200 rounded-xl p-6 mt-4">
      <h2 className="font-semibold text-slate-900 flex items-center gap-2">
        <KeyRound className="w-4 h-4 text-slate-400" /> Change password
      </h2>
      <p className="text-sm text-slate-500 mt-1">
        Changing this signs you out on every other device.
      </p>

      <form onSubmit={submit} className="mt-4 space-y-3 max-w-md">
        <div>
          <label htmlFor="cur" className="block text-sm font-medium text-slate-700 mb-1">
            Current password
          </label>
          <input
            id="cur"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            className={field}
            required
          />
        </div>
        <div>
          <label htmlFor="new" className="block text-sm font-medium text-slate-700 mb-1">
            New password
          </label>
          <input
            id="new"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            className={field}
            placeholder={`At least ${MIN} characters`}
            required
          />
        </div>
        <div>
          <label htmlFor="conf" className="block text-sm font-medium text-slate-700 mb-1">
            Confirm new password
          </label>
          <input
            id="conf"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            className={field}
            required
          />
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-2 bg-indigo-600 text-white px-5 py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition"
          >
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Update password
          </button>
          {done && (
            <span className="inline-flex items-center gap-1 text-sm text-emerald-700">
              <Check className="w-4 h-4" /> Password updated
            </span>
          )}
        </div>
      </form>
    </section>
  )
}
