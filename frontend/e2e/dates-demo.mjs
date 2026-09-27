/**
 * Find Roles "Date posted" and "Sort", checked in a browser against live ads.
 *
 * Presets like the big job sites (past 24 hours, 3 days, week, 2 weeks,
 * month, any time), a custom "on or after" date, and newest first. The job
 * board filters by whole days and loosely, so the exact cut-off is Insite's.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-dates/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

/** "Posted 4 hours ago" -> 4; "yesterday" -> 24; "3 days ago" -> 72. */
function ageHours(text) {
  if (/within the hour/.test(text)) return 0
  let m = text.match(/Posted (\d+) hours? ago/)
  if (m) return Number(m[1])
  if (/Posted yesterday/.test(text)) return 24
  m = text.match(/Posted (\d+) days ago/)
  return m ? Number(m[1]) * 24 : null
}

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))

console.log('\nInsite — date posted demo\n')

const EMAIL = `dates+${Date.now()}@example.com`
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Dates Tester')
await page.fill('#email', EMAIL)
await page.fill('#password', 'a dates demo passphrase')
await page.fill('#password-confirm', 'a dates demo passphrase')
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
const ages = async () => (await page.locator('article[data-section="stated"]').allInnerTexts()).map(ageHours)

await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
await page.fill('#q', 'registered nurse')
await page.fill('#where', 'Chicago')
await page.press('#where', 'Enter')

const options = await page.locator('#age option').allInnerTexts()
check('date choices like other job sites',
  ['Past 24 hours', 'Past 3 days', 'Past week', 'Past 2 weeks', 'Past month', 'Any time', 'Custom date…']
    .every((o) => options.includes(o)), options.join(' | '))

// Past 24 hours, newest first
await page.selectOption('#age', '1')
await page.selectOption('#sort', 'date')
await search()
const day = await ages()
check('past 24 hours shows only ads under a day old',
  day.length > 0 && day.every((h) => h !== null && h < 24), `${day.length} ads, ages ${day.slice(0, 6).join(',')}h…`)
check('newest first really is newest first', day.every((h, i) => i === 0 || h >= day[i - 1]))
await page.screenshot({ path: `${OUT}/1-past-24h.png`, fullPage: false })

// Custom date: 3 days back
await page.selectOption('#age', 'custom')
const since = new Date(Date.now() - 3 * 86_400_000)
const iso = `${since.getFullYear()}-${String(since.getMonth() + 1).padStart(2, '0')}-${String(since.getDate()).padStart(2, '0')}`
await page.fill('#since', iso)
await search()
const custom = await ages()
check('a custom date keeps to ads on or after it',
  custom.length > 0 && custom.every((h) => h !== null && h <= 4 * 24), `${custom.length} ads since ${iso}`)
await page.screenshot({ path: `${OUT}/2-custom-date.png`, fullPage: false })

// Remembered with the date and the sort
await page.goto(`${BASE}/jobs?x=1`, { waitUntil: 'networkidle' })
await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
const recent = await page.getByLabel('Recent searches').innerText().catch(() => '')
check('recent searches remember the date and sort',
  /Past 24 hours · newest first/.test(recent) && new RegExp(`since ${iso}`).test(recent), recent.replace(/\s+/g, ' '))
await Promise.all([
  page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
  page.getByLabel('Recent searches').getByRole('button', { name: /Past 24 hours/ }).click(),
])
check('re-running one restores its date and sort',
  (await page.inputValue('#age')) === '1' && (await page.inputValue('#sort')) === 'date')

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
