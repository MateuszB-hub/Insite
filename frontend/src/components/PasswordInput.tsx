import { useState } from 'react'
import { Eye, EyeOff } from 'lucide-react'

interface Props {
  id: string
  value: string
  onChange: (value: string) => void
  autoComplete: 'new-password' | 'current-password'
  placeholder?: string
  required?: boolean
  className?: string
}

/**
 * Password field with a show/hide toggle. Typing a long passphrase blind is
 * where most sign-up typos come from, so every password field uses this.
 */
export default function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  placeholder,
  required = true,
  className = 'w-full px-4 py-2.5 rounded-lg border border-slate-300 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition',
}: Props) {
  const [visible, setVisible] = useState(false)

  return (
    <div className="relative">
      <input
        id={id}
        type={visible ? 'text' : 'password'}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        // Never let the browser spellcheck or autocorrect a visible password.
        autoCapitalize="off"
        autoCorrect="off"
        spellCheck={false}
        placeholder={placeholder}
        className={`${className} pr-11`}
      />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        aria-pressed={visible}
        aria-controls={id}
        className="absolute inset-y-0 right-0 flex items-center px-3 text-slate-400 hover:text-slate-600"
      >
        {visible ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
      </button>
    </div>
  )
}
