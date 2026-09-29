/**
 * Cost of living on Find Roles: pay in another metro, in the person's home
 * terms (BEA Regional Price Parities). Mentor: "100k is basically 70k here."
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-col/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))
console.log('\nInsite — cost of living demo\n')

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Living Costs')
await page.fill('#email', `col+${Date.now()}@example.com`)
await page.fill('#password', 'a living costs passphrase')
await page.fill('#password-confirm', 'a living costs passphrase')
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

const searchSF = async () => {
  await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
  await page.fill('#q', 'software engineer')
  await page.fill('#where', 'San Francisco, CA')
  await page.keyboard.press('Escape')
  await page.press('#where', 'Enter')
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForTimeout(500)
}

await searchSF()
check('without a home city, the page says how to get the comparison',
  await page.getByTestId('living-cost-hint').isVisible().catch(() => false))

await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
await page.fill('#loc', 'Plano, TX')
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })

await searchSF()
const lines = await page.getByTestId('living-cost').allInnerTexts()
check('jobs with pay show their worth in home terms', lines.length > 0, lines[0] ?? '')
check('…as San Francisco pay in Dallas terms, costs higher there',
  lines.every((l) => /in Dallas terms/.test(l) && /higher in San (Francisco|Jose)/.test(l)), lines.slice(0, 2).join(' | '))
await page.screenshot({ path: `${OUT}/1-sf-in-dallas-terms.png`, fullPage: false })

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))
await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
