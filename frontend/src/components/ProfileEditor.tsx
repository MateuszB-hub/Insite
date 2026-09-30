import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Download, Loader2, TriangleAlert } from 'lucide-react'
import {
  eraseMyAccount, exportMyData, fetchProfile, saveProfile,
  type Profile, type ResumeField, type ResumeSuggestion,
} from '../lib/api'
import { useAuth } from '../auth/AuthContext'
import ChangePassword from './ChangePassword'
import ResumeImport from './ResumeImport'
import { useNavigate } from 'react-router-dom'

const EMPTY: Profile = { skills: [] }

type Scalar = 'current_role' | 'location' | 'years_experience' | 'industry' | 'summary'
const SCALARS: Scalar[] = ['current_role', 'location', 'years_experience', 'industry', 'summary']

const splitSkills = (text: string) => text.split(',').map((s) => s.trim()).filter(Boolean)
const splitLines = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean)

/** Where a filled-in value came from, next to the field's label. */
function FromResume({ source }: { source?: string }) {
  if (!source) return null
  const suggested = source === 'suggested'
  return (
    <span data-testid="from-resume"
      className={`ml-1.5 text-xs font-normal rounded px-1.5 py-0.5 ${
        suggested ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-700'}`}>
      {source === 'résumé' ? 'from your résumé' : suggested ? 'suggested from your résumé, check it' : source}
    </span>
  )
}

/** For a field already filled in: offer the résumé's value, never overwrite. */
function Offer({ label, onUse }: { label: string; onUse: () => void }) {
  return (
    <p className="text-xs text-slate-600 mt-1" data-testid="resume-offer">
      Your résumé says <span className="font-medium">{label}</span>.{' '}
      <button type="button" onClick={onUse} className="text-indigo-600 hover:underline">Use it</button>
    </p>
  )
}

export default function ProfileEditor() {
  const navigate = useNavigate()
  const { user, logout } = useAuth()
  const [profile, setProfile] = useState<Profile>(EMPTY)
  const [skillsText, setSkillsText] = useState('')
  const [certsText, setCertsText] = useState('')
  //: Résumé import: which fields it filled (and from where), and what it
  //: offers for fields the person had already filled in.
  const [filled, setFilled] = useState<Partial<Record<ResumeField, string>>>({})
  const [offers, setOffers] = useState<Partial<Record<ResumeField, string | number | string[]>>>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmErase, setConfirmErase] = useState(false)

  useEffect(() => {
    fetchProfile()
      .then((p) => {
        setProfile(p)
        setSkillsText(p.skills.join(', '))
        setCertsText((p.certifications ?? []).join('\n'))
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    setSaved(false)
    try {
      const next = await saveProfile({
        ...profile,
        skills: splitSkills(skillsText),
        certifications: splitLines(certsText),
      })
      setProfile(next)
      setFilled({})
      setOffers({})
      setSaved(true)
      setTimeout(() => setSaved(false), 2500)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save')
    } finally {
      setSaving(false)
    }
  }

  /** Fill empty fields from the résumé; offer the rest. Returns counts. */
  const applyResume = (s: ResumeSuggestion) => {
    const nextProfile = { ...profile }
    const nextFilled: Partial<Record<ResumeField, string>> = {}
    const nextOffers: Partial<Record<ResumeField, string | number | string[]>> = {}
    for (const f of SCALARS) {
      const value = s.fields[f]
      if (value === null || value === undefined || value === '') continue
      const current = profile[f]
      if (current === null || current === undefined || current === '') {
        ;(nextProfile as Record<string, unknown>)[f] = value
        nextFilled[f] = s.sources[f] ?? 'résumé'
      } else if (String(current).trim().toLowerCase() !== String(value).trim().toLowerCase()) {
        nextOffers[f] = value
      }
    }
    for (const [f, text, split, set, join] of [
      ['skills', skillsText, splitSkills, setSkillsText, (v: string[]) => v.join(', ')],
      ['certifications', certsText, splitLines, setCertsText, (v: string[]) => v.join('\n')],
    ] as const) {
      const incoming = s.fields[f] ?? []
      if (!incoming.length) continue
      const have = split(text)
      if (!have.length) {
        set(join(incoming))
        nextFilled[f] = s.sources[f] ?? 'résumé'
      } else {
        const known = new Set(have.map((x) => x.toLowerCase()))
        const extra = incoming.filter((x) => !known.has(x.toLowerCase()))
        if (extra.length) nextOffers[f] = extra
      }
    }
    setProfile(nextProfile)
    setFilled(nextFilled)
    setOffers(nextOffers)
    setSaved(false)
    return { filled: Object.keys(nextFilled).length, offered: Object.keys(nextOffers).length }
  }

  const useOffer = (f: ResumeField) => {
    const value = offers[f]
    if (value === undefined) return
    if (f === 'skills' || f === 'certifications') {
      const list = value as string[]
      if (f === 'skills') setSkillsText((t) => [...splitSkills(t), ...list].join(', '))
      else setCertsText((t) => [...splitLines(t), ...list].join('\n'))
    } else {
      setProfile((p) => ({ ...p, [f]: value }))
    }
    setFilled((m) => ({ ...m, [f]: 'résumé' }))
    setOffers((m) => {
      const rest = { ...m }
      delete rest[f]
      return rest
    })
  }

  const offerFor = (f: ResumeField) => {
    const value = offers[f]
    if (value === undefined) return null
    const label = Array.isArray(value)
      ? `${value.length} more: ${value.slice(0, 4).join(', ')}${value.length > 4 ? '…' : ''}`
      : `"${value}"`
    return <Offer label={label} onUse={() => useOffer(f)} />
  }

  const doExport = async () => {
    const data = await exportMyData()
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'insite-my-data.json'
    a.click()
    URL.revokeObjectURL(url)
  }

  const doErase = async () => {
    await eraseMyAccount()
    await logout()
    navigate('/login', { replace: true })
  }

  if (loading) {
    return (
      <div className="p-8 flex items-center gap-2 text-slate-500">
        <Loader2 className="w-5 h-5 animate-spin" /> Loading…
      </div>
    )
  }

  const field = 'w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition'

  return (
    <div className="p-4 sm:p-8 max-w-3xl mx-auto">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-slate-900">Your Profile</h1>
        <p className="text-slate-500 mt-1">
          Only you see this. Your role and location pick the jobs on Home and fill in
          Find Roles and Career Pathway for you; the rest is optional.
        </p>
      </header>

      <ResumeImport onSuggestion={applyResume} />

      <form onSubmit={submit} className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
        <div className="grid sm:grid-cols-2 gap-4">
          <div>
            <label htmlFor="role" className="block text-sm font-medium text-slate-700 mb-1">Current role<span className="ml-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 rounded px-1.5 py-0.5">Needed</span><FromResume source={filled.current_role} /></label>
            <input id="role" className={field} value={profile.current_role ?? ''}
              onChange={(e) => setProfile({ ...profile, current_role: e.target.value })}
              placeholder="Senior Backend Engineer" />
            <p className="text-xs text-slate-500 mt-1">Picks the jobs on Home and maps where your role leads.</p>
            {offerFor('current_role')}
          </div>
          <div>
            <label htmlFor="ind" className="block text-sm font-medium text-slate-700 mb-1">Industry<span className="ml-1.5 text-xs font-normal text-slate-600 bg-slate-100 rounded px-1.5 py-0.5">Nice to have</span><FromResume source={filled.industry} /></label>
            <input id="ind" className={field} value={profile.industry ?? ''}
              onChange={(e) => setProfile({ ...profile, industry: e.target.value })}
              placeholder="Fintech" />
            <p className="text-xs text-slate-500 mt-1">Filled in on Career Pathway.</p>
            {offerFor('industry')}
          </div>
          <div>
            <label htmlFor="yrs" className="block text-sm font-medium text-slate-700 mb-1">Years of experience<span className="ml-1.5 text-xs font-normal text-slate-600 bg-slate-100 rounded px-1.5 py-0.5">Nice to have</span><FromResume source={filled.years_experience} /></label>
            <input id="yrs" type="number" min={0} max={70} className={field}
              value={profile.years_experience ?? ''}
              onChange={(e) => setProfile({
                ...profile,
                years_experience: e.target.value === '' ? null : Number(e.target.value),
              })} />
            <p className="text-xs text-slate-500 mt-1">Kept with your profile; not used to pick jobs yet.</p>
            {offerFor('years_experience')}
          </div>
          <div>
            <label htmlFor="loc" className="block text-sm font-medium text-slate-700 mb-1">Location<span className="ml-1.5 text-xs font-medium text-indigo-700 bg-indigo-50 rounded px-1.5 py-0.5">Needed</span><FromResume source={filled.location} /></label>
            <input id="loc" className={field} value={profile.location ?? ''}
              onChange={(e) => setProfile({ ...profile, location: e.target.value })}
              placeholder="Chicago" />
            <p className="text-xs text-slate-500 mt-1">For jobs near you. Leave it blank to see jobs anywhere.</p>
            {offerFor('location')}
          </div>
        </div>

        <div>
          <label htmlFor="skills" className="block text-sm font-medium text-slate-700 mb-1">
            Skills <span className="text-slate-500 font-normal">(comma separated)</span><span className="ml-1.5 text-xs font-normal text-slate-600 bg-slate-100 rounded px-1.5 py-0.5">Nice to have</span><FromResume source={filled.skills} />
          </label>
          <input id="skills" className={field} value={skillsText}
            onChange={(e) => setSkillsText(e.target.value)}
            placeholder="Python, Postgres, Distributed systems" />
          <p className="text-xs text-slate-500 mt-1">Kept with your profile; not used to pick jobs yet.</p>
          {offerFor('skills')}
        </div>

        <div>
          <label htmlFor="certs" className="block text-sm font-medium text-slate-700 mb-1">
            Certifications and licences <span className="text-slate-500 font-normal">(one per line)</span><span className="ml-1.5 text-xs font-normal text-slate-600 bg-slate-100 rounded px-1.5 py-0.5">Nice to have</span><FromResume source={filled.certifications} />
          </label>
          <textarea id="certs" rows={3} className={field} value={certsText}
            onChange={(e) => setCertsText(e.target.value)}
            placeholder={'BLS\nPMP'} />
          <p className="text-xs text-slate-500 mt-1">Kept with your profile; not used to pick jobs yet.</p>
          {offerFor('certifications')}
        </div>

        <div>
          <label htmlFor="sum" className="block text-sm font-medium text-slate-700 mb-1">Summary<span className="ml-1.5 text-xs font-normal text-slate-600 bg-slate-100 rounded px-1.5 py-0.5">Nice to have</span><FromResume source={filled.summary} /></label>
          <textarea id="sum" rows={4} className={field} value={profile.summary ?? ''}
            onChange={(e) => setProfile({ ...profile, summary: e.target.value })}
            placeholder="A short professional summary." />
          {offerFor('summary')}
        </div>

        {error && <p className="text-sm text-red-700">{error}</p>}

        <div className="flex items-center gap-3">
          <button type="submit" disabled={saving}
            className="inline-flex items-center gap-2 bg-indigo-600 text-white px-5 py-2.5 rounded-lg font-medium hover:bg-indigo-700 disabled:opacity-50 transition">
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
            Save profile
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-sm text-emerald-700">
              <Check className="w-4 h-4" /> Saved
            </span>
          )}
        </div>
      </form>

      <ChangePassword />

      {/* Data rights, surfaced rather than buried in a policy page. */}
      <section className="bg-white border border-slate-200 rounded-xl p-6 mt-4">
        <h2 className="font-semibold text-slate-900">Your data</h2>
        <p className="text-sm text-slate-500 mt-1">
          Signed in as {user?.email}.
          {profile.updated_at && ` Profile updated ${new Date(profile.updated_at).toLocaleDateString()}.`}
        </p>

        <div className="flex flex-wrap gap-3 mt-4">
          <button type="button" onClick={doExport}
            className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg border border-slate-300 text-slate-700 hover:bg-slate-50 transition">
            <Download className="w-4 h-4" /> Download my data
          </button>

          {!confirmErase ? (
            <button type="button" onClick={() => setConfirmErase(true)}
              className="inline-flex items-center gap-2 text-sm px-4 py-2 rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 transition">
              <TriangleAlert className="w-4 h-4" /> Delete my account and data
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <span className="text-sm text-rose-700">
                Permanently delete your account and everything in it: your profile,
                applications and their history? This can't be undone.
              </span>
              <button type="button" onClick={doErase}
                className="text-sm px-3 py-1.5 rounded-lg bg-rose-600 text-white font-medium hover:bg-rose-700 transition">
                Yes, delete
              </button>
              <button type="button" onClick={() => setConfirmErase(false)}
                className="text-sm px-3 py-1.5 rounded-lg border border-slate-300 text-slate-600 hover:bg-slate-50 transition">
                Cancel
              </button>
            </div>
          )}
        </div>
      </section>
    </div>
  )
}
