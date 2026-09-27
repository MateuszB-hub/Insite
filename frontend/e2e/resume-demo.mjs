/**
 * "Fill in from your résumé", checked in a browser.
 *
 * Uses a made-up résumé built as a real PDF right here (no real people) and
 * the local model, so it takes ~10-30 s per upload.
 */
import { chromium } from 'playwright'
import { mkdirSync, rmSync } from 'node:fs'

const BASE = process.env.DEMO_BASE_URL ?? 'http://localhost:5173'
const OUT = new URL('./output-resume/', import.meta.url).pathname
rmSync(OUT, { recursive: true, force: true }); mkdirSync(OUT, { recursive: true })

const checks = []
const check = (n, p, d = '') => { checks.push({ n, p }); console.log(`  ${p ? 'PASS' : 'FAIL'}  ${n}${d ? ` — ${d}` : ''}`) }

/** A minimal text PDF (PDF 1.4, Helvetica), like one saved from Word. */
function makePdf(lines) {
  const esc = (s) => s.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')
  const stream = `BT /F1 10 Tf 50 780 Td 13 TL ${lines.map((l) => `(${esc(l)}) '`).join(' ')} ET`
  const objs = [
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    '<< /Type /Page /Parent 4 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 1 0 R >> >> /Contents 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Catalog /Pages 4 0 R >>',
  ]
  let out = '%PDF-1.4\n'
  const offsets = []
  objs.forEach((body, i) => { offsets.push(out.length); out += `${i + 1} 0 obj\n${body}\nendobj\n` })
  const xref = out.length
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`
  offsets.forEach((o) => { out += `${String(o).padStart(10, '0')} 00000 n \n` })
  out += `trailer\n<< /Size ${objs.length + 1} /Root 5 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return Buffer.from(out, 'latin1')
}

const RESUME = makePdf([
  'Dana Whitfield',
  'Omaha, NE | dana.w@example.com',
  'EXPERIENCE',
  'Registered Nurse, Nebraska Medical Center, Jun 2019 - Present',
  'Triage, patient assessment, IV therapy, Epic charting.',
  'Licensed Practical Nurse, Bellevue Care Home, Jan 2015 - May 2019',
  'Medication administration and wound care.',
  'SKILLS: Triage; IV therapy; Wound care; Epic',
  'CERTIFICATIONS: BLS, ACLS',
])

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } })
const errs = []
page.on('pageerror', (e) => errs.push(e.message))

console.log('\nInsite — résumé import demo\n')

const EMAIL = `resume+${Date.now()}@example.com`
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' })
await page.getByRole('button', { name: 'Register' }).click()
await page.fill('#name', 'Resume Tester')
await page.fill('#email', EMAIL)
await page.fill('#password', 'a resume demo passphrase')
await page.fill('#password-confirm', 'a resume demo passphrase')
await page.getByRole('checkbox').check()
await page.getByRole('button', { name: 'Create Account' }).click()
await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 })

// Already filled in: the résumé must offer, not overwrite.
await page.goto(`${BASE}/profile`, { waitUntil: 'networkidle' })
await page.fill('#loc', 'Chicago')
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })

const upload = async (file) => {
  await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/me/profile/resume'), { timeout: 120000 }),
    page.setInputFiles('input[type=file]', file),
  ])
  await page.waitForTimeout(300)
}

const started = Date.now()
await upload({ name: 'resume.pdf', mimeType: 'application/pdf', buffer: RESUME })
const secs = ((Date.now() - started) / 1000).toFixed(1)
await page.screenshot({ path: `${OUT}/1-filled.png`, fullPage: true })

check('empty fields fill in from the résumé', (await page.inputValue('#role')) === 'Registered Nurse', `${secs}s`)
check('years are calculated from the job dates', (await page.inputValue('#yrs')) === '11')
check('skills and certifications filled in',
  /Triage/.test(await page.inputValue('#skills')) && /ACLS/.test(await page.inputValue('#certs')))
const badges = await page.locator('[data-testid="from-resume"]').allInnerTexts()
check('each filled field says where it came from',
  badges.some((b) => b.includes('from your résumé')) && badges.some((b) => b.includes('calculated')),
  badges.join(' | '))
check('model-written fields are marked as suggestions', badges.some((b) => b.includes('suggested')))
check('a field already filled in is not overwritten', (await page.inputValue('#loc')) === 'Chicago')
const offer = await page.locator('[data-testid="resume-offer"]').allInnerTexts()
check("…but the résumé's value is offered", offer.some((o) => /Omaha/.test(o)), offer.join(' | '))
check('the report says nothing is saved yet',
  /Nothing is saved yet/.test(await page.locator('[data-testid="resume-report"]').innerText()))

// Nothing saved until Save.
await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('#role', { timeout: 15000 })
check('nothing is saved until Save is pressed', (await page.inputValue('#role')) === '')

// Use the offer, save, and it sticks.
await upload({ name: 'resume.pdf', mimeType: 'application/pdf', buffer: RESUME })
await page.locator('[data-testid="resume-offer"]', { hasText: 'Omaha' }).getByRole('button', { name: 'Use it' }).click()
await page.getByRole('button', { name: 'Save profile' }).click()
await page.waitForSelector('text=Saved', { timeout: 10000 })
await page.reload({ waitUntil: 'networkidle' })
await page.waitForSelector('#role', { timeout: 15000 })
check('after Use it and Save, it is kept',
  (await page.inputValue('#role')) === 'Registered Nurse' && /Omaha/.test(await page.inputValue('#loc')) &&
  /BLS/.test(await page.inputValue('#certs')))

// Not a PDF: a plain reason, nothing else changes.
await upload({ name: 'resume.docx', mimeType: 'application/octet-stream', buffer: Buffer.from('PK not a pdf') })
const alert = await page.getByRole('alert').innerText().catch(() => '')
check('a non-PDF gets a plain explanation', /isn't a PDF/.test(alert), alert)

check('no JS errors', errs.length === 0, errs.slice(0, 2).join('; '))

await browser.close()
const failed = checks.filter((c) => !c.p)
console.log(`\n${checks.length - failed.length}/${checks.length} checks passed`)
process.exit(failed.length ? 1 : 0)
