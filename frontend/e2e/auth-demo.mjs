/**
 * Proof-of-function for the login portal.
 *   1. protected route redirects to /login when signed out
 *   2. register creates the account and lands on the dashboard
 *   3. the real email/name appear in the sidebar (not the old hardcoded stub)
 *   4. sign out returns to /login and re-protects the route
 *   5. sign back in works
 *   6. session cookie is not readable from JavaScript (httpOnly)
 *   7. sign-up blocks a mismatched confirmation; the eye toggle reveals the password
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-auth/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

// Always a fresh address: reusing a real one hits the duplicate-account
// guard and the demo cannot re-register.
const EMAIL = process.env.DEMO_EMAIL ?? `authdemo+${Date.now()}@example.com`
const PW = 'insite demo passphrase 2026'
const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
const errs = []
page.on('pageerror', e => errs.push(e.message))

console.log('\nInsite — login portal demo\n')

// 1. guard
await page.goto(`${BASE}/dashboard`, { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
check('protected route redirects when signed out', page.url().includes('/login'), page.url().replace(BASE, ''))
await page.screenshot({ path: `${OUT}/1-login.png`, fullPage: true })

// 2. register
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Mateusz')
await page.fill('#email', EMAIL)
await page.fill('#password', PW)
await page.getByRole('checkbox').check()

// 7. confirmation must match; nothing is submitted until it does
await page.fill('#password-confirm', PW + ' typo')
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForTimeout(300)
const mismatchText = await page.locator('form').innerText()
check('mismatched confirmation is blocked', page.url().includes('/login') && mismatchText.includes('Passwords do not match'))
await page.getByRole('button', { name: 'Show password' }).first().click()
check('eye toggle reveals the password', (await page.getAttribute('#password', 'type')) === 'text')
await page.getByRole('button', { name: 'Hide password' }).first().click()
check('eye toggle hides it again', (await page.getAttribute('#password', 'type')) === 'password')
await page.fill('#password-confirm', PW)

await page.screenshot({ path: `${OUT}/2-register.png`, fullPage: true })
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL('**/dashboard', { timeout: 20000 })
check('register signs in and lands on dashboard', page.url().includes('/dashboard'))

// 3. real identity in sidebar
const sidebar = await page.locator('aside').innerText()
check('sidebar shows the real user', sidebar.includes(EMAIL), EMAIL)
check('hardcoded stub is gone', !sidebar.includes('applicant@example.com'))
await page.screenshot({ path: `${OUT}/3-signed-in.png`, fullPage: true })

// 6. httpOnly
const visible = await page.evaluate(() => document.cookie)
check('session cookie invisible to JavaScript', !visible.includes('insite_session'), visible || '(no js-readable cookies)')

// 4. sign out
await page.locator('button[title="Sign out"]').click()
await page.waitForURL('**/login', { timeout: 20000 })
await page.goto(`${BASE}/pathway`, { waitUntil: 'networkidle' })
await page.waitForTimeout(500)
check('route re-protected after sign out', page.url().includes('/login'))

// 5. sign back in
await page.fill('#email', EMAIL)
await page.fill('#password', PW)
await page.getByRole('button', { name: 'Sign In' }).click()
await page.waitForURL(/\/(dashboard|pathway)/, { timeout: 20000 })
check('sign back in works', !page.url().includes('/login'), page.url().replace(BASE, ''))
await page.screenshot({ path: `${OUT}/4-signed-back-in.png`, fullPage: true })

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter(c => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
console.log(`artifacts: frontend/e2e/output-auth/\n`)
process.exit(failed.length ? 1 : 0)
