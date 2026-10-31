# Detailed Interaction Specification — Career Credits Wallet and Payments

**Scope:** WAL-01 to WAL-07 and the shared credit-confirmation dialog.  
**Commercial model:** prepaid credits only; no subscriptions or recurring billing.  
**Status:** Design specification only. Payment integration is not implemented.

## 1. Global wallet rules

- Users buy prepaid in-app Career Credits.
- Purchased credits never expire.
- No recurring billing or automatic renewal.
- Credits are not cash and are not withdrawable by default.
- Every purchase and debit has a unique reference and immutable ledger entry.
- Balance is calculated from the server-side ledger; the browser is never authoritative.
- The user sees the feature cost before confirming a paid AI action.
- Cancel means no debit.
- Double taps, retries and webhook retries must not create duplicate charges or credits.
- Provider redirect alone is not proof of payment; server verification is required.
- Failed or undelivered AI operations follow the published refund/retry rules.
- Promotional credits, if introduced, are separately labelled and have separately disclosed conditions.

## 2. WAL-01 — Wallet overview

### Desktop layout
- Page title "Career Credits".
- Main balance card at top left with available balance.
- Primary action Buy Credits.
- Secondary action Transactions.
- Summary cards: Total Purchased, Total Used, Promotional Credits (only if applicable).
- Lower section: Recent Activity with date, feature/purchase, debit/credit, status and reference.
- Right-side help card: how credits work, purchased credits do not expire, contact support.

### Mobile layout
- Balance card first.
- Full-width Buy Credits button.
- Transactions button.
- Compact summary cards in two columns.
- Recent Activity list.
- Help and policy links below.

### Buttons
**Buy Credits**
- Primary blue; tap → WAL-02.
**Transactions**
- Secondary; tap → WAL-04.
**View Usage**
- Link; tap → WAL-05.
**View All Activity**
- Tap → WAL-04 or WAL-05 with selected tab.
**How Credits Work**
- Opens explanatory page/section.
**Payment Help**
- → SUP-01 or ticket creation with wallet context.
**Activity row**
- Tap → WAL-06.
- Pending status stays visibly pending; do not represent it as completed.

### States
- New wallet: zero balance and clear Buy Credits CTA.
- Existing wallet: live verified balance.
- Loading: skeleton; never show invented balance.
- Offline: last known balance labelled with last sync time; paid actions disabled until server balance can be checked.
- Wallet unavailable: Retry and support route.

## 3. WAL-02 — Credit packages

### Layout
- Header: "Buy Career Credits".
- Short explanation: "Choose a one-time credit package. Purchased credits do not expire."
- Package grid: 2 columns mobile, 3–4 desktop.
- Every card hierarchy:
  1. Large bold quantity: e.g. **2,200 Credits**
  2. Bonus line: **+200 Bonus Credits** (only if applicable)
  3. Smaller Naira price: **₦2,000**
- Selected card has blue outline and checkmark.
- Bottom sticky summary on mobile; desktop summary panel or footer.
- Payment/credit terms link.

### Approved packages

| Price | Display quantity | Bonus line |
|---:|---:|---:|
| ₦200 | 200 Credits | No bonus |
| ₦300 | 300 Credits | No bonus |
| ₦500 | 500 Credits | No bonus |
| ₦1,000 | 1,100 Credits | +100 Bonus Credits |
| ₦2,000 | 2,200 Credits | +200 Bonus Credits |
| ₦3,000 | 3,300 Credits | +300 Bonus Credits |
| ₦4,000 | 4,400 Credits | +400 Bonus Credits |
| ₦5,000 | 5,500 Credits | +500 Bonus Credits |
| ₦10,000 | 11,000 Credits | +1,000 Bonus Credits |
| ₦15,000 | 16,500 Credits | +1,500 Bonus Credits |
| ₦20,000 | 22,000 Credits | +2,000 Bonus Credits |
| ₦30,000 | 33,000 Credits | +3,000 Bonus Credits |
| ₦40,000 | 44,000 Credits | +4,000 Bonus Credits |
| ₦50,000 | 55,000 Credits | +5,000 Bonus Credits |
| ₦100,000 | 110,000 Credits | +10,000 Bonus Credits |
| ₦200,000 | 220,000 Credits | +20,000 Bonus Credits |

Do not invent intermediate packages or change the approved 10% bonus schedule without approval.

### Buttons
**Package card**
- Entire card selectable; tap sets selected package and updates summary.
- It does not start payment.
**Continue**
- Primary; disabled until a package is selected.
- Tap → WAL-03 with package ID, amount and credit amount loaded from server.
**Back**
- Returns WAL-01.
**Credit Costs**
- Opens a read-only list of feature costs and indicates which are provisional/admin-configurable.

## 4. WAL-03 — Checkout

### Layout
- Order summary: package amount, base credits, bonus credits, total credits.
- Payment method/provider options supported by configured integration.
- User identity/email used for receipt, editable only after verification where needed.
- Clear one-time purchase notice.
- Checkbox for required terms acknowledgement if applicable.
- Primary Pay button and Cancel.

### Buttons
**Pay ₦X**
- Primary action.
- Tap creates a pending payment intent on server with unique idempotency key.
- Redirects/opens the configured provider checkout.
- Disable while intent is being created.
- Do not mark as paid from browser callback alone.

**Change Package**
- Returns WAL-02 and preserves no stale payment intent.
**Cancel**
- Returns WAL-02 or WAL-01; pending provider intent is handled as pending/cancelled according to provider response.
**Payment Terms**
- Opens LEG-04 / LEG-05.

### Failure handling
- Provider unavailable: show Retry or choose another supported method.
- User closes provider: show payment pending/unknown; verify status before offering retry.
- Network disconnect: retain transaction reference and check status; do not create another intent until prior state is resolved.
- Amount mismatch: reject crediting, flag reconciliation and notify operations.

## 5. WAL-07 — Payment result

### Success
- Show "Payment confirmed".
- Display amount paid, base credits, bonus credits, total credited, transaction reference and timestamp.
- Refresh wallet balance from server.
- Buttons: Go to Wallet → WAL-01; View Transaction → WAL-06; Download Receipt.

### Pending
- Show "We're confirming your payment".
- Explain that the wallet will update after provider confirmation.
- Buttons: Check Status; Wallet; Contact Support.
- Polling is bounded and rate-limited; do not create a new payment on every check.

### Failed
- Show "Payment was not completed" only when provider/server confirms failure.
- Display safe reference and reason if available.
- Buttons: Try Again (new intent only after prior state resolved); Wallet; Contact Support.
- No credits are added.

## 6. WAL-04 — Transaction history

### Layout
- Tabs: All, Purchases, Refunds, Adjustments.
- Filters: date range, status and reference.
- Table desktop / stacked cards mobile.
- Columns: date/time, reference, transaction type, Naira amount, credit amount, status.

### Buttons
**Search** filters transaction reference.
**Date Filter** opens date range selector.
**Status Filter** selects pending/success/failed/refunded.
**Transaction row** → WAL-06.
**Download Receipt** appears for verified completed purchase.
**Export** exports only the signed-in user's history.
**Report a Problem** creates support ticket with transaction reference prefilled.

## 7. WAL-05 — Credit usage

### Layout
- Summary: total credits used, current period usage and operation count.
- Usage rows: AI feature, date, debit, operation ID, status, refund state.
- Filters by feature/date/status.

### Buttons
**Open Operation** shows operation detail, input context summary and result status.
**Filter** updates list.
**Export** downloads user-owned usage history.
**Report Issue** creates support ticket with operation reference.
**Refund Status** opens refund details when applicable.

## 8. WAL-06 — Transaction detail

- Show transaction reference, provider reference, date, Naira amount, package, base credits, bonus credits, total credits, payment status and receipt.
- Hide sensitive provider/payment data.
- Buttons: Download Receipt, Report a Problem, Back to Transactions.
- Refund or adjustment is shown as a separate ledger event, not deletion of original transaction.

## 9. Global credit confirmation dialog

### Compact design

Use a compact modal (not a full-page oversized panel). On desktop, centred; on mobile, accessible bottom sheet.

Content order:
1. Tiny uppercase label: **USING CREDITS**
2. Feature name in medium semibold text.
3. Small uppercase label: **DEBITING CREDITS**
4. Debit amount as largest element, e.g. **−200 Credits**.
5. Small label: **Total credits** and live balance, e.g. 5,000 Credits.
6. Small label: **Remaining credits** and projected balance, e.g. 4,800 Credits.
7. One concise explanation of what the operation will do.
8. Footer buttons: Cancel (secondary, left) and Confirm (primary, right).

### Exact interaction

**Cancel**
- Closes dialog.
- Makes no debit request and creates no paid operation.
- Returns focus to the control that opened the dialog.

**Confirm**
- Sends operation request with idempotency key.
- Server locks/atomically checks wallet balance and current feature price.
- If balance is sufficient, create pending operation and debit exactly once in the same transaction.
- If balance changed since preview, return updated balance and ask user to reconfirm with the new values.
- If insufficient, do not debit; show required amount, actual balance and Buy Credits → WAL-02.
- On success, close dialog and start operation; show progress.
- On failure before operation starts, reverse/void debit through a ledger adjustment.
- If the operation fails after debit, apply disclosed refund/retry policy and show status.
- Duplicate taps with same idempotency key return the same operation result.

### Insufficient balance dialog
- Label: INSUFFICIENT CREDITS.
- Show current balance, required cost and shortfall.
- Buttons: Cancel and Buy Credits.
- Buy Credits → WAL-02.
- No partial debit.

## 10. Payment and ledger backend requirements

### Payment lifecycle
1. Create payment intent server-side.
2. Store unique internal transaction ID and provider reference.
3. Redirect to provider.
4. Receive signed webhook.
5. Verify signature, amount, currency, transaction identity and final provider status server-side.
6. Enforce idempotency.
7. Credit wallet ledger atomically once.
8. Reconcile provider settlement and internal ledger.
9. Notify user and issue receipt.
10. Keep audit trail.

### Ledger requirements
- Ledger entries are append-only/tamper-evident.
- Every entry includes user ID, type, amount, balance effect, reference, timestamp and source.
- No direct editing of wallet balance in admin UI.
- Refunds and corrections are new compensating ledger entries.
- Atomic debit prevents negative balances and concurrent double-spend.
- Feature price is read from server-side versioned cost rule.
- Store the price charged with each operation for audit.
- Never store card PIN, OTP or full card details.

### Admin and support
- Admin can inspect and reconcile but cannot silently alter balance.
- Refund/grant requires permission, reason, reference and audit record; high-value adjustments may require second approval.
- Support staff cannot request passwords, card PINs or OTPs.
- Payment disputes retain transaction references and relevant evidence under retention policy.

## 11. Provisional AI price catalogue

These are planning values, not final approved prices. All must be configurable server-side and visible before use.

| Feature | Proposed credits |
|---|---:|
| AI chat message | 20 |
| CV review | 100 |
| New CV generation | 200 |
| CV improvement | 50 |
| ATS analysis | 30 |
| Tailor CV to job | 100 |
| Cover letter generation | 100 |
| Job analysis | 50 |
| Interview question generation | 50 |
| Interview feedback | 100 |
| Career roadmap | 150 |
| Short grammar correction | 5 |
| Rewrite sentence | 5 |
| Rewrite paragraph | 10 |
| Improve CV section | 15 |

Do not expose this table as final public pricing until costs, model usage, margins and user testing have been reviewed and approved. Manual editing remains free. Exporting an existing document remains free.

## 12. Acceptance tests

- Each approved package displays the exact amount, total credits and bonus.
- ₦2,000 displays 2,200 Credits and +200 Bonus Credits.
- Purchased credits never expire.
- Checkout never credits wallet before verified provider confirmation.
- Redirect without verified payment does not credit wallet.
- Duplicate webhook does not duplicate credits.
- Concurrent debit attempts cannot spend the same balance twice.
- Cost changes after dialog preview trigger reconfirmation.
- Cancel causes no debit.
- Insufficient balance causes no partial debit.
- AI failure follows refund policy.
- Receipts and history are private to wallet owner.
- Reconciliation detects amount/currency mismatch.
- No recurring billing is created.
