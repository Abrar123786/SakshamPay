# SakshamPay frontend authentication (P-8)

The React side of sign-in. It calls only the three P-6 endpoints
([`authentication.md`](authentication.md)) and made no backend changes.

## Pages and routes

| Path | Who can open it | Page |
| --- | --- | --- |
| `/login` | Signed-out users (`GuestOnly`) | Sign in: email, password with show/hide |
| `/register` | Signed-out users (`GuestOnly`) | Create an account: full name, email, optional mobile, password, confirm password |
| `/dashboard` | Signed-in users (`RequireAuth`) | The dashboard (P-9, see [`dashboard.md`](dashboard.md)) |
| `/account` | Signed-in users (`RequireAuth`) | Profile from `GET /auth/me` and **Sign out** |
| `/`, unknown paths | Everyone | Landing placeholder, 404 page (unchanged) |

- **Signed out, opening `/account`:** sent to `/login`. After signing in, the user returns
  to `/account`. Later protected pages work the same way.
- **Signed in, opening `/login` or `/register`:** sent to `/dashboard`
  (`DEFAULT_SIGNED_IN_PATH` in `src/utils/authPaths.js`; it was `/account` in P-8).
- **While a stored session is being checked:** guarded pages show "Checking your
  session". Public pages render immediately.
- **The header** shows **Sign in** / **Create account**. Signed in, it shows the main
  navigation and **Sign out** (P-9, a **Menu** button on phones).

## Flows

```text
Register ─ POST /auth/register ─> /login with "Account created", email prefilled
                                   (no automatic sign-in; the password is never kept)

Sign in ─ POST /auth/login ─> save { token, expiresAt } ─ GET /auth/me ─> signed in
                                                           (fails → token discarded)

Page load ─ stored token? ─ no ──────────────────────────> signed out
                           ├ expired ─ clear ────────────> signed out, "Your session expired"
                           └ valid ─ GET /auth/me ─ 200 ─> signed in
                                                  ├ 401 ─> clear, "Your session has ended"
                                                  └ network/timeout/5xx ─> keep token,
                                                        "We couldn't confirm your session" + Try again

Sign out ─ clear token and profile ─> /login, "You have signed out."
```

**Expiry.** A timer fires at the token's expiry time. The time is re-checked when the
tab becomes visible or focused again (browsers slow timers in background tabs) and
before every request. An expired token is never sent.

**401 handling.** Any request that carried the token and comes back 401
(`TOKEN_EXPIRED`, `INVALID_TOKEN`, or a user who was deactivated) clears the session.
Sign-in failures (`INVALID_CREDENTIALS`) never do, because login requests carry no token.

## Architecture

| File | Role |
| --- | --- |
| `src/services/tokenStore.js` | The only code that touches `sessionStorage`. Stores `{ accessToken, expiresAt }` under one key and deletes malformed values |
| `src/services/apiClient.js` | Adds `Authorization: Bearer …` only to requests under `VITE_API_BASE_URL`. Reports 401s on authenticated requests. Keeps 422 `details`. Error `cause` is sanitised |
| `src/services/authService.js` | The three endpoints. Request bodies are built from explicit keys only (the backend rejects unknown fields) |
| `src/context/AuthProvider.jsx` | The single owner of auth state: `status`, `user`, `endedReason`, `error`, `login`, `register`, `logout`, `retry` |
| `src/context/authContext.js` | `useAuth()` and the session-ended messages |
| `src/components/auth/RouteGuards.jsx` | `RequireAuth` and `GuestOnly` layout routes |
| `src/components/auth/AuthNav.jsx` | Header actions |
| `src/pages/auth/*`, `src/pages/AccountPage.jsx` | Pages |
| `src/utils/authValidation.js` | Client rules mirroring `backend/app/schemas/auth.py` |
| `src/utils/formErrors.js` | Maps 422 details and 409 codes to fields |
| `src/utils/authPaths.js` | Route paths and the safe return-path check |

`status` is one of `restoring`, `authenticated`, `unauthenticated` or `error`. The
provider never navigates; the route guards react to `status`.

## Token storage decision

The token is kept in **`sessionStorage`**, following P-1 decision D12 and the way P-6 issues tokens: a bearer
token in the response body, `allow_credentials=False`, no refresh token.

| Option | Verdict |
| --- | --- |
| Memory only | Rejected: lost on every refresh, and there is no refresh token to recover with |
| **`sessionStorage`** | **Chosen.** Survives refresh, limited to one tab, cleared when the tab closes, works across the Vercel and Render domains |
| `localStorage` | Rejected: persists across browser restarts and on shared computers, with no benefit for a 30-minute token |
| httpOnly cookie | Not possible without backend changes (Set-Cookie, CSRF protection, credentialed CORS, same-site hosting). This is the upgrade path |

**Risk:** script injected by an XSS bug could read `sessionStorage`. These measures
reduce that risk:

- React escapes output. A test fails if `dangerouslySetInnerHTML` or `innerHTML` is used.
- Tokens are short-lived (30 minutes).
- The token is sent only to the API origin and path, never to `/health` or another domain.
- Tokens are never logged or put in URLs or router state.
- A strict Content-Security-Policy is still to come (see Deployment requirement below).

### What is never stored or exposed

- **Passwords.** They exist only in form state while typing and in the request body.
  They are not prefilled after registration, and they are cleared after a wrong
  sign-in. Tests check `sessionStorage`, `localStorage` and history state.
- **The user profile.** It is held in memory and fetched from `/auth/me` again after a
  refresh.
- **JWT secrets.** The frontend has no signing key and reads only `VITE_API_BASE_URL`.
  The token is opaque here and is never decoded.
- **Credentials in errors.** `ApiError.cause` is `{ name, code, message }`, not the Axios
  error. The Axios error contains the request body (the password) and headers (the
  token), and errors can reach `console.error`. This was fixed first in P-8.

## Validation

The client rules match the backend, so most mistakes are caught before a request is
sent. The backend still validates everything, and its 422 messages appear on the
matching fields.

| Field | Rule |
| --- | --- |
| Full name | Required, up to 100 characters; repeated spaces are collapsed |
| Email | Required; trimmed and lowercased; `name@domain.tld`, up to 254 characters |
| Mobile number | **Optional.** Spaces and hyphens are removed. A 10-digit Indian mobile number (starting 6–9) is sent as `+91XXXXXXXXXX`, and `+91XXXXXXXXXX` is accepted as is. Other international numbers must start with `+` (8–15 digits) and are never rewritten. Anything else is rejected with a message |
| Password (register) | 10–128 characters (counted as the backend counts them), not only spaces, not the same as the email. **Never trimmed** |
| Confirm password | Must match exactly. It is never sent to the backend |
| Password (sign in) | Required, up to 128 characters. Registration rules are not repeated, as in the backend |

**How errors are shown:**

| Error | Where it appears |
| --- | --- |
| 409 `EMAIL_ALREADY_REGISTERED` / `PHONE_ALREADY_REGISTERED` | On the email or mobile field, which receives focus |
| 401 `INVALID_CREDENTIALS` | One generic message. The backend uses it for wrong passwords, unknown emails and locked accounts alike |
| 5xx, network failure, timeout | A form-level alert with the server's message and, for server-side failures, a request reference |

**Accessibility:**

- Labels, hints and errors are wired with `aria-describedby`, and invalid fields get `aria-invalid`.
- Focus moves to the first invalid field.
- Alerts use `role="alert"` (errors) or `role="status"` (notices).
- The submit button shows a busy state and can't be pressed twice.
- Fields carry `autocomplete` values: `name`, `username`, `tel`, `current-password` and `new-password`.
- The show/hide toggle is a real button with `aria-pressed`.

## Testing

```powershell
cd frontend
npm test
```

| File | Covers |
| --- | --- |
| `services/apiClient.test.js` | No password or token in `ApiError`; P-3 error mapping unchanged; 422 `details` |
| `services/tokenStore.test.js` | `sessionStorage` only, malformed values, expiry, memory fallback |
| `services/authService.test.js` | Exact endpoints and request bodies; bearer only to the API; 401 clears the session, network errors and 5xx do not |
| `context/AuthProvider.test.jsx` | Restore, StrictMode, 401 vs network failure, retry, login, logout, timer and visibility expiry |
| `components/auth/routing.test.jsx` | Guards, return path, redirects for signed-in users, loading and error states, sign-out |
| `pages/auth/auth-pages.test.jsx` | Both forms, PasswordInput, backend errors, the account page |
| `utils/auth-utils.test.js` | Validation incl. phone normalisation, error mapping, safe return paths |
| `auth-security.test.js` | Source guards: no `localStorage`, no logging in auth code, no raw HTML, only the three endpoints, no JWT secret |

### Manual check (PowerShell, both servers running)

1. Open http://localhost:5173/account. You are sent to **Sign in**.
2. **Create an account.** Use a 10-digit mobile number such as `98765 43210`; it is stored as `+919876543210`.
3. You land on **Sign in** with "Account created" and your email filled in. Sign in.
4. You land on the **Dashboard**. Open **Account** to see your profile. Refresh the
   page: you stay signed in.
5. In DevTools → Application → Session storage you see one key, `sakshampay.session`.
   Local storage is empty.
6. **Sign out**, then press Back. You stay on **Sign in**.
7. Optional: to see expiry, start the backend with a 1-minute token, sign in and wait a
   minute. The page returns to **Sign in** with "Your session expired."

   ```powershell
   $env:ACCESS_TOKEN_EXPIRE_MINUTES="1"; uvicorn app.main:app --reload
   ```

## Limitations

- **Sign-out is client-side only.** P-6 has no logout endpoint (P-1 planned
  `POST /auth/logout`). A token copied before sign-out stays valid on the server until
  it expires, at most 30 minutes. Server-side revocation needs a backend change.
- **No refresh tokens.** The session ends at 30 minutes even mid-task. The user signs
  in again and returns to the page they were on, but anything unsaved on it is lost.
- **One session per tab.** Signing out in one tab doesn't sign out another, and a new
  tab needs a new sign-in. Duplicating a tab copies its session.
- **No "Forgot password".** There is no reset endpoint.
- **Locked accounts look like wrong passwords.** This is deliberate in the backend.
- **Validation rules exist twice.** If backend rules change,
  `src/utils/authValidation.js` must change too. Backend 422 errors are still shown if
  the two disagree.

## Deployment requirement: Content-Security-Policy

A strict CSP is part of the P-1 security design and is what limits the XSS risk of
`sessionStorage`. It is **deferred** until the real Render API domain and Vercel
domain are known, because `connect-src` must name the API origin exactly; a wildcard
such as `*.onrender.com` would weaken it. At deployment, add to the `headers` in
`frontend/vercel.json`:

```text
Content-Security-Policy:
  default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:;
  font-src 'self'; connect-src 'self' https://<render-api-domain>; object-src 'none';
  base-uri 'self'; form-action 'self'; frame-ancestors 'none'
```

This policy was checked locally against the P-8 production build (with `connect-src`
pointing at the local API): no violations, and the self-hosted font loads. The build
has no inline scripts or styles. Then confirm in the deployed site that sign-in, refresh and the API status panel still
work, and that the browser console shows no CSP violations. Also set the backend's
`FRONTEND_ORIGIN` to the Vercel domain.
