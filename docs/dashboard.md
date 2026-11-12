# SakshamPay dashboard (P-9)

The signed-in home page at `/dashboard`: the user's last 30 days at a glance. It is
backed by one new read-only endpoint, `GET /api/v1/dashboard/summary`. No migration,
table or index was added.

## What it shows, and what it deliberately does not

| Shown | Source |
| --- | --- |
| **Payments checked** | `transactions.total` |
| **Approved amount** (₹, simulated), with the number of approved payments | `transactions.approved_amount_paise`, `by_status.APPROVED` |
| **Needs your action** | `transactions.awaiting_action` |
| **Unread alerts** | `alerts.unread` |
| **Payments by status**: all seven stored states, including zeros, with proportion bars | `transactions.by_status` |
| An empty state for users with no payments in the window | `transactions.total == 0` |

| Not shown | Why | When |
| --- | --- | --- |
| Risk statistics (Low/Medium/High counts, risk trend, top factors) | The only stored assessments today are development-seed samples with hand-written scores. Showing them would present sample values as fraud-detection results | Once the risk engine and scoring pipeline produce real assessments |
| Recent transactions | Would duplicate the transaction history built in P-11 | P-11 |
| New payment button | Payment creation is P-10 | P-10 |

## API: `GET /api/v1/dashboard/summary`

- **Auth:** `Authorization: Bearer <token>`. The user is taken from the token
  (`CurrentUser`). The endpoint takes no parameters, so it cannot be pointed at another
  user's data; unknown query parameters are ignored.
- **Response headers:** `Cache-Control: no-store`.
- **Errors:** 401 `NOT_AUTHENTICATED` / `INVALID_TOKEN` / `TOKEN_EXPIRED`, and 503
  `DATABASE_UNAVAILABLE` / `DATABASE_NOT_CONFIGURED` / `AUTH_NOT_CONFIGURED`, in the
  standard `{"error": {...}}` shape.

```json
{
  "period": { "days": 30, "start": "2026-10-10T18:00:00Z", "end": "2026-11-09T18:00:00Z" },
  "transactions": {
    "total": 10,
    "by_status": { "INITIATED": 0, "ANALYSED": 0, "AWAITING_USER_ACTION": 1, "APPROVED": 7,
                   "CANCELLED": 1, "EXPIRED": 1, "FAILED": 0 },
    "awaiting_action": 1,
    "approved_amount_paise": 4459000
  },
  "alerts": { "unread": 3 }
}
```

### Definitions

| Figure | Definition |
| --- | --- |
| Window | Rolling: `end` is the time of the request (UTC) and `start = end − 30 days`. A transaction is in the window when `start <= created_at <= end`. This uses the existing `transactions(user_id, created_at)` index |
| `total` | The user's transactions created in the window, in any status |
| `by_status` | The **stored** status of each of those transactions. All seven keys are always present (0 when none) |
| `approved_amount_paise` | Sum of `amount_paise` of those transactions whose status is `APPROVED`, as an integer number of paise (0 when none) |
| `awaiting_action` | Those with status `AWAITING_USER_ACTION` whose `expires_at >= now`, i.e. the user can still decide. This is the same boundary as the expiry sweep (`expires_at < now` means expired) |
| `alerts.unread` | **All** of the user's alerts with `is_read = false`, at any date (not limited to the window) |

**Past their deadline but not yet swept.** A payment still stored as
`AWAITING_USER_ACTION` after its deadline is counted in
`by_status.AWAITING_USER_ACTION`, because that is its stored state. It is **not**
counted in `awaiting_action`, because the user can no longer act on it. The dashboard
says so: "1 payment awaiting your decision has passed its deadline and will be marked
as expired." The expiry sweep belongs to the transaction service (P-10/P-11).

### Read-only by construction: two sessions per request

```text
GET /api/v1/dashboard/summary
 1. CurrentUser       DbSession (get_db), unchanged P-6 dependency
                      token checked (no DB) → SELECT user → 401 here stops the request;
                      the read-only session below is never opened
 2. ReadOnlyDbSession get_read_only_db: a new session, own pooled connection
                      first statement: SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY
 3. DashboardService  checks SHOW transaction_read_only = on, then runs the aggregates
 4. request ends      both sessions closed (rollback, connection back to the pool),
                      on success and on any error
```

- **Separate session.** The dashboard's transaction is independent of the session
  `CurrentUser` used to load the user, so its characteristics are set before any query
  in *its* transaction. `CurrentUser` and every other endpoint are unchanged.
- **Enforced by PostgreSQL.** PostgreSQL accepts an isolation level only as the first
  statement of a transaction. If anything ever ran before it, the request fails loudly
  rather than silently running read-write. `READ ONLY` makes PostgreSQL reject every
  write; `REPEATABLE READ` gives all the figures in one response a single consistent
  snapshot.
- **The service refuses a read-write session** (`NotReadOnlySessionError`) and never
  commits.
- **Cost:** one extra pooled connection for the duration of a dashboard request.

Tests check this on the real endpoint against PostgreSQL:

- the authentication query runs first, on a different connection;
- the dashboard connection's first statement is the `SET TRANSACTION`;
- a write attempted inside the request is rejected by PostgreSQL;
- ten repeated requests change no rows;
- no pooled connection is left checked out and none is left idle in a transaction,
  after success, a service exception or a failed query;
- 401 requests never open the dashboard session.

### Backend files

| File | Purpose |
| --- | --- |
| `app/repositories/transactions.py` | `count_by_status`, `sum_amount` and `count_awaiting_action`, scoped by user and window |
| `app/database/session.py` | `get_read_only_db` / `ReadOnlyDbSession`: the separate REPEATABLE READ, READ ONLY session |
| `app/services/dashboard.py` | `DashboardService` (requires a read-only session, `WINDOW_DAYS = 30`) |
| `app/schemas/dashboard.py` | `DashboardSummary` (explicit status keys; unknown keys rejected) |
| `app/routes/dashboard.py` | The route: `CurrentUser`, then `ReadOnlyDbSession`; `Cache-Control: no-store` |
| `app/routes/__init__.py` | Registers the router under `/api/v1` |

## Frontend

| File | Purpose |
| --- | --- |
| `src/services/dashboardService.js` | `getDashboardSummary()`. It validates the response, so a missing or malformed figure becomes an error and is never shown as 0 |
| `src/hooks/useDashboardSummary.js` | Loading, ready and error states with `retry()`. The request is aborted on unmount (e.g. sign-out). Data is held in memory only |
| `src/pages/DashboardPage.jsx` | The page |
| `src/components/dashboard/KeyFigures.jsx` | One card with four figures: 4 columns from 1024 px, 2 from 640 px, 1 below |
| `src/components/dashboard/StatusBreakdown.jsx`, `statusLabels.js` | Seven status rows. The bars are decorative and use one neutral brand colour, because a status is not a risk level |
| `src/components/dashboard/DashboardEmpty.jsx`, `DashboardSkeleton.jsx` | Empty and loading states |
| `src/components/navigation/navItems.js`, `SignedInNav.jsx` | Signed-in navigation |
| `src/utils/format.js` | `formatNumber` (Indian grouping) and `formatDateRange` |

**States**

| State | What the user sees |
| --- | --- |
| Session check | The P-8 "Checking your session" message |
| Loading the summary | A skeleton in the card layout, with a screen-reader status ("Loading your summary") |
| Network error, timeout or 5xx | "We couldn't load your summary" with the server's message, a request reference for 5xx, and **Try again**. The session is kept |
| 401 | The session ends (P-8) and the user is sent to sign in. They return to `/dashboard` afterwards |
| Invalid response shape | Treated as an error ("could not be read"), never shown as zeros |

## Navigation

Top navigation, not a sidebar: P-1 rules out sidebars on the payment page, there are
few items, and P-11's history table needs the full width.

- **From 640 px:** Dashboard and Account links (`aria-current="page"` on the current
  one), then **Sign out**.
- **Below 640 px:** a **Menu** disclosure button (`aria-expanded`, `aria-controls`).
  The panel lists the same links, "Signed in as…" and **Sign out**. It closes on
  Escape (focus returns to the button), on a click outside, and after navigating.
- The logo links to `/dashboard` when signed in.
- Signed-in users land on `/dashboard`. `DEFAULT_SIGNED_IN_PATH` changed from
  `/account` to `/dashboard`; `/account` is unchanged, and returning to the
  originally requested page after sign-in still works.
- To add a page later, add one entry to `SIGNED_IN_NAV_ITEMS` and a route under
  `RequireAuth` in `src/routes.jsx`.

## Tests

```powershell
# backend, from backend\ (venv active)
pytest tests\test_dashboard_api.py
$env:TEST_DATABASE_URL="postgresql+psycopg://USER:PASSWORD@localhost:5432/DISPOSABLE_DB"; pytest tests\test_dashboard_postgres.py

# frontend, from frontend\
npm test
```

| File | Covers |
| --- | --- |
| `tests/test_dashboard_api.py` | 401 codes before any database access, response shape, all status keys, user from the token only, query parameters ignored, `no-store`, OpenAPI |
| `tests/test_dashboard_postgres.py` | Deactivated or unknown user, zero-transaction user, exact aggregates across all seven states, large amounts, user isolation, 30-day boundaries (both edges, to the microsecond), window vs. all-time unread alerts, past-deadline payment, deadline boundary equal to the sweep's, read-only session (isolation, write rejected, one snapshot, no commit, refuses read-write), the real endpoint's session lifecycle (statement order, separate connection, write rejected mid-request, no leaks on success or errors, 401 opens no session), seed users vs. the seed specification |
| `src/services/dashboardService.test.js` | Request, bearer token, 401/503/network, response validation, hook loading, retry and abort |
| `src/pages/dashboard.test.jsx` | Populated, empty and loading states, errors with retry, Indian formatting, past-deadline note, no risk or later-phase content, protected routing, abort on sign-out |
| `src/components/navigation/navigation.test.jsx` | `aria-current`, logo, phone menu (keyboard, Escape, focus, outside click, navigation, sign-out) |

## Known limitations

- **Seed data ages out.** Seed dates are relative to when `python -m seeds.dev_seed`
  ran, and re-running skips existing rows. After about a month the demo users'
  dashboards are empty. For a demo, seed a fresh database.
- **Seeded figures are samples.** Demo users' counts and amounts come from the
  development seed (fictional, simulated payments). Real users have no payments
  until P-10.
- **"Unread alerts" can't be opened yet.** The alerts page comes in a later phase.
- **"Needs your action" doesn't link anywhere yet.** The review screen comes with
  P-10/P-11.
- **No refreshing.** Figures are fetched when the page opens and on **Try again**,
  without polling.
- **Time zones differ by design.** The window is computed on the server in UTC; the
  date range shown uses the viewer's time zone.
