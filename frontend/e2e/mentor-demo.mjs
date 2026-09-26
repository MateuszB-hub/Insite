/**
 * The mentor's second round of feedback, checked in a browser.
 *
 * Walks the path the mentor took: sign up, fill in the profile, search for
 * "QA lead", filter by contract, open Career Pathway, delete the account.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-mentor/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const EMAIL = `mentor+${Date.now()}@example.com`
const PW = 'a mentor walkthrough passphrase'
const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))
const searchAndWait = async () => {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs/search'), { timeout: 90000 }),
    page.getByRole('button', { name: 'Search' }).click(),
  ])
  await page.waitForSelector('article, text=Nothing matched honestly', { timeout: 60000 }).catch(() => {})
}

console.log('\nInsite — mentor feedback demo\n')

// 1. consent: the AI sentence is information, not part of what you tick
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
const consentLabel = await page.locator('label', { has: page.getByRole('checkbox') }).innerText()
check('ticking the box is not an AI opt-in', !/opt in|AI/i.test(consentLabel), consentLabel.trim())
check('where data goes is stated separately',
  (await page.locator('body').innerText()).includes('not sent to an outside AI company'))
await page.fill('#name', 'Mentor Walkthrough')
await page.fill('#email', EMAIL)
await page.fill('#password', PW)
await page.fill('#password-confirm', PW)
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

// 8. profile says what is needed and what it's used for
await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
await page.waitForSelector('#role', { state: 'visible', timeout: 15000 })
const needed = await page.locator('span', { hasText: /^Needed$/ }).count()
const nice = await page.locator('span', { hasText: /^Nice to have$/ }).count()
check('profile marks needed vs nice to have', needed === 2 && nice >= 3, `${needed} needed, ${nice} nice to have`)
check('profile no longer claims hiring staff see it',
  !(await page.locator('body').innerText()).includes('hiring staff'))
await page.fill('#role', 'QA Lead')
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })

// 5. Find Roles starts from the profile
await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
await page.waitForFunction(() => document.querySelector('#q')?.value === 'QA Lead', null, { timeout: 15000 })
  .catch(() => {})
check('Find Roles is filled in from the profile', (await page.inputValue('#q')) === 'QA Lead')

// 2. "QA lead" is matched as a phrase: QA jobs, not "lead" jobs
await page.selectOption('#age', '30')
await searchAndWait()
const note = await page.locator('[data-testid="match-note"]').innerText().catch(() => '')
check('the words are matched in the job title', note.includes('in the job title'), note)
const titles = await page.locator('article[data-section="stated"] h2').allInnerTexts()
const qa = titles.filter((t) => /\bqa\b|quality|test/i.test(t))
check('results are QA jobs', titles.length > 0 && qa.length / titles.length >= 0.8, `${qa.length} of ${titles.length}`)
await page.screenshot({ path: `${OUT}/1-qa-lead.png`, fullPage: false })

// 4. the link says where it goes
const link = await page.locator('article a', { hasText: 'View listing on' }).first().innerText()
check('links name the site they open', /View listing on [a-z0-9.-]+\.[a-z]+/.test(link), link.trim())

// 3. job type: contract only, and the rest are accounted for
await page.selectOption('#type', 'contract')
await searchAndWait()
const cards = await page.locator('article[data-section="stated"]').allInnerTexts()
const allContract = cards.every((t) => /Contract/.test(t))
const explained = (await page.locator('body').innerText()).includes("didn't say whether they're contract")
check('contract filter keeps contract roles only', cards.length === 0 || allContract, `${cards.length} contract roles`)
check('adverts without a type are counted, not hidden silently', explained)
await page.screenshot({ path: `${OUT}/2-contract.png`, fullPage: false })

// 9. recent searches come back
await page.goto(`${BASE}/jobs?x=1`, { waitUntil: 'networkidle' })
await page.goto(`${BASE}/jobs`, { waitUntil: 'networkidle' })
const recent = await page.getByLabel('Recent searches').innerText().catch(() => '')
check('recent searches are remembered', recent.includes('QA Lead'), recent.replace(/\s+/g, ' '))

// 7. Career Pathway says what the time choice means
await page.goto(`${BASE}/pathway`, { waitUntil: 'networkidle' })
const body = await page.locator('body').innerText()
check('the horizon is explained', body.includes('How soon do you want to move?') && !body.includes('Looking ahead'))

// 6. deleting says it deletes your data
await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Delete my account and data' }).click()
check('delete says what it deletes',
  (await page.locator('body').innerText()).includes('profile,\napplications') ||
  (await page.locator('body').innerText()).includes('applications and their history'))

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
