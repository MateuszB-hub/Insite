/**
 * Every page, in every browser engine, at every size -- plus an accessibility
 * audit (axe, WCAG 2.1 AA).
 *
 *   npm run demo:matrix               all 9 setups
 *   MATRIX=webkit:phone npm run demo:matrix
 *
 * Chromium stands for Chrome and Edge, Firefox for Firefox, WebKit for Safari
 * (desktop and iPhone). Per page: no JavaScript errors, no sideways scrolling,
 * the menu reachable, and no serious or critical accessibility violations.
 * Screenshots go to e2e/output-matrix/ for a look by eye.
 */
import { chromium, firefox, webkit, devices } from 'playwright'
import AxeBuilder from '@axe-core/playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-matrix/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const ENGINES = { chromium, firefox, webkit }
const SIZES = {
  desktop: { viewport: { width: 1440, height: 900 } },
  tablet: { viewport: { width: 820, height: 1180 }, hasTouch: true },
  phone: { viewport: { width: 390, height: 844 }, hasTouch: true },
}
/** Real device profiles where the engine supports them (Firefox has no mobile mode). */
const deviceFor = (engine, size) => {
  if (size === 'phone' && engine === 'webkit') return devices['iPhone 13']
  if (size === 'phone' && engine === 'chromium') return devices['Pixel 7']
  if (size === 'tablet' && engine === 'webkit') return devices['iPad (gen 7)']
  return SIZES[size]
}
const only = process.env.MATRIX?.split(',')
const setups = Object.keys(ENGINES).flatMap((e) => Object.keys(SIZES).map((s) => `${e}:${s}`))
  .filter((k) => !only || only.includes(k))

const PAGES = [
  { path: '/home', name: 'Home' },
  { path: '/jobs', name: 'Find Roles' },
  { path: '/applications', name: 'My Applications' },
  { path: '/pathway', name: 'Career Pathway' },
  { path: '/dashboard', name: 'Future of Work' },
  { path: '/profile', name: 'Profile' },
]

const results = []
const violations = new Map()   // rule id -> { impact, help, where: Set }
const record = (setup, page, check, pass, detail = '') => {
  results.push({ setup, page, check, pass, detail })
  if (!pass) console.log(`  FAIL  ${setup}  ${page}: ${check}${detail ? ` — ${detail}` : ''}`)
}

async function audit(page, setup, where) {
  const { violations: found } = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze()
  for (const v of found) {
    const entry = violations.get(v.id) ?? { impact: v.impact, help: v.help, where: new Set(), nodes: 0 }
    entry.where.add(`${where} (${setup})`)
    entry.nodes += v.nodes.length
    violations.set(v.id, entry)
  }
  const serious = found.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  record(setup, where, 'no serious accessibility problems', serious.length === 0,
    serious.map((v) => v.id).join(', '))
}

async function layoutChecks(page, setup, where) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  record(setup, where, 'no sideways scrolling', overflow <= 1, `${overflow}px too wide`)
  // Squeezed is as bad as overflowing: a 256px sidebar left a phone 134px.
  const room = await page.evaluate(() => {
    const main = document.querySelector('main') ?? document.body
    return Math.min(main.getBoundingClientRect().width, window.innerWidth)
  })
  record(setup, where, 'the page gets real width', room >= Math.min(300, 0.75 * page.viewportSize().width),
    `${Math.round(room)}px of ${page.viewportSize().width}`)
}

// One account for every setup: cookies carry across engines via storageState.
let storage = null
async function signIn(browser) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await page.getByRole('button', { name: 'Register' }).click()
  await page.fill('#name', 'Matrix Tester')
  await page.fill('#email', `matrix+${Date.now()}@example.com`)
  await page.fill('#password', 'a matrix test passphrase')
  await page.fill('#password-confirm', 'a matrix test passphrase')
  await page.getByRole('checkbox').check()
  await page.getByRole('button', { name: 'Create Account' }).click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })
  storage = await context.storageState()
  await context.close()
}

console.log(`\nInsite — ${setups.length} browser/size setups, ${PAGES.length + 1} pages each\n`)

for (const setup of setups) {
  const [engineName, size] = setup.split(':')
  const browser = await ENGINES[engineName].launch()
  if (!storage) await signIn(browser)
  const errors = []

  // Signed out: the sign-in page.
  const outCtx = await browser.newContext({ ...deviceFor(engineName, size) })
  const out = await outCtx.newPage()
  out.on('pageerror', (e) => errors.push(`login: ${e.message}`))
  await out.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
  await layoutChecks(out, setup, 'Sign in')
  await audit(out, setup, 'Sign in')
  await out.screenshot({ path: `${OUT}/${engineName}-${size}-login.png` })
  await outCtx.close()

  const ctx = await browser.newContext({ ...deviceFor(engineName, size), storageState: storage })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => errors.push(`${page.url()}: ${e.message}`))

  for (const { path, name } of PAGES) {
    await page.goto(`${BASE}${path}`, { waitUntil: 'networkidle' })
    await page.waitForTimeout(300)
    await layoutChecks(page, setup, name)
    // The menu must be reachable: every other page's link visible, or a
    // visible button that opens the menu.
    const other = PAGES.find((p) => p.path !== path)
    const linkVisible = await page.getByRole('link', { name: other.name }).first().isVisible().catch(() => false)
    const menuButton = page.getByRole('button', { name: /menu/i }).first()
    const buttonVisible = await menuButton.isVisible().catch(() => false)
    let reachable = linkVisible
    if (!reachable && buttonVisible) {
      await menuButton.click()
      reachable = await page.getByRole('link', { name: other.name }).first().isVisible().catch(() => false)
      await page.keyboard.press('Escape')
    }
    record(setup, name, 'menu reachable', reachable)
    await audit(page, setup, name)
    await page.screenshot({ path: `${OUT}/${engineName}-${size}-${path.slice(1)}.png` })
  }

  // One real interaction: a search on Find Roles (the board's answer is
  // cached server-side, so repeats across setups cost nothing).
  await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
  await page.fill('#q', 'registered nurse')
  await page.fill('#where', 'Austin, TX')
  await page.keyboard.press('Escape')
  await page.press('#where', 'Enter')
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForTimeout(600)
  record(setup, 'Find Roles', 'a search shows jobs', (await page.locator('article').count()) > 0)
  await layoutChecks(page, setup, 'Find Roles results')
  await audit(page, setup, 'Find Roles results')
  await page.screenshot({ path: `${OUT}/${engineName}-${size}-jobs-results.png`, fullPage: true })

  record(setup, 'all pages', 'no JavaScript errors', errors.length === 0, errors.slice(0, 2).join('; '))
  await ctx.close()
  await browser.close()
  const mine = results.filter((r) => r.setup === setup)
  console.log(`  ${setup.padEnd(16)} ${mine.filter((r) => r.pass).length}/${mine.length} checks passed`)
}

console.log('\nAccessibility (axe, WCAG 2.1 AA) — every rule broken anywhere:')
if (!violations.size) console.log('  none')
for (const [id, v] of [...violations].sort((a, b) => (a[1].impact < b[1].impact ? -1 : 1))) {
  const pages = [...new Set([...v.where].map((w) => w.replace(/ \(.*\)$/, '')))]
  console.log(`  [${v.impact}] ${id}: ${v.help} — ${v.nodes} elements; ${pages.join(', ')}`)
}
const failed = results.filter((r) => !r.pass)
console.log(`\n${results.length - failed.length}/${results.length} checks passed`)
process.exit(failed.length ? 1 : 0)
