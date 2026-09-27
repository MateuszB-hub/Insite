/**
 * Find Roles locations: checked against real places before searching.
 *
 * The user's own test: "new yotrk", "3" and "." returned jobs from Puerto
 * Rico and Alabama without a word. Now junk is refused, typos get "did you
 * mean", shared names say which place was used, and suggestions come as you
 * type.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-places/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))

console.log('\nInsite — location check demo\n')

const EMAIL = `places+${Date.now()}@example.com`
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Places Tester')
await page.fill('#email', EMAIL)
await page.fill('#password', 'a places demo passphrase')
await page.fill('#password-confirm', 'a places demo passphrase')
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
await page.fill('#q', 'cloud engineer')
const tags = async () => (await page.getByLabel('Selected locations').innerText().catch(() => '')).replace(/\s+/g, ' ').trim()
const search = async () => {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForTimeout(400)
}

// Junk is refused where it's typed.
await page.fill('#where', '3')
await page.press('#where', 'Enter')
const junk = await page.getByRole('alert').innerText().catch(() => '')
check('"3" is refused with a reason', /isn't a place/.test(junk) && (await tags()) === '', junk)

// Suggestions as you type.
await page.fill('#where', 'sea')
await page.waitForSelector('[role="listbox"] button', { timeout: 10000 })
const options = await page.locator('[role="listbox"] button').allInnerTexts()
check('suggestions as you type', options[0] === 'Seattle, WA', options.slice(0, 3).join(' | '))
await page.locator('[role="listbox"] button', { hasText: 'Seattle, WA' }).click()
check('picking one adds it', (await tags()).includes('Seattle, WA'))
await page.getByRole('button', { name: 'Remove Seattle, WA' }).click()

// A typo and a shared name.
for (const place of ['new yotrk', 'springfield']) {
  await page.fill('#where', place)
  await page.keyboard.press('Escape')
  await page.press('#where', 'Enter')
}
await search()
const notes = await page.locator('[data-testid="place-notes"]').innerText().catch(() => '')
check('a typo gets "did you mean"', /couldn't find "new yotrk"/.test(notes) && /New York, NY/.test(notes))
check('a shared name says which place was searched', /"springfield": showing Springfield, MO/.test(notes))
check('tags show what was actually searched', (await tags()).startsWith('Springfield, MO'), await tags())
await page.screenshot({ path: `${OUT}/1-notes.png`, fullPage: false })

await Promise.all([
  page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
  page.locator('[data-testid="place-notes"] button', { hasText: 'New York, NY' }).click(),
])
await page.waitForTimeout(400)
check('one click fixes the typo and searches again', (await tags()).includes('New York, NY'), await tags())

// Only junk: nothing is searched, and the page says so.
for (const place of ['Springfield, MO', 'New York, NY']) {
  await page.getByRole('button', { name: `Remove ${place}` }).click()
}
await page.fill('#where', 'zzzz')
await page.press('#where', 'Enter')
await search()
const body = await page.locator('body').innerText()
check('only junk places: nothing searched, and it says so',
  body.includes('None of the places you entered could be found, so nothing was searched.'))
await page.screenshot({ path: `${OUT}/2-nothing-searched.png`, fullPage: false })

// A borough and a ZIP code: searched as the city they're in, and said so.
for (const place of ['Brooklyn', '78701']) {
  await page.fill('#where', place)
  await page.keyboard.press('Escape')
  await page.press('#where', 'Enter')
}
check('a ZIP code is accepted as a location', (await tags()).includes('78701'), await tags())
await search()
const cityNotes = await page.locator('[data-testid="place-notes"]').innerText().catch(() => '')
check('a borough searches New York, NY and says why', /Brooklyn is part of New York City/.test(cityNotes))
check('a ZIP searches its city and says so', /ZIP 78701 is in Austin, TX/.test(cityNotes))
check('tags show the cities searched', (await tags()).includes('New York, NY') && (await tags()).includes('Austin, TX'), await tags())
await page.screenshot({ path: `${OUT}/3-borough-zip.png`, fullPage: false })

// "Remote" typed as a place: the Remote only filter instead, ticked.
for (const place of ['New York, NY', 'Austin, TX']) {
  await page.getByRole('button', { name: `Remove ${place}` }).click()
}
await page.fill('#where', 'Remote')
await page.keyboard.press('Escape')
await page.press('#where', 'Enter')
await search()
const remoteNotes = await page.locator('[data-testid="place-notes"]').innerText().catch(() => '')
check('"Remote" is not searched as a place', /Remote isn't a place/.test(remoteNotes), remoteNotes)
check('the Remote only box is ticked', await page.getByLabel('Genuinely remote only').isChecked())
await page.screenshot({ path: `${OUT}/4-remote.png`, fullPage: false })

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
