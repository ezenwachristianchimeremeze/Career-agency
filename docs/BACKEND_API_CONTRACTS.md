# Career Agency — Backend API Contracts

**Status:** Implementation contract for the rebuild branch  
**API style:** JSON REST under `/api/v1`; authenticated endpoints use server-owned identity.  
**Currency:** NGN; amounts are integer kobo in API payloads.

## 1. Global conventions

- Content type: `application/json`, except multipart uploads.
- Authentication: secure HttpOnly, Secure, SameSite session cookie for browser clients; short-lived access token plus rotating refresh token for native mobile if required. Never put long-lived tokens in localStorage.
- Every mutation accepts an `Idempotency-Key` header.
- Every response includes `request_id`.
- Error shape: `{ "error": { "code": "...", "message": "...", "field_errors": {} }, "request_id": "..." }`.
- Pagination uses `cursor` and `limit`; cap limit server-side.
- All user-owned records are scoped by authenticated user ID. Never accept a client-supplied owner ID as authority.
- RBAC and object-level authorization are checked on every request.
- Rate limits apply to login, password reset, AI actions, payment initialization, uploads and messaging.
- Do not expose stack traces, provider secrets, SQL, internal prompts or other users' records.

## 2. Authentication

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/auth/csrf` | Issue CSRF token for cookie-authenticated browser session. |
| POST | `/api/v1/auth/register` | Create pending account; validate role allowlist and consent. |
| POST | `/api/v1/auth/login` | Verify credentials; establish session. |
| POST | `/api/v1/auth/logout` | Revoke current session. |
| POST | `/api/v1/auth/refresh` | Rotate refresh token (native/mobile flow). |
| POST | `/api/v1/auth/verify-email` | Verify single-use email token. |
| POST | `/api/v1/auth/resend-verification` | Rate-limited resend. |
| POST | `/api/v1/auth/forgot-password` | Neutral anti-enumeration reset response. |
| POST | `/api/v1/auth/reset-password` | Consume single-use expiring token. |
| GET | `/api/v1/auth/me` | Return server-verified identity, role, profile summary and wallet balance. |
| GET | `/api/v1/auth/sessions` | List current user's sessions. |
| DELETE | `/api/v1/auth/sessions/{session_id}` | Revoke an owned session. |

Registration never permits a user to self-select `admin`. The first screen at the web root is the dark login screen; unauthenticated app routes redirect to it. The same auth-first experience is used in mobile.

### Login request
```json
{ "email": "person@example.com", "password": "user-entered-secret" }
```

### Login success
```json
{
  "data": {
    "user": { "id": "uuid", "full_name": "Example User", "role": "job_seeker", "email_verified": true },
    "wallet": { "credits": 0 }
  },
  "request_id": "req_..."
}
```

Do not return password hashes, verification tokens or internal permission details.

## 3. Wallet and package catalogue

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/v1/wallet` | Balance, purchased-credit total and usage summary. |
| GET | `/api/v1/wallet/ledger` | Paginated immutable ledger. |
| GET | `/api/v1/credit-packages` | Active, approved package catalogue only. |
| POST | `/api/v1/payments/paystack/initialize` | Initialize checkout for an active package. |
| GET | `/api/v1/payments/{reference}` | Return status for a payment owned by current user. |
| POST | `/api/v1/payments/paystack/webhook` | Provider webhook; signature and transaction verification required. |
| POST | `/api/v1/wallet/estimate` | Estimate a known action's current cost without charging. |

### Package catalogue response
Only active packages are returned. The two endpoint values provided by the owner are stored but remain inactive until the intermediate package schedule is confirmed:
```json
{
  "data": {
    "currency": "NGN",
    "packages": []
  },
  "request_id": "req_..."
}
```

Do not make up intermediate tiers or enable a guessed package schedule.

### Initialize Paystack payment
Request:
```json
{ "package_id": "package_uuid", "email": "verified-user@example.com" }
```
The server derives the user ID and package price from the database. It creates a cryptographically random reference and initializes Paystack with the exact integer kobo amount and metadata containing internal payment ID and user ID. It returns authorization URL, access code and reference. It never trusts a client-submitted amount or credit quantity.

### Paystack webhook contract
1. Read the exact raw request body.
2. Verify `x-paystack-signature` using HMAC-SHA512 and the server-held secret key; compare signatures in constant time.
3. Parse JSON only after signature validation.
4. Process only `event == "charge.success"`.
5. Verify the reference independently through Paystack's transaction verification endpoint using the secret key.
6. Require provider status `success`, expected currency `NGN`, exact expected amount in kobo, matching reference, and matching internal payment/user/package metadata.
7. In one database transaction, mark payment successful, add the package credits to `users.credits`, append one purchase ledger entry, and mark webhook event processed.
8. Enforce unique provider reference/transaction ID and idempotency. Repeated webhooks return HTTP 200 without a second credit.
9. Invalid signatures return 401; valid but irrelevant events are acknowledged safely; transient provider/database failures return retryable 5xx without crediting.
10. Never credit from the browser redirect alone.

## 4. AI action execution and cache-first charging

### Action keys and base prices
| Action key | Base cost |
|---|---:|
| `chat` | 5 |
| `cv` | 25 |
| `mock_interview` | 50 |
| `workspace` | 72 |

The action price table is server-controlled and versioned. The client may display an estimate but cannot choose or override the debit.

### Cache-hit discount
- The API canonicalizes action, model/provider version, prompt version, user/tenant visibility scope, locale and all response-affecting input fields.
- It computes a SHA-256 cache key.
- It queries the SQLite `llm_cache` table before charging and before calling an LLM provider.
- A valid cache hit returns the cached result after the configured discounted debit.
- The provided CV example is 10 credits on cache hit versus 25 on a miss.
- Other action cache-hit prices remain unset until approved. Do not silently assume 10 for every action.
- Expired or invalid cache rows are treated as misses.
- A cache entry containing private user material must be scoped so another user cannot receive it.

### Endpoint
`POST /api/v1/ai/actions/{action_key}`

Request:
```json
{
  "input": { "prompt": "..." },
  "model": "server-selected",
  "client_request_id": "optional-client-correlation-id"
}
```

Response:
```json
{
  "data": {
    "request_id": "ai_req_...",
    "cache": { "hit": true },
    "credits": { "charged": 10, "balance": 90 },
    "result": {}
  },
  "request_id": "req_..."
}
```

For a cache miss, `credits.charged` uses the base price. For a cache hit, it uses the configured discounted price. The backend checks balance and debits atomically using a unique idempotency key. No partial debit is allowed. If insufficient, return `402 INSUFFICIENT_CREDITS` with required and available amounts and no LLM call.

### Required execution sequence
1. Authenticate and authorize.
2. Validate request and action allowlist.
3. Resolve server-side model and prompt version.
4. Build canonical cache key.
5. Query SQLite `llm_cache` first.
6. Resolve cache-hit or base price from `credit_action_prices`.
7. Validate idempotency and balance.
8. Atomically debit and write ledger.
9. Cache hit: return stored result.
10. Cache miss: invoke provider outside the database transaction; save successful response to cache.
11. On provider failure, append a compensating refund ledger entry exactly once.
12. Record usage, latency and safe audit metadata.

The cache lookup must happen before the debit and external LLM request. The debit itself is committed atomically before returning a hit or starting a paid miss request. A repeated client retry must not cause a second debit.

## 5. Other job-seeker APIs

| Method | Endpoint | Purpose |
|---|---|---|
| GET/POST | `/api/v1/jobs` | Search jobs / create saved search as applicable. |
| GET | `/api/v1/jobs/{job_id}` | Job detail. |
| GET/POST/DELETE | `/api/v1/saved-jobs` | List, save and remove saved jobs. |
| GET/POST | `/api/v1/applications` | List and create application records. |
| GET/PATCH/DELETE | `/api/v1/applications/{id}` | Read/update/delete an owned application. |
| GET/POST | `/api/v1/cvs` | List/upload CV documents. |
| GET/PATCH/DELETE | `/api/v1/cvs/{id}` | Read/update/delete owned CV. |
| POST | `/api/v1/cvs/{id}/analyse` | Paid ATS analysis via AI action pricing. |
| POST | `/api/v1/cvs/{id}/tailor` | Paid CV tailoring via AI action pricing. |
| GET/POST | `/api/v1/interviews` | List/create interview events. |
| POST | `/api/v1/interviews/{id}/mock` | Mock interview action; 50-credit base price. |
| GET/PATCH | `/api/v1/profile` | Read/update own profile. |
| GET/POST | `/api/v1/notifications` | List/create permitted notifications. |
| POST | `/api/v1/support/tickets` | Create support ticket. |

## 6. Employer, recruiter and admin APIs

All endpoints require server-side role and permission checks.

- Employer: `/api/v1/employer/company`, `/jobs`, `/applicants`, `/candidates`, `/interviews`, `/team`, `/analytics`.
- Recruiter: `/api/v1/recruiter/clients`, `/candidates`, `/pipeline`, `/messages`, `/reports`.
- Admin: `/api/v1/admin/overview`, `/users`, `/employers`, `/recruiters`, `/jobs`, `/moderation`, `/credits`, `/payments`, `/audit`, `/system-health`, `/settings`.

Admin credit adjustment requires a reason, step-up authentication and audit record. High-impact operations should require a second approver.

## 7. Standard status and error codes

- 400 `VALIDATION_ERROR`
- 401 `UNAUTHENTICATED`
- 403 `FORBIDDEN`
- 404 `NOT_FOUND` (also used to avoid leaking existence)
- 409 `CONFLICT` / `IDEMPOTENCY_CONFLICT`
- 402 `INSUFFICIENT_CREDITS`
- 422 `BUSINESS_RULE_VIOLATION`
- 429 `RATE_LIMITED`
- 502 `AI_PROVIDER_ERROR`
- 503 `DEPENDENCY_UNAVAILABLE`

## 8. Security and operational requirements

- Password hashing with Argon2id or scrypt; never plain SHA-256.
- HTTPS only in production; secure cookies; CSRF protection for cookie-authenticated writes.
- Store Paystack secret key in environment/secret manager, never source control or database.
- Verify webhook HMAC and transaction server-to-server.
- Restrict CORS to configured client origins.
- Validate upload type, size, content and storage ownership.
- Audit all admin, payment, credit and permission mutations.
- Use request IDs, structured logs, redaction and rate limiting.
- Never trust browser redirect parameters, user IDs, action costs, credit quantities or roles.
