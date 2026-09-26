/**
 * Proof-of-function for the candidate-side portal.
 *
 * No staff actor: this is one person managing their own job hunt. They browse
 * roles, keep a profile, apply, and record what happens as they hear back.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = 'http://localhost:5173'
const OUT = new URL('./output-portal/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const EMAIL = `candidate+${Date.now()}@example.com`
const PW = 'a candidate passphrase'
const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
// Wait for THIS search's response: the previous results stay on screen
// while the next search runs, so waiting for 'article' alone passes early.
const searchAndWait = async () => {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForSelector('article', { timeout: 60000 })
}
page.on('pageerror', e => errs.push(e.message))

console.log('\nInsite — candidate portal demo\n')

// register
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Test Candidate')
await page.fill('#email', EMAIL)
await page.fill('#password', PW)
await page.fill('#password-confirm', PW)
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })
check('registration signs the candidate in', true)

// the staff area is gone entirely
const nav = await page.locator('aside').innerText()
check('no hiring-team section in nav', !nav.includes('Candidate Review') && !nav.includes('HIRING TEAM'))
await page.goto(`${BASE}/staff`, { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
await page.goto(`${BASE}/positions`, { waitUntil: 'networkidle' })
await page.waitForTimeout(400)
check('removed /positions route falls through to the app',
  !(await page.locator('body').innerText()).includes('Open Roles'))

check('old /staff route no longer renders a review screen',
  !(await page.locator('body').innerText()).includes('Candidate Review'))

// profile
await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
await page.waitForSelector('#role', { state: 'visible', timeout: 15000 })
await page.fill('#role', 'Registered Nurse')
await page.fill('#skills', 'Patient care, Triage')
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })
check('profile saves', true)

// find a real job and track it
await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
await page.waitForSelector('#q', { state: 'visible', timeout: 15000 })
// tester's case: "software engineer", nationwide, $100k minimum used to
// show 2 jobs. Estimated pay above the floor now has its own labelled list.
await page.fill('#q', 'software engineer')
await page.fill('#sal', '100000')
await searchAndWait()
const stated = await page.locator('article[data-section="stated"]').count()
const estimated = await page.locator('article[data-section="estimated"]').count()
check('salary floor returns more than a couple of jobs', stated + estimated >= 5, `${stated} employer-stated + ${estimated} estimated`)
const firstCard = await page.locator('article').first().innerText()
check('cards show how recently they were posted', /Posted (today|yesterday|\d+ days ago)/.test(firstCard))
check('recent-only is the default', (await page.inputValue('#age')) === '7')
await page.screenshot({ path: `${OUT}/0-salary-floor.png`, fullPage: false })
await page.fill('#sal', '')

await page.fill('#q', 'registered nurse')
// several places: each becomes a removable tag, all searched at once
for (const place of ['Austin', 'Denver']) {
  await page.fill('#where', place)
  await page.press('#where', 'Enter')
}
const tags = await page.getByLabel('Selected locations').innerText()
check('places become tags', tags.includes('Austin') && tags.includes('Denver'), tags.replace(/\s+/g, ' '))
await searchAndWait()
const cities = (await page.locator('article').allInnerTexts()).join(' ')
check('results cover every place', /Austin|Travis/.test(cities) && /Denver/.test(cities))
await page.screenshot({ path: `${OUT}/0-two-cities.png`, fullPage: false })
const title = await page.locator('article h2').first().innerText()
await page.locator('button:has-text("Mark as applied")').first().click()
await page.waitForSelector('text=Already applied', { timeout: 20000 })
check('marks a real job as applied', true, title.slice(0, 40))

await page.goto(`${BASE}/applications`, { waitUntil: 'networkidle' })
await page.waitForSelector('article', { timeout: 15000 })
check('application recorded', (await page.locator('body').innerText()).includes(title.slice(0, 25)), title.slice(0, 40))
await page.screenshot({ path: `${OUT}/1-applications.png`, fullPage: true })

// self-report progress -- the candidate drives this, not a recruiter
await page.getByRole('button', { name: 'They responded' }).first().click()
await page.waitForSelector('text=In review', { timeout: 15000 })
await page.getByRole('button', { name: 'Got an interview' }).first().click()
await page.waitForSelector('text=Interview', { timeout: 15000 })
check('candidate self-reports progress', true, 'submitted → in review → interview')
await page.screenshot({ path: `${OUT}/2-self-reported.png`, fullPage: true })

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter(c => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
