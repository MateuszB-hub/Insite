/** End-to-end password reset, the way a locked-out user experiences it. */
import { chromium } from 'playwright'
import { readFileSync } from 'node:fs'

const BASE = 'http://localhost:5173'
const EMAIL = `reset+${Date.now()}@example.com`
const PW1 = 'the original passphrase'
const PW2 = 'the replacement passphrase'
const LOG = process.env.INSITE_LOG ?? '/tmp/insite-dev.log'
const checks = []
const ok = (n, c, d='') => { checks.push(c); console.log(`  ${c ? 'PASS' : 'FAIL'}  ${n}${d?` — ${d}`:''}`) }

const b = await chromium.launch()
const p = await b.newPage({ viewport: { width: 1400, height: 1000 } })

// register, then forget the password
await p.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await p.getByRole('button', { name: 'Register' }).click()
await p.fill('#name', 'Reset Test'); await p.fill('#email', EMAIL); await p.fill('#password', PW1); await p.fill('#password-confirm', PW1)
await p.getByRole('checkbox').check()
await p.getByRole('button', { name: 'Create Account' }).click()
await p.waitForURL('**/jobs', { timeout: 20000 })
await p.evaluate(() => fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-Insite-CSRF': '1' } }))

// "Forgot password?" is reachable from the login card
await p.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await p.getByRole('link', { name: 'Forgot password?' }).click()
await p.waitForURL('**/forgot-password', { timeout: 10000 })
await p.waitForSelector('#email', { state: 'visible', timeout: 10000 })
ok('forgot-password reachable from login', true)

await p.fill('#email', EMAIL)
await p.getByRole('button', { name: 'Send reset link' }).click()
await p.waitForSelector('text=Check your inbox', { timeout: 15000 })
ok('generic acknowledgement shown', true)
await p.screenshot({ path: '/tmp/insite_shots/reset-1-sent.png', fullPage: true })

// grab the link from the console email provider's output
await new Promise(r => setTimeout(r, 800))
const log = readFileSync(LOG, 'utf8')
const m = [...log.matchAll(/reset-password\?token=([A-Za-z0-9_\-]+)/g)].pop()
ok('reset link delivered', Boolean(m))
const token = m[1]

await p.goto(`${BASE}/reset-password?token=${token}`, { waitUntil: 'networkidle' })
await p.waitForSelector('#new', { state: 'visible', timeout: 10000 })
await p.fill('#new', PW2); await p.fill('#conf', PW2)
await p.screenshot({ path: '/tmp/insite_shots/reset-2-form.png', fullPage: true })
await p.getByRole('button', { name: 'Update password' }).click()
await p.waitForSelector('text=Password updated', { timeout: 15000 })
ok('password reset completed', true)
await p.screenshot({ path: '/tmp/insite_shots/reset-3-done.png', fullPage: true })

// the link cannot be replayed
await p.goto(`${BASE}/reset-password?token=${token}`, { waitUntil: 'networkidle' })
await p.waitForSelector('#new', { state: 'visible', timeout: 10000 })
await p.fill('#new', 'a third long passphrase'); await p.fill('#conf', 'a third long passphrase')
await p.getByRole('button', { name: 'Update password' }).click()
await p.waitForTimeout(1500)
ok('link is single-use', (await p.locator('text=invalid or has expired').count()) > 0)

// old dead, new works
await p.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await p.fill('#email', EMAIL); await p.fill('#password', PW1)
await p.getByRole('button', { name: 'Sign In' }).click(); await p.waitForTimeout(1500)
ok('old password rejected', p.url().includes('/login'))
await p.fill('#email', EMAIL); await p.fill('#password', PW2)
await p.getByRole('button', { name: 'Sign In' }).click()
await p.waitForURL('**/jobs', { timeout: 20000 })
ok('new password works', true)

await b.close()

const failed = checks.filter((c) => !c).length
console.log(`\n${checks.length - failed}/${checks.length} checks passed`)
process.exit(failed ? 1 : 0)
