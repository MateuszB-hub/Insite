import { BookOpen, ExternalLink, GraduationCap, Target } from 'lucide-react'
import type { LearningLink, SkillGap } from '../lib/api'

/** What the move takes: training, the skills to build, and where to learn. */
export default function MoveFacts({ training, gaps = [], links = [] }: {
  training?: string | null
  gaps?: SkillGap[]
  links?: LearningLink[]
}) {
  if (!training && gaps.length === 0 && links.length === 0) return null
  return (
    <div className="mt-3 space-y-1.5 text-sm">
      {training && (
        <p className="flex items-start gap-1.5 text-slate-600">
          <GraduationCap className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" />
          <span><span className="text-slate-500">Training:</span> {training}</span>
        </p>
      )}
      {gaps.length > 0 && (
        <p className="flex items-start gap-1.5 text-slate-600">
          <Target className="w-4 h-4 mt-0.5 shrink-0 text-slate-400" />
          <span>
            <span className="text-slate-500">Skills to build:</span>{' '}
            {gaps.map((g) => g.skill).join(', ')}
          </span>
        </p>
      )}
      {links.length > 0 && (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1" data-testid="learning-links">
          <BookOpen className="w-4 h-4 shrink-0 text-slate-400" />
          {links.map((l) => (
            <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer"
              title={l.source}
              className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-800 hover:underline">
              {l.label} <ExternalLink className="w-3 h-3" />
            </a>
          ))}
        </p>
      )}
    </div>
  )
}
