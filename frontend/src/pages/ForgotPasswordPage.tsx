import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Loader2, Mail } from 'lucide-react'
import { requestPasswordReset } from '../lib/api'

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      // The server returns the same acknowledgement whether or not the
      // address exists, so we show exactly what it says.
      setSent(await requestPasswordReset(email))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-indigo-950 to-slate-900 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <p className="text-4xl font-bold text-white tracking-tight">
            <span className="text-indigo-400">In</span>site
          </p>
          <p className="text-slate-400 mt-2">Career planning for any field</p>
        </div>

        <div className="bg-white rounded-2xl shadow-2xl p-8">
          {sent ? (
            <>
              <div className="w-12 h-12 bg-indigo-50 rounded-full flex items-center justify-center mb-4">
                <Mail className="w-6 h-6 text-indigo-500" />
              </div>
              <h1 className="text-xl font-semibold text-slate-900 mb-2">Check your inbox</h1>
              <p className="text-sm text-slate-600">{sent}</p>
              <p className="text-xs text-slate-400 mt-3">
                The link expires in 30 minutes and can only be used once.
              </p>
            </>
          ) : (
            <>
              <h1 className="text-xl font-semibold text-slate-900 mb-1">Reset your password</h1>
              <p className="text-sm text-slate-500 mb-6">
                We'll email you a link to set a new one.
              </p>
              <form onSubmit={submit} className="space-y-4">
                <div>
                  <label htmlFor="email" className="block text-sm font-medium text-slate-700 mb-1">
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    required
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition"
                  />
                </div>
                {error && <p className="text-sm text-red-700">{error}</p>}
                <button
                  type="submit"
                  disabled={busy}
                  className="w-full flex items-center justify-center gap-2 bg-indigo-600 text-white py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition"
                >
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}
                  Send reset link
                </button>
              </form>
            </>
          )}

          <Link
            to="/login"
            className="mt-6 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-800"
          >
            <ArrowLeft className="w-4 h-4" /> Back to sign in
          </Link>
        </div>
      </div>
    </div>
  )
}
