# Payments and risk assessment (P-10 backend)

> **Simulated payments only.** SakshamPay is not connected to UPI, NPCI, any bank or any
> payment app. "Approved" means approved in the simulation; no money moves. Do not enter
> real bank or UPI details: payees are fictional.

P-1 (the approved architecture) is authoritative. This page records how P-10 implements
it, and every place where P-1 left a definition open and the reading that was approved
for P-10.

## Endpoints

All require `Authorization: Bearer <token>`. Requests forbid unknown fields, so a client
cannot send a status, score, level or allowed actions.

| Endpoint | Purpose |
| --- | --- |
| `GET /api/v1/beneficiaries` | Your active payees, newest first. Identifiers are masked. |
| `POST /api/v1/beneficiaries` | Add a payee with a UPI ID **or** an account reference (plus optional bank name). Stores only a mask and a keyed fingerprint. Duplicate → 409 `BENEFICIARY_ALREADY_EXISTS`. |
| `POST /api/v1/transactions` | Start a payment and assess it. Headers `Idempotency-Key` and `X-Device-Id` are required. 201 on first use; 200 with the stored payment when the same key and body are sent again; 409 `IDEMPOTENCY_KEY_REUSED` for the same key with a different body. |
| `GET /api/v1/transactions/{id}` | One of your payments and its assessment. Applies lazy expiry. |
| `POST /api/v1/transactions/{id}/actions` | `CANCEL`, `CONTINUE` (with `confirmed: true` for MEDIUM) or `VERIFY` (with `password`). The only way to change a payment's status after assessment. |

Timestamps in every response are UTC with a `Z` suffix and keep their microseconds
(`2026-11-13T11:59:57.827761Z`), including idempotent replays and repeated actions; see
[`database-operations.md`](database-operations.md#10-time-zones).

Limits: ₹1 to ₹1,00,000 per payment (`MAX_TRANSACTION_AMOUNT_PAISE`, default
10,000,000 paise), integer paise only, description up to 80 plain-text characters. There
is no simulated balance.

Errors use the standard envelope. Payment-specific codes: `AMOUNT_OUT_OF_RANGE` (422),
`BENEFICIARY_NOT_FOUND` (404, also for inactive or another user's payee),
`TRANSACTION_NOT_FOUND` (404, also for another user's payment), `CONFIRMATION_REQUIRED`
(400), `STEP_UP_REQUIRED` (403, CONTINUE on HIGH), `VERIFICATION_FAILED` (403, with
`context.attempts_remaining` and `context.status`), `ACTION_NOT_ALLOWED`,
`INVALID_STATE_TRANSITION`, `TRANSACTION_EXPIRED` (409), `TOO_MANY_VERIFICATION_ATTEMPTS`
(429), `SERVICE_BUSY` (503: a lock was not granted within 2 seconds; nothing was paid or
changed, and retrying with the same `Idempotency-Key` is safe).

## Lifecycle

```
POST /transactions
  txn 0: stale-state sweep                                         commit
  txn 1: per-user creation lock (first statement) → idempotency
         re-check → initiated_at = clock_timestamp() →
         INITIATED + audit                                         commit (releases the lock)
  txn 2: lock row → features → rules → (no ML) → score/level →
         risk_assessments row → ANALYSED → AWAITING_USER_ACTION
         (expires_at = now + 10 min) → audit rows → alert           commit (all or nothing)
  on any error in txn 2: roll back, then INITIATED → FAILED + audit + alert

POST /transactions/{id}/actions
  lock row → expiry check → state check → allowed-actions check →
  CANCELLED | APPROVED | (failed VERIFY: counter, 3rd failure → CANCELLED) → audit → alert
```

* `TransactionService` is the only caller of `TransactionRepository.transition`; the
  repository state machine and the database CHECK constraints enforce the same rules.
* `APPROVED` is reachable only from `AWAITING_USER_ACTION`, which exists only after a
  stored assessment, and only through an explicit `CONTINUE` (LOW, or MEDIUM with
  `confirmed: true`) or a successful `VERIFY`. An assessment failure always ends in
  `FAILED`.
* The decision window is 10 minutes for every level. Past it, the payment becomes
  `EXPIRED` when it is next read or acted on, or by the sweep.
* **Sweep.** Each `POST /transactions` runs a bounded sweep (50 + 50 rows, all users):
  `AWAITING_USER_ACTION` past `expires_at` → `EXPIRED`; `INITIATED` older than 2 minutes →
  `FAILED`. It uses `FOR UPDATE SKIP LOCKED`, so it never waits for or overrides a request
  that holds a row. A sweep failure is logged and never blocks the payment. Reads and
  actions settle only the payment they touch. The P-9 dashboard stays read-only: it does
  not sweep (a deliberate change from P-1, which also sweeps on dashboard load).
* **Repeats.** Repeating the action that produced the current state returns 200 with that
  state; any other action on a finished payment is 409: `TRANSACTION_EXPIRED` for an
  expired payment (whether this request, an earlier read or the sweep expired it),
  otherwise `INVALID_STATE_TRANSITION`.
* **Logging (P-1 observability).** Each assessment writes one structured log line,
  "Payment assessed", with `request_id`, `transaction_id`, `assessment_ms`, `ml_available`,
  `risk_level` and `outcome` (`AWAITING_USER_ACTION` or `FAILED`). It contains no amount,
  payee, device or feature value. Replays do not log a new assessment.
* **Concurrency.** Row locks (`SELECT … FOR UPDATE`) plus the `version` column serialise
  actions on one payment; the loser sees the finished state. `VERIFY` also locks the user
  row so the per-account failure limit is counted exactly. Lock order is always
  transaction row → user row → network lock (`VERIFY` only).
* **Creation lock (R3 under concurrency).** The creation transaction (txn 1) starts with a
  transaction-scoped advisory lock keyed on the user
  (`pg_advisory_xact_lock(51001, hashtext(user_id))`) and takes `initiated_at` from
  PostgreSQL's `clock_timestamp()` while holding it. One user's creation transactions
  therefore commit in `initiated_at` order, so when a payment is assessed every earlier
  attempt is committed and visible: the n-th attempt counts exactly n−1 earlier ones,
  whichever assessment finishes first. (Without the lock, a request that took its time
  first but committed last was counted by nobody, and counted nobody.) Properties:
  * held for the short txn 1 only (sweep excluded, assessment excluded); other users use
    other keys and never wait; a hash collision only causes a brief wait;
  * idempotency: the key is re-checked under the lock, so same-key requests run one after
    another and the second replays the first; the unique `(user_id, idempotency_key)`
    index remains the backstop; the lock is released before a replay waits for the
    stored payment;
  * no deadlock: it is the first lock of its transaction, and nothing that holds a row
    lock ever waits for it;
  * a wait longer than 2 seconds (`lock_timeout`) returns 503 `SERVICE_BUSY` with nothing
    written.

## Verification (step-up)

`VERIFY` re-checks the account password with the existing Argon2id verifier. There is no
simulated OTP. Three wrong passwords on one payment cancel it (P-1) and raise an alert.
The password is never stored, logged, audited or echoed.

P-1: "Login and Verify attempts are rate-limited per account and IP prefix."

* **Per account (always on).** Five failed verifications per user in 15 minutes return 429
  `TOO_MANY_VERIFICATION_ATTEMPTS`, even for the right password. Counted from
  `VERIFICATION_FAILED` audit rows under the user row lock, so it holds across payments
  and processes.
* **Per network (implemented, OFF by default).** With `VERIFY_PREFIX_LIMIT_ENABLED=true`,
  20 (`VERIFY_PREFIX_FAILURE_LIMIT`) failed verifications from **all accounts** on one
  network (IPv4 /24, IPv6 /48) in 15 minutes return the same 429. No new data is stored:
  each `VERIFICATION_FAILED` audit row already holds the truncated network
  (`audit_logs.ip_address`), never the full address. Order of work in `VERIFY`:
  1. lock the payment row, then the user row; per-account check;
  2. unlocked early check of the network count (saves an Argon2 run when already blocked);
  3. Argon2 password check, with no network lock held;
  4. `pg_advisory_xact_lock(51002, hashtext(network))`, recount, and if at the limit refuse
     with 429 **whatever the password was** (so the limit never reveals a right guess) and
     record nothing; otherwise approve or record the failure; commit releases the lock.

  Counting and recording happen under one lock, so concurrent failures from different
  accounts on one network are counted exactly and the limit is never exceeded. The lock
  is held for a count and an insert, not for Argon2. Requests whose address is unknown or
  invalid are never pooled together (the limit is skipped for them; the per-account limit
  still applies). The 429 does not say which limit applied and never contains an address.
  IPv4-mapped IPv6 addresses (`::ffff:203.0.113.57`) are treated as the IPv4 address they
  carry; before this fix every such client was truncated to the same `::/48`.
* **Trade-off.** Someone on a shared network (campus, mobile carrier NAT) can block
  verification for others on it for 15 minutes. They can still Cancel; MEDIUM payments can
  still Continue with confirmation.

**Why it is off by default, and how to turn it on.** Uvicorn trusts `X-Forwarded-For` only
from `FORWARDED_ALLOW_IPS` (default `127.0.0.1,::1`). Behind Render's proxy the app
therefore most likely sees the proxy's address for every client (see also
[`authentication.md`](authentication.md#known-limitations-v1)). With the limit on, all users
would share one network and one attacker could block verification for everyone. Before
setting `VERIFY_PREFIX_LIMIT_ENABLED=true` in production:
1. set `FORWARDED_ALLOW_IPS` on Render to the addresses its proxy connects from (`*` only
   if the service cannot be reached except through Render's proxy; otherwise clients can
   spoof `X-Forwarded-For` to evade the limit or to block another network);
2. verify it: make a failed verification from two different networks (for example Wi-Fi
   and mobile data) and check that the two `VERIFICATION_FAILED` audit rows hold
   different `ip_address` networks, neither of them the proxy's.

**Login.** P-1 asks for the same two limits on login. The per-network login limit is
implemented the same way, also off by default
([`authentication.md`](authentication.md#login-limit-per-network-p-1-per-account-and-ip-prefix)).
P-1's rate-limiting requirement is met in code; the per-network halves are active only
once enabled.

## Risk engine

Pure functions in `app/fraud_detection/` (no database access); only
`app/services/feature_extraction.py` reads history. All numbers live in the versioned
`RISK_CONFIG` (`risk-config-v1`), which every assessment records.

### Rules-only mode

No anomaly model exists yet. `ml.UnavailableScorer` reports "unavailable" on every call,
so every assessment runs in P-1's rules-only mode: `S = R`, `ml_score`, `model_version`
and `ml_details` are NULL, and LOW is raised to MEDIUM. No ML score is produced or
imitated anywhere. A scorer that raises is treated the same way (rules-only, never a
failed payment).

### Score and level when the level is raised

The database ties `final_risk_score` to the scores (`final = rule_score` when
`ml_score IS NULL`) but **not** to the risk level: there is no CHECK linking
`risk_level` to the score band, and `RiskAssessmentRepository.create` takes the level from
the caller. So a payment where no rule fired is stored honestly, without invented points
and without a migration:

| Column | Value |
| --- | --- |
| `rule_score`, `final_risk_score` | 0 |
| `ml_score`, `model_version`, `ml_details` | NULL |
| `risk_level` | MEDIUM |
| `rule_details` (last entry) | `{"summary": true, "raw_points_total": 0, "band_level": "LOW", "risk_level": "MEDIUM", "level_raised_from": "LOW", "ml_unavailable_reason": "MODEL_NOT_IMPLEMENTED", …}` |
| `explanation` | ends with the `LIMITED_ASSESSMENT` factor |

The audit log has an `ML_UNAVAILABLE` event (`reason`, `mode: rules_only`) for the
payment, and the API returns `level_raised_from: "LOW"` and `ml_available: false`, so a
client never has to infer the level from the score. Any later consumer that derives a level
from a score (charts, statistics) must use the stored `risk_level`, not the band.

### R1–R6 against P-1

"History" = the user's **approved** payments initiated in the **90 days** before this
payment (P-1: feature extraction loads "the user's 90-day history"). **Cold start** = fewer
than 5 of them. One clause reads further back: R6's dormant clause (below). Thresholds
are strict (`>`, `<`) where P-1 says "over", "above" or "under"; time windows include
their start.

| Rule | Points | P-1 trigger | As implemented | Cold start |
| --- | --- | --- | --- | --- |
| R1 New beneficiary | 20 (P-1) | First payment to this beneficiary, or added less than 24h ago | No earlier APPROVED payment to this payee (any date), **or** payee `created_at` < 24 h before the payment | Same (needs no baseline) |
| R2 Unusual amount | 25 (P-1) | Amount over 3× the user's median and above their 95th percentile; cold start: above ₹25,000 | `amount > 3 × median` **and** `amount > p95` over history | `amount > ₹25,000` (P-1) |
| R3 Velocity | 20 (P-1) | 3 or more payments in 10 minutes, or 24h total over 3× typical, or same payee and amount within 5 minutes | (a) this payment is at least the 3rd **attempt** (any status) in 10 min; (b) (approved in last 24 h + this amount) > 3 × typical daily total; (c) an earlier attempt (any status) to the same payee for the same amount in 5 min | (a) and (c) apply; (b) **not evaluated** |
| R4 Unusual timing | 10 (P-1) | Hour in which the user made under 5% of past payments | Share of history in the same IST clock hour < 5% | 00:00 ≤ IST time < 05:00 (P-1) |
| R5 Device/session | 15 (P-1) | New device, or payment within 60s of login on a new device | Device hash not on any of the same user's **APPROVED** payments initiated in the 30 days before this one. "Within 60 s of login" only adds detail (see below) | Same |
| R6 Behavioural deviation | 15 (P-1) | New beneficiary combined with an unusual amount, or a dormant account (30+ days idle) paying above its 90th percentile | (a) R1 and R2 both fired; or (b) ≥ 30 days since the last approved payment (any date) **and** amount > p90 of the user's **lifetime** approved payments, which must number at least 5 | (a) applies; (b) applies whenever there are ≥ 5 lifetime approved payments, in or out of cold start |

`R = min(100, sum of points)`; the raw total (up to 105) is kept in `rule_details`. Bands
LOW 0–30, MEDIUM 31–65, HIGH 66–100. Allowed actions: LOW `CONTINUE, CANCEL`; MEDIUM
`CONTINUE, VERIFY, CANCEL` (Continue needs `confirmed: true`); HIGH `VERIFY, CANCEL`.
P-1's worked example (new payee, ₹48,000 at 2:40 AM → R1, R2, R4, R6 = 70) is a test.

### Definitions P-1 does not give, and the reading used

Each is a configuration value or a documented choice, not a hidden rule. Items marked
**approved** were approved for P-10; the others are flagged for review.

| # | Open point in P-1 | Reading in `risk-config-v1` | Status |
| --- | --- | --- | --- |
| 1 | Which past payments form a baseline, and over what window | Approved payments, previous 90 days | approved |
| 2 | "Fewer than 5 past transactions" (cold start): which transactions | Approved payments in the same 90-day window | follows 1; review |
| 3 | "3 or more payments": attempts or approvals; does the current one count | Every attempt in any status; the current attempt is at least the 3rd | approved |
| 4 | "Typical daily total" | Average total per active IST day over history | approved |
| 5 | Median / percentile method | Linear interpolation (numpy's default) | review |
| 6 | Population baselines for cold start | P-1 gives only ₹25,000 (R2) and 00:00–05:00 (R4). R3(b) and R6(b) are skipped in cold start rather than invented | review |
| 7 | Hour granularity for "hour in which" | IST clock hour (e.g. 02:00–02:59) | review |
| 8 | Where device history comes from; "seen" means what | The same user's earlier **APPROVED** transactions' `device_id_hash`, initiated in the last 30 days (P-1 D11: no device table). INITIATED, FAILED, ANALYSED, AWAITING, EXPIRED and CANCELLED (including cancellation after three wrong passwords) never make a device known: none of them is a completed assessment plus an explicit user approval. Audit logs hold no device ID, so they add nothing here | approved |
| 9 | Missing device ID | Request rejected (422); the header is required | approved |
| 10 | "Within 60s of login": login time source | `users.last_login_at` (last successful login) | review |
| 11 | R5 second clause | Redundant: "on a new device" is already covered by the first clause, so it never adds points | P-1 wording; review |
| 12 | R6 "new beneficiary" and "unusual amount" | R1 fired and R2 fired (including R1's "added < 24 h" branch) | review |
| 13 | "Dormant": idle since what | Days since the last approved payment, at any date; needs existing history | approved |
| 14 | R6 90th percentile window | The user's **lifetime** approved payments (one `percentile_cont(0.9)` aggregate, no row cap), at least 5 of them (P-1's personal-baseline minimum). A dormant account's own payments lie before the idle gap, usually outside the 90-day window, so the 90-day history would make the clause blind to users idle for more than 90 days. Cold start and R2/R3/R4 baselines still use the 90-day history | approved (deliberately beyond P-1's literal "90-day history") |
| 15 | Recommended action for LOW | `CONTINUE` (P-1 names MEDIUM → Verify, HIGH → Cancel only) | review |
| 16 | Verify rate limit numbers | 5 failures per user per 15 min (same as login lockout) | approved |
| 17 | P-1 limits Login and Verify per **IP prefix**; no numbers given | Verify and login: 20 failures per network per 15 minutes each, implemented and **off by default** until client IP forwarding is verified | Verify approved; login implemented with the same numbers (review) |
| 18 | Rule weights total 105 | Unchanged; capped at 100; raw total stored | P-1 open issue |
| 19 | Features P-1 lists but no rule uses (`amount_z_user`, `amount_vs_p95`, `txn_count_1h`) and ML-only features | Not computed until the model exists | review |

### Explanations

Each fired rule gives a factor with a plain label, a detail sentence and its points. P-1
asks for the user's own baseline next to the current value ("₹48,000 is about 6× your
typical payment of ₹7,700"), so R2 and R3(b) details show the user's median or usual daily
total. Details never state the thresholds (3×, 95th percentile, 5%, ₹25,000, 30 days).
Copy says "unusual" or "higher risk", never "fraud". `LIMITED_HISTORY` (cold start) and
`LIMITED_ASSESSMENT` (rules only) are `system` factors with no points.

Never returned by the API: `features_snapshot`, `rule_details` (observed values), request
hash, idempotency key, device ID or its hash, full payee identifiers, passwords.

## Privacy

* UPI IDs and account references are masked and fingerprinted (HMAC-SHA-256 with
  `IDENTIFIER_HASH_KEY`) before they reach the repository; the raw value is never stored,
  logged, audited or echoed in validation errors.
* The device ID is a random, non-secret browser identifier; only its keyed hash is stored.
* IP addresses are stored only as truncated networks in audit rows (IPv4 /24, IPv6 /48;
  IPv4-mapped IPv6 as its IPv4 /24). The per-network Verify limit compares networks only;
  no address appears in responses or logs (the Uvicorn access log is disabled).
* Without `IDENTIFIER_HASH_KEY`, adding payees and making payments fail with
  `CONFIGURATION_ERROR` and nothing is stored; startup logs a warning.

## Known limitations

* **Rules only.** Every payment is at least MEDIUM, and every MEDIUM/HIGH assessment
  creates a `RISK_WARNING` alert (P-1), so every payment currently has an alert.
* **Returning users are in cold start.** A user with no approved payment in 90 days gets
  the "still learning your patterns" factor and R2's ₹25,000 cold-start threshold, however
  long their earlier history. Only R6's dormant clause uses lifetime history.
* **A device becomes known after one approved payment.** Someone holding a session on a
  new device can approve one small MEDIUM payment (with confirmation) to make the device
  known. That payment is assessed, audited and alerted. P-1 calls device anomaly a weak
  signal.
* **Velocity counts attempts, not approvals.** Every attempt in any status counts
  (approved reading). The creation lock makes the count exact under concurrency; the 24-hour
  total (R3) still reflects only approvals committed before the assessment runs.
* **Per-network Verify limit is off** until `FORWARDED_ALLOW_IPS` is set and verified on
  Render (see Verification above).
* **Per-network login limit is off** for the same reason (see Verification).
* The frontend payment flow is P-10 checkpoint 2 (not built yet).
