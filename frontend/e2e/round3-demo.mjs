/**
 * Mentor round 3 on Find Roles: a long specific title finds the job inside
 * it, hidden adverts can be shown with their reason, and places have a radius.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-round3/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))
console.log('\nInsite — mentor round 3 demo\n')

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Round Three')
await page.fill('#email', `round3+${Date.now()}@example.com`)
await page.fill('#password', 'a round three passphrase')
await page.fill('#password-confirm', 'a round three passphrase')
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

const search = async () => {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForTimeout(400)
}

await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
check('radius is off until there is a place', await page.locator('#distance').isDisabled())

// A long, specific title: nothing has every word, so the job inside it.
await page.fill('#q', 'VP EAC Compliance & Operational Risk Specialist')
await search()
const note = await page.getByTestId('broadened-note').innerText().catch(() => '')
check('a long title says what was searched instead', /compliance specialist/.test(note), note)
const jobs = await page.locator('article').count()
check('…and finds jobs', jobs > 0, `${jobs} shown`)
await page.screenshot({ path: `${OUT}/1-broadened.png`, fullPage: false })

// Hidden adverts, on request, each with its reason.
await page.fill('#q', 'qa lead')
await page.getByLabel('Only employer-stated salaries').check()
await search()
await page.getByRole('button', { name: /Show the \d+ hidden job/ }).click()
const reasons = await page.getByTestId('hidden-reason').allInnerTexts()
check('hidden jobs can be shown, each with its reason',
  reasons.length > 0 && reasons.every((r) => r.startsWith('Hidden: ')), reasons.slice(0, 2).join(' | '))
await page.screenshot({ path: `${OUT}/2-hidden.png`, fullPage: false })

// A title that means different work in different fields: narrow by what
// the advert says.
await page.getByLabel('Only employer-stated salaries').uncheck()
await page.fill('#mention', 'software')
const [withMention] = await Promise.all([
  page.waitForRequest((r) => r.url().includes('/api/jobs/search')),
  page.getByRole('button', { name: 'Search' }).click(),
])
await page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 })
await page.waitForTimeout(400)
check('"must also mention" goes with the search', new URL(withMention.url()).searchParams.get('mention') === 'software')
const matchNote = await page.getByTestId('match-note').innerText().catch(() => '')
check('…and the page says so', /"software" anywhere in the advert/.test(matchNote), matchNote)
await page.fill('#mention', '')

// Radius: enabled once a place is typed, and sent with the search.
await page.fill('#where', 'Austin, TX')
await page.keyboard.press('Escape')
await page.press('#where', 'Enter')
check('radius turns on with a place', !(await page.locator('#distance').isDisabled()))
await page.selectOption('#distance', '50')
const [req] = await Promise.all([
  page.waitForRequest((r) => r.url().includes('/api/jobs/search')),
  page.getByRole('button', { name: 'Search' }).click(),
])
check('the radius goes with the search', new URL(req.url()).searchParams.get('distance') === '50')
await page.waitForTimeout(3000)

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))
await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
