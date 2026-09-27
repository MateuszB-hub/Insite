import { useRef, useState } from 'react'
import { FileUp, Loader2, ShieldCheck } from 'lucide-react'
import { uploadResume, type ResumeSuggestion } from '../lib/api'

/**
 * "Fill in from your résumé": every job site has it, and typing a profile by
 * hand is where people give up. The PDF is read by Insite's own model and
 * thrown away; the result only fills the form below, for review.
 */
export default function ResumeImport({ onSuggestion }: {
  onSuggestion: (s: ResumeSuggestion) => { filled: number; offered: number }
}) {
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [report, setReport] = useState<string | null>(null)

  const read = async (file: File | undefined) => {
    if (!file) return
    setBusy(true)
    setError(null)
    setReport(null)
    try {
      const s = await uploadResume(file)
      const { filled, offered } = onSuggestion(s)
      const dropped = Object.values(s.dropped ?? {}).reduce((a, b) => a + b, 0)
      const parts = [
        filled ? `Filled in ${filled} field${filled === 1 ? '' : 's'}` : 'Nothing new to fill in',
        offered ? `${offered} suggestion${offered === 1 ? '' : 's'} for fields you'd already filled` : '',
        dropped ? `left out ${dropped} item${dropped === 1 ? '' : 's'} your résumé doesn't actually mention` : '',
      ].filter(Boolean)
      setReport(`${parts.join('; ')}. Nothing is saved yet: check it below, then press Save profile.`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Your résumé could not be read.')
    } finally {
      setBusy(false)
      if (input.current) input.current.value = ''
    }
  }

  return (
    <section aria-labelledby="resume-import" data-testid="resume-import"
      className="bg-gradient-to-r from-indigo-50 to-purple-50 border border-indigo-100 rounded-xl p-5 mb-4">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 id="resume-import" className="font-semibold text-indigo-900">Fill in from your résumé</h2>
          <p className="text-sm text-slate-600 mt-1">
            Upload a PDF and the form below fills itself in. A LinkedIn profile works too:
            on LinkedIn, open your profile, click <span className="font-medium">More</span>, then{' '}
            <span className="font-medium">Save to PDF</span>.
          </p>
          <p className="text-xs text-slate-500 mt-2 flex items-start gap-1.5">
            <ShieldCheck className="w-4 h-4 shrink-0 text-emerald-600" />
            Read by Insite's own AI model on Insite's own computer, then discarded: the file
            isn't stored and nothing is sent to an outside AI company.
          </p>
        </div>
        <label className={`shrink-0 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium cursor-pointer ${
          busy ? 'bg-slate-200 text-slate-500 cursor-wait' : 'bg-indigo-600 text-white hover:bg-indigo-700'}`}>
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <FileUp className="w-4 h-4" />}
          {busy ? 'Reading…' : 'Upload résumé (PDF)'}
          <input ref={input} type="file" accept="application/pdf,.pdf" className="sr-only"
            disabled={busy} aria-label="Upload résumé PDF"
            onChange={(e) => read(e.target.files?.[0])} />
        </label>
      </div>
      {busy && (
        <p className="text-sm text-indigo-800 mt-3">Reading your résumé. This takes about 30 seconds, or a minute or two for a long one.</p>
      )}
      {report && <p className="text-sm text-slate-700 mt-3" data-testid="resume-report">{report}</p>}
      {error && <p className="text-sm text-red-700 mt-3" role="alert">{error}</p>}
    </section>
  )
}
