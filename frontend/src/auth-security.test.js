/*
 * Authentication security guards (P-8). Like design-system.test.js, these read the
 * real source files, so a later change that breaks a rule fails `npm test`.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, posix, relative, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

import { AUTH_PATHS } from './services/authService'

const SRC = join(import.meta.dirname)

function sourceFiles(dir = SRC) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === 'test' ? [] : sourceFiles(path)
    return /\.jsx?$/.test(name) && !/\.test\.jsx?$/.test(name) ? [path] : []
  })
}

// POSIX form so results compare equally on Windows and Linux.
const rel = (path) => relative(SRC, path).split(sep).join(posix.sep)

// Code only: block and line comments are removed (but not the "//" in "https://"),
// so documentation that names a forbidden thing does not trip the guard.
function code(path) {
  return readFileSync(path, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:])\/\/.*$/gm, '$1')
}

function filesMatching(pattern, files = sourceFiles()) {
  return files.filter((path) => pattern.test(code(path))).map(rel).sort()
}

const AUTH_FILES = sourceFiles().filter((path) =>
  /^(services\/(apiClient|authService|tokenStore)|context\/|components\/auth\/|pages\/auth\/|pages\/AccountPage|utils\/auth)/.test(rel(path)),
)

describe('token storage', () => {
  it('nothing uses localStorage (the token lives in sessionStorage only)', () => {
    expect(filesMatching(/localStorage/)).toEqual([])
  })

  it('only the token store touches sessionStorage', () => {
    expect(filesMatching(/sessionStorage/)).toEqual(['services/tokenStore.js'])
  })

  it('the auth code was found (guards are not passing vacuously)', () => {
    expect(AUTH_FILES.length).toBeGreaterThanOrEqual(12)
  })
})

describe('secrets and logging', () => {
  it('the frontend reads no environment variable except VITE_API_BASE_URL and Vite built-ins', () => {
    const used = new Set(
      sourceFiles().flatMap((path) => [...code(path).matchAll(/import\.meta\.env\.([A-Z_]+)/g)].map((m) => m[1])),
    )
    expect([...used].sort()).toEqual(['DEV', 'MODE', 'PROD', 'VITE_API_BASE_URL'])
  })

  it('nothing mentions a JWT secret or decodes tokens', () => {
    expect(filesMatching(/JWT_SECRET|jwt-decode|jwtDecode|atob\(/)).toEqual([])
  })

  it('auth code never logs (tokens, passwords and profiles stay out of the console)', () => {
    expect(filesMatching(/console\./, AUTH_FILES)).toEqual([])
  })

  it('no raw HTML rendering (XSS is what could read sessionStorage)', () => {
    expect(filesMatching(/dangerouslySetInnerHTML|innerHTML\s*=/)).toEqual([])
  })
})

describe('backend contract', () => {
  it('only the three P-6 auth endpoints are called', () => {
    const paths = new Set(sourceFiles().flatMap((path) => [...code(path).matchAll(/['"`](\/auth\/[a-z/-]*)['"`]/g)].map((m) => m[1])))
    expect([...paths].sort()).toEqual(Object.values(AUTH_PATHS).sort())
  })

  it('the access token is read from the login response in one place only', () => {
    expect(filesMatching(/access_token/)).toEqual(['context/AuthProvider.jsx'])
  })
})
