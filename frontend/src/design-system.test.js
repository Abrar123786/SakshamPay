/*
 * Design-system guards (P-7). These read the real source files, so a future change
 * that breaks a rule fails `npm test` instead of slipping through review.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, posix, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = join(import.meta.dirname)
const CSS = readFileSync(join(SRC, 'styles', 'index.css'), 'utf8')

function sourceFiles(dir = SRC) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return /\.(jsx?|css)$/.test(name) && !/\.test\.jsx?$/.test(name) ? [path] : []
  })
}

function token(name) {
  const match = CSS.match(new RegExp(`--color-${name}:\\s*(#[0-9a-f]{6})`, 'i'))
  if (!match) throw new Error(`token --color-${name} not found`)
  return match[1]
}

function contrast(a, b) {
  const luminance = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    const f = (c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
  }
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

describe('risk colours are exclusive to risk UI', () => {
  it('only RiskBadge (and the token definitions) use risk-* tokens', () => {
    const offenders = sourceFiles()
      .filter((path) => /risk-(low|medium|high)/.test(readFileSync(path, 'utf8')))
      // relative() uses the platform separator (\ on Windows); compare in POSIX form.
      .map((path) => relative(SRC, path).split(sep).join(posix.sep))
      .sort()
    expect(offenders).toEqual(['components/ui/RiskBadge.jsx', 'styles/index.css'])
  })
})

describe('Tailwind palette restriction', () => {
  const REMOVED = 'red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose'

  it('removes the chromatic default palettes', () => {
    for (const hue of REMOVED.split('|')) {
      expect(CSS).toContain(`--color-${hue}-*: initial;`)
    }
  })

  it('keeps neutral palettes available', () => {
    for (const hue of ['slate', 'gray', 'zinc', 'neutral', 'stone']) {
      expect(CSS).not.toContain(`--color-${hue}-*: initial`)
    }
  })

  it('no source file uses a removed palette class (it would silently produce no style)', () => {
    const pattern = new RegExp(`\\b[a-z-]+-(${REMOVED})-\\d{2,3}\\b`)
    const offenders = sourceFiles()
      .filter((path) => !path.endsWith('index.css') && pattern.test(readFileSync(path, 'utf8')))
      .map((path) => relative(SRC, path))
    expect(offenders).toEqual([])
  })
})

describe('colour tokens meet WCAG 2.2 AA', () => {
  const TEXT = 4.5
  const UI = 3

  it.each([
    ['ink', 'surface', TEXT],
    ['ink-muted', 'surface', TEXT],
    ['ink-subtle', 'surface', TEXT],
    ['ink-subtle', 'surface-raised', TEXT],
    ['ink-subtle', 'surface-muted', TEXT],
    ['ink-muted', 'surface-muted', TEXT],
    ['brand', 'surface-raised', TEXT],
    ['brand', 'surface', TEXT],
    ['brand', 'brand-soft', TEXT],
    ['danger', 'surface-raised', TEXT],
    ['danger', 'danger-soft', TEXT],
    ['risk-low', 'risk-low-soft', TEXT],
    ['risk-medium', 'risk-medium-soft', TEXT],
    ['risk-high', 'risk-high-soft', TEXT],
    ['line-input', 'surface-raised', UI],
    ['line-input', 'surface-muted', UI],
    ['brand', 'surface', UI], // focus outline
  ])('%s on %s', (foreground, background, minimum) => {
    expect(contrast(token(foreground), token(background))).toBeGreaterThanOrEqual(minimum)
  })

  it.each([
    ['brand', TEXT],
    ['brand-hover', TEXT],
    ['danger', TEXT],
    ['danger-hover', TEXT],
  ])('white text on %s', (background, minimum) => {
    expect(contrast('#ffffff', token(background))).toBeGreaterThanOrEqual(minimum)
  })
})

describe('typography', () => {
  it('uses the self-hosted IBM Plex Sans', () => {
    expect(CSS).toMatch(/--font-sans:\s*"IBM Plex Sans Variable"/)
    expect(readFileSync(join(SRC, 'main.jsx'), 'utf8')).toContain("import '@fontsource-variable/ibm-plex-sans/wght.css'")
  })

  it('loads no fonts from third-party hosts', () => {
    const offenders = sourceFiles().filter((path) => /fonts\.(googleapis|gstatic)\.com/.test(readFileSync(path, 'utf8')))
    expect(offenders).toEqual([])
  })
})
