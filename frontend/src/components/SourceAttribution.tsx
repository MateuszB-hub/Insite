import type { DataSourceInfo } from '../lib/api'

/**
 * Required credit for the data sources actually in use.
 *
 * Only live sources are credited. Claiming to incorporate O*NET data while
 * running on the offline fallback would be inaccurate, so the notice appears
 * exactly when the source does.
 *
 * The O*NET wording is verbatim from USDOL/ETA and must not be reworded --
 * it names their trademark. The BLS and Adzuna lines are ordinary source
 * credit; check their current terms before launch in case they mandate
 * specific phrasing or a backlink.
 */
const CREDITS: Record<string, { text: string; href?: string }> = {
  onet: {
    text:
      'This site incorporates information from O*NET Web Services by the ' +
      'U.S. Department of Labor, Employment and Training Administration ' +
      '(USDOL/ETA). O*NET® is a trademark of USDOL/ETA.',
    href: 'https://services.onetcenter.org/',
  },
  bls: {
    text:
      'Wage data from the U.S. Bureau of Labor Statistics, Occupational ' +
      'Employment and Wage Statistics (OEWS).',
    href: 'https://www.bls.gov/oes/',
  },
  adzuna: {
    text: 'Job posting and salary data provided by Adzuna.',
    href: 'https://www.adzuna.com/',
  },
}

export default function SourceAttribution({ sources }: { sources: DataSourceInfo[] }) {
  const live = sources.filter((s) => s.live && CREDITS[s.name])
  if (live.length === 0) return null

  return (
    <footer className="mt-8 pt-5 border-t border-slate-200">
      <h2 className="text-xs font-medium text-slate-500 mb-2">Data sources</h2>
      <ul className="space-y-1.5">
        {live.map((s) => {
          const credit = CREDITS[s.name]
          return (
            <li key={s.name} className="text-xs text-slate-500 leading-relaxed">
              {credit.href ? (
                <a
                  href={credit.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="hover:text-slate-700 hover:underline"
                >
                  {credit.text}
                </a>
              ) : (
                credit.text
              )}
            </li>
          )
        })}
      </ul>
    </footer>
  )
}
