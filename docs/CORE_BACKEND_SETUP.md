# Career Agency Core Backend — Setup and Verification

## Current implementation scope

The rebuild branch now contains an additive core backend module connected from the existing `app.py`.

Implemented foundation:
- Auth-first dark sign-in screen and session-based sign-in API.
- SQLite core schema with `users.credits`, credit ledger, action-price registry, packages, Paystack payment records, webhook events, AI request records and `llm_cache`.
- Base action costs: Chat 5, CV 25, Mock Interview 50, Workspace 72.
- Cache lookup before wallet debit and before external AI execution.
- CV cache-hit price of 10 credits instead of 25.
- Configurable server-side AI adapter; provider failures trigger an idempotent refund.
- Paystack initialization and signature-checked `charge.success` webhook with server-side transaction verification.
- Existing legacy routes are isolated by default while ownership migration is pending.
- Flask debug mode is disabled by default.

Not yet complete:
- Email delivery and email-verification token lifecycle.
- Full mobile bearer/refresh-token authentication.
- CSRF token lifecycle for browser mutations.
- Full role-specific business APIs and all domain tables from the schema document.
- Complete LLM provider-specific adapter and production prompt registry.
- Full package catalogue between the two supplied endpoint prices.
- Live Paystack sandbox verification and end-to-end payment test.
- Migration/reconciliation of existing `job_agent.db` records.
- Production deployment, PostgreSQL migration, Redis/worker and object-storage integration.
- Full regression/security suite for every legacy feature.

## Pricing data boundary

The latest business instruction confirms only:
- ₦500 = 100 credits.
- ₦200,000 = 120,000 credits.

The package rows are created but inactive. This is intentional: the intermediate tiers were not supplied, so the API does not publish guessed packages and checkout cannot be initialized for them. The full approved tier list must be supplied before packages are activated.

## Local Termux setup

1. Pull the `career-agency-production-rebuild` branch.
2. Install the existing requirements:

   ```bash
   pip install -r requirements.txt
   ```

3. Set environment variables in the Termux shell. Use `.env.example` as a reference; the application does not load a `.env` file automatically.

   ```bash
   export CAREER_AGENCY_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
   export CAREER_AGENCY_CORE_DB="career_agency_core.db"
   export FLASK_DEBUG=0
   export HOST=127.0.0.1
   export PORT=5000
   ```

4. Start the app:

   ```bash
   python app.py
   ```

5. Open `http://127.0.0.1:5000/`. An unauthenticated request is redirected to the dark sign-in screen at `/auth/login`.

Do not set `CAREER_AGENCY_ENABLE_LEGACY_ROUTES=1` on a public deployment. The legacy workspace contains routes whose data ownership must be migrated and verified first.

## AI provider adapter

Configure `CAREER_AGENCY_LLM_ENDPOINT` to a trusted server-side endpoint that accepts JSON:

```json
{
  "action": "cv",
  "model": "server-default",
  "input": {
    "document_id": "..."
  }
}
```

The adapter must return a JSON object. Optional `CAREER_AGENCY_LLM_API_KEY` is sent as a Bearer token. Do not put provider keys in the browser, source files or SQLite settings table. This generic adapter is an integration seam, not a claim that a particular Gemini/OpenAI provider is already configured.

## Paystack

Set `PAYSTACK_SECRET_KEY` only in a protected server environment. Configure the Paystack webhook URL to:

`https://YOUR_DOMAIN/api/v1/payments/paystack/webhook`

Use Paystack test credentials and test transactions first. Do not activate packages or accept live payments until the complete package catalogue, webhook replay tests, amount/currency validation and sandbox-to-live configuration review are complete.

## Tests

The branch includes a GitHub Actions workflow that compiles `app.py` and `career_agency_core.py` and runs `tests/test_core_api.py` on pushes to the rebuild branch.

Run locally:

```bash
python -m py_compile app.py career_agency_core.py
python -m pytest -q tests/test_core_api.py
```

A passing core test workflow is not equivalent to a full regression test of the existing 8,500-line legacy application or a production security review.
