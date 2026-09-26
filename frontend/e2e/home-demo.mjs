/**
 * Proof-of-function for the Home page a person lands on after signing in.
 *
 * Tester feedback: "ideally home dashboard or something too. Logging in to
 * just this is meh." Home walks a new person through getting started, picks
 * recent jobs from their profile, and sums up their applications.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-home/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const EMAIL = `home+${Date.now()}@example.com`
const PW = 'a home page passphrase'
const ROLE = 'Registered Nurse'
const PLACE = 'Chicago'
const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', e => errs.push(e.message))

console.log('\nInsite — home page demo\n')

// a brand-new person lands on Home, not straight in a search form
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Home Tester')
await page.fill('#email', EMAIL)
await page.fill('#password', PW)
await page.fill('#password-confirm', PW)
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })
await page.waitForSelector('text=Get started', { timeout: 15000 })
check('sign-up lands on Home', new URL(page.url()).pathname === '/home', new URL(page.url()).pathname)

const firstNav = (await page.locator('aside nav a').first().innerText()).trim()
check('Home is first in the nav', firstNav === 'Home', firstNav)

const started = await page.locator('section', { hasText: 'Get started' }).innerText()
check('first run shows Get started, nothing done', started.includes('0 of 3 done'))
check('picked jobs ask for a profile first',
  (await page.locator('body').innerText()).includes('Add your role'))
await page.screenshot({ path: `${OUT}/1-first-run.png`, fullPage: true })

// fill in the profile from the first step
await page.getByRole('link', { name: 'Fill in profile' }).click()
await page.waitForSelector('#role', { state: 'visible', timeout: 15000 })
await page.fill('#role', ROLE)
await page.fill('#loc', PLACE)
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })

// back on Home: step one ticked, and recent jobs picked from the profile
await Promise.all([
  page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
  page.getByRole('link', { name: 'Home' }).click(),
])
await page.locator('[data-testid="picked-job"]')
  .or(page.getByText('No new jobs matched')).first().waitFor({ timeout: 60000 })
check('profile step is ticked',
  (await page.locator('section', { hasText: 'Get started' }).innerText()).includes('1 of 3 done'))
const picks = await page.locator('[data-testid="picked-job"]').allInnerTexts()
check('jobs picked from the profile', picks.length > 0 && picks.length <= 5, `${picks.length} jobs`)
const stale = picks.filter((t) => {
  const m = t.match(/Posted (\d+) days ago/)
  return m && Number(m[1]) > 7
})
check('picked jobs are from the past 7 days', stale.length === 0, `${stale.length} older`)
check('picked jobs show where the pay figure came from',
  picks.every((t) => /employer stated|estimated|No salary stated/.test(t)))
await page.screenshot({ path: `${OUT}/2-picked-jobs.png`, fullPage: true })

// "See all" carries the search into Find Roles and runs it
await Promise.all([
  page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
  page.getByRole('link', { name: 'See all in Find Roles' }).click(),
])
await page.waitForSelector('article', { timeout: 60000 })
const tags = await page.getByLabel('Selected locations').innerText()
check('See all opens Find Roles with the search filled in and run',
  (await page.inputValue('#q')) === ROLE && tags.includes(PLACE))

// track one, and the summary on Home follows
const title = await page.locator('article h2').first().innerText()
await page.locator('button:has-text("Mark as applied")').first().click()
await page.waitForSelector('text=Already applied', { timeout: 20000 })
await page.getByRole('link', { name: 'Home' }).click()
await page.waitForSelector('[data-testid="count-active"]', { timeout: 15000 })
const active = (await page.locator('[data-testid="count-active"]').innerText()).trim()
check('applications summary counts the tracked job', active.startsWith('1'), active.replace(/\s+/g, ' '))
check('recent application listed on Home',
  (await page.locator('section', { hasText: 'My applications' }).innerText()).includes(title.slice(0, 25)),
  title.slice(0, 40))
check('tracking ticks the find-roles step',
  (await page.locator('section', { hasText: 'Get started' }).innerText()).includes('2 of 3 done'))
await page.screenshot({ path: `${OUT}/3-summary.png`, fullPage: true })

// count tiles open My Applications on the matching tab
await page.locator('[data-testid="count-active"]').click()
await page.waitForSelector('[role="tab"][aria-selected="true"]', { timeout: 15000 })
const tab = (await page.locator('[role="tab"][aria-selected="true"]').innerText()).trim()
check('count tile opens the matching tab', tab.startsWith('Active'), tab.replace(/\s+/g, ' '))

// the pathway step fills the role in from the profile
await page.getByRole('link', { name: 'Home' }).click()
await page.getByRole('link', { name: 'Explore pathway' }).click()
await page.waitForSelector('#role', { state: 'visible', timeout: 15000 })
check('Explore pathway fills in the role', (await page.inputValue('#role')) === ROLE)

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter(c => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
