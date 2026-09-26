/**
 * Proof-of-function demo for the Career Pathway narrative (#3).
 *
 * Drives the real UI against the real backend and asserts the properties that
 * make the feature trustworthy -- not just that it rendered:
 *
 *   1. narrative appears and is attributed to an engine
 *   2. every destination gets a readiness badge
 *   3. badges are DIFFERENTIATED (not all "ready")
 *   4. prose never contradicts the badge ("Readiness: ..." leakage)
 *   5. prose contains no dollar figure (numbers come from data, not the model)
 *   6. no JS errors
 *
 * Usage:  npm run demo         (servers must already be running)
 * Output: e2e/output/*.png and a video of the run.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output/', import.meta.url).pathname
const ROLE = process.env.DEMO_ROLE ?? 'Senior Backend Software Engineer'
const INDUSTRY = process.env.DEMO_INDUSTRY ?? 'Fintech'

rmSync(OUT, { recursive: true, force: true })
mkdirSync(OUT, { recursive: true })

const checks = []
const check = (name, pass, detail = '') => {
  checks.push({ name, pass, detail })
  console.log(`  ${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`)
}

const browser = await chromium.launch()
const context = await browser.newContext({
  viewport: { width: 1440, height: 1400 },
  recordVideo: { dir: OUT, size: { width: 1440, height: 1000 } },
})
const page = await context.newPage()
const jsErrors = []
page.on('pageerror', (e) => jsErrors.push(e.message))

// Keep the raw response: the model-authored fields are the ones that must
// never contain a number, and scraping the rendered card cannot tell those
// apart from the BLS wages rendered beside them.
let payload = null
page.on('response', async (r) => {
  if (r.url().includes('/api/career-pathway') && r.status() === 200) {
    try { payload = await r.json() } catch { /* ignore */ }
  }
})
page.on('console', (m) => {
  // /api/auth/me returns 401 before login; expected, not a fault.
  if (m.type() === 'error' && !/401/.test(m.text())) jsErrors.push(`console: ${m.text()}`)
})

console.log(`\nInsite — Career Pathway demo`)
console.log(`   target: ${BASE}`)
console.log(`   role:   ${ROLE} / ${INDUSTRY}\n`)

// The app requires authentication, so the demo registers a throwaway
// candidate rather than depending on anyone's real credentials.
const EMAIL = `demo+${Date.now()}@example.com`
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Demo')
await page.fill('#email', EMAIL)
await page.fill('#password', 'a demo passphrase here')
await page.fill('#password-confirm', 'a demo passphrase here')
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL(u => !u.pathname.startsWith('/login'), { timeout: 20000 })

await page.goto(`${BASE}/pathway`, { waitUntil: 'networkidle' })
await page.waitForSelector('#role', { state: 'visible', timeout: 15000 })
await page.screenshot({ path: `${OUT}/1-empty.png`, fullPage: true })

await page.fill('#role', ROLE)
await page.fill('#ind', INDUSTRY)
await page.screenshot({ path: `${OUT}/2-filled.png`, fullPage: true })

const started = Date.now()
await page.getByRole('button', { name: 'Map pathway' }).click()

// Tester: the old ~22 s wait was "too slow, most people would just leave".
// The facts come without waiting on a model at all.
await page.waitForSelector('text=Roles open to you', { timeout: 60000 })
const factsIn = (Date.now() - started) / 1000
const earlyBadges = await page.locator('span', { hasText: /^(Ready now|Stretch|Longer term)$/ }).count()
await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}/3-facts.png`, fullPage: true })

console.log(`facts in ${factsIn.toFixed(1)}s\n`)
console.log('assertions:')

check('facts and badges show without waiting for a model', factsIn < 10 && earlyBadges >= 3,
      `${factsIn.toFixed(1)}s, ${earlyBadges} badges`)

// Tester: "kind of useless tbh. Super generic information". The headline is
// computed from the data, and every role says what it takes and where to learn.
const glance = await page.locator('section', { hasText: 'At a glance' }).first().innerText()
check('at-a-glance headline from the data', /Of \d+ next roles?:/.test(glance), glance.split('\n')[1] ?? '')
const roleCards = page.locator('article', { has: page.locator('text=Training:') })
const cardCount = await roleCards.count()
const linked = await page.locator('article [data-testid="learning-links"]').count()
check('every role links to where to learn', cardCount >= 3 && linked >= cardCount, `${linked} linked of ${cardCount}`)
const roadmaps = await page.locator('a[href^="https://roadmap.sh/"]').count()
check('tech roles link to roadmap.sh', roadmaps > 0, `${roadmaps} roadmap links`)
const payChanges = await page.locator('[data-testid="pay-change"]').count()
check('pay change vs the current role shown', payChanges > 0, `${payChanges} roles`)

// 1. the AI summary is optional, labelled, and comes after the facts
const askedAt = Date.now()
await page.getByRole('button', { name: 'Write me a summary' }).click()
await page.waitForSelector('h2:text-is("AI summary")', { timeout: 240000 })
console.log(`  (summary written in ${((Date.now() - askedAt) / 1000).toFixed(1)}s)`)
await page.waitForTimeout(500)
await page.screenshot({ path: `${OUT}/4-result.png`, fullPage: true })
const summary = await page.locator('section', { hasText: 'AI summary' }).first().innerText()
check('summary rendered on request', summary.length > 80, `${summary.length} chars`)
check('engine attributed', /Local model|Anthropic|Mock/.test(summary))

// 2/3. readiness badges present and differentiated
const badges = await page.locator('span', { hasText: /^(Ready now|Stretch|Longer term)$/ }).allInnerTexts()
check('readiness badge on every role', badges.length >= 3, `${badges.length} badges`)
const unique = [...new Set(badges)]
check('badges differentiated', unique.length > 1, unique.join(', '))

// 4. prose must not restate readiness in ANY phrasing -- the badge is the
// single source of truth, and a restatement can silently disagree with it.
const cards = await page.locator('article').allInnerTexts()
const RESTATEMENT = /readiness\s*[:\-]|this transition is considered|considered\s+(a\s+)?['"]?(ready|stretch|long[- ]term)/i
const leaked = cards.filter((t) => RESTATEMENT.test(t))
check('no readiness restatement in prose', leaked.length === 0, `${leaked.length} leaks`)

// 5. The model must not state money. Checked against the model-authored
// fields specifically -- wages shown alongside them come from BLS and are
// supposed to be there.
const authored = payload
  ? [
      payload.narrative?.summary ?? '',
      ...(payload.narrative?.skill_gaps ?? []),
      ...(payload.narrative?.risks ?? []),
      ...payload.pathways.flatMap((p) => [p.rationale ?? '', ...(p.steps ?? [])]),
    ].join(' ')
  : ''
const dollars = authored.match(/\$[\d,]+/g) ?? []
check('no model-authored dollar figures', payload !== null && dollars.length === 0,
      dollars.join(' ') || 'none')

// 7. and the wages that ARE shown must come from the data layer
const wagesShown = payload?.pathways.filter((p) => p.wage?.annual_median).length ?? 0
check('wages present and sourced from BLS', wagesShown > 0,
      `${wagesShown} roles with BLS median`)

// 6. clean console
check('no JS errors', jsErrors.length === 0, jsErrors.slice(0, 2).join('; '))

await context.close()
await browser.close()

const failed = checks.filter((c) => !c.pass)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
console.log(`artifacts: frontend/e2e/output/  (4 screenshots + video)\n`)
process.exit(failed.length ? 1 : 0)
