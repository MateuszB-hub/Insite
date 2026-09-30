# Every browser, every screen size, and accessibility (WCAG 2.1 AA)

Branch: `feat/a11y-browsers` · Kind: big feature (inline chain) · Release: <tag after merge>

## Plan
The owner asked for accessibility and for the site to work in every browser and on every device.

**Acceptance criteria:**
1. Every signed-in page, plus sign-in and a real Find Roles search, works in Chromium (Chrome, Edge), Firefox and WebKit (Safari), at desktop, tablet and phone sizes: no JavaScript errors, no sideways scrolling, the content has real width, and the menu is reachable.
2. No serious or critical axe violations (WCAG 2.1 A/AA) on any page, in any setup.
3. One repeatable command runs all of it: `npm run demo:matrix` (with `./dev.sh` running).

**First measurement (before the changes):** 172 of 216 checks passed.
- **Phones:** the fixed 256 px sidebar left a 390 px phone about 134 px of page (seen in screenshots; the first sideways-scroll check missed it, so a width check was added).
- **Colour contrast:** 73 elements too faint; light grey `slate-400` text on white is 2.6:1 against the required 4.5:1.
- **Links:** 14 links on Home were told apart by colour alone.

## Build
- **`Layout.tsx`:**
  - Below 1024 px: a top bar and a **Menu** button (`aria-expanded`, `aria-controls`) that opens a slide-over panel (`role="dialog"`, `aria-modal`).
  - The panel closes on Escape, a tap on the backdrop or picking a page. Focus moves into it, stays there with Tab, and goes back to the button on close.
  - Also: a "Skip to main content" link, `aria-current` on the current page, `aria-label` on sign-out, and `min-w-0` on main.
- **Contrast:**
  - `text-slate-400` → `text-slate-500` on light backgrounds. The dark sign-in background and the dark menu keep `slate-400`, which is correct on dark.
  - Grey badges on light grey go `slate-500` → `slate-600`.
- **Home:** links inside sentences are underlined.
- **Page padding:** `p-4 sm:p-8`, so phones get 16 px.
- **Tooling:** `e2e/matrix-demo.mjs` (Playwright across 3 engines × 3 sizes, using real iPhone 13, Pixel 7 and iPad profiles where the engine supports them) with `@axe-core/playwright` as a dev dependency.

## Tests
- `npm run demo:matrix`: **288/288** checks; **no axe violations** of any severity on any page, in any setup.
- Earlier demos still pass: places 15/15, round 3 9/9. Typecheck and build pass.
- Screenshots checked by eye: Find Roles and Career Pathway on an iPhone.
- **Not tested:** real devices (these are the same browser engines, emulated); screen readers used by a person (VoiceOver, NVDA). axe finds roughly a third to a half of accessibility problems, so a manual keyboard and screen-reader pass is still worth doing; Android Firefox; very old browsers (the build targets browsers from about 2021 on).

## Review
APPROVED.
- **L:** the menu button shows its focus ring after the menu closes with Escape. That's intended, as keyboard focus goes back to it.
- **L:** Firefox has no mobile emulation, so "firefox:phone" is a small desktop window.
