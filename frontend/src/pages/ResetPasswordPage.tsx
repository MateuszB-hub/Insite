import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Check, KeyRound, Loader2 } from 'lucide-react'
import { resetPassword } from '../lib/api'

const MIN = 12

export default function ResetPasswordPage() {
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''

  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setError(null)
    if (next !== confirm) {
      setError('Passwords do not match.')
      return
    }
    setBusy(true)
    try {
      await resetPassword(token, next)
      setDone(true)
      setTimeout(() => navigate('/login', { replace: true }), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not reset password')
    } finally {
      setBusy(false)
    }
  }

  const field =
    'w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition'

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <p className="text-4xl font-bold text-white tracking-tight">
            <span className="text-indigo-400">In</span>site
          </p>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl p-8">
          {!token ? (
            <>
              <h1 className="text-xl font-semibold text-slate-900 mb-2">Link incomplete</h1>
              <p className="text-sm text-slate-600">
                This reset link is missing its token. Request a new one.
              </p>
              <Link to="/forgot-password" className="text-indigo-600 hover:underline text-sm mt-4 inline-block">
                Request a new link
              </Link>
            </>
          ) : done ? (
            <>
              <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center mb-4">
                <Check className="w-6 h-6 text-emerald-600" />
              </div>
              <h1 className="text-xl font-semibold text-slate-900 mb-2">Password updated</h1>
              <p className="text-sm text-slate-600">
                You've been signed out everywhere. Taking you to sign in…
              </p>
            </>
          ) : (
            <>
              <h1 className="text-xl font-semibold text-slate-900 mb-1">Set a new password</h1>
              <p className="text-sm text-slate-500 mb-6">
                This signs you out on every device.
              </p>
              <form onSubmit={submit} className="space-y-4">
                <div>
                  <label htmlFor="new" className="block text-sm font-medium text-slate-700 mb-1">
                    New password
                  </label>
                  <input
                    id="new" type="password" required autoComplete="new-password"
                    value={next} onChange={(e) => setNext(e.target.value)}
                    placeholder={`At least ${MIN} characters`} className={field}
                  />
                </div>
                <div>
                  <label htmlFor="conf" className="block text-sm font-medium text-slate-700 mb-1">
                    Confirm password
                  </label>
                  <input
                    id="conf" type="password" required autoComplete="new-password"
                    value={confirm} onChange={(e) => setConfirm(e.target.value)}
                    className={field}
                  />
                </div>
                {error && <p className="text-sm text-red-700">{error}</p>}
                <button
                  type="submit" disabled={busy}
                  className="w-full flex items-center justify-center gap-2 bg-indigo-600 text-white py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition"
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <KeyRound className="w-4 h-4" />}
                  Update password
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
