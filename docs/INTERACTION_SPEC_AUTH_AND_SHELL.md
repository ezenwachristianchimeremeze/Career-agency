# Detailed Interaction Specification — Authentication and App Shell

**Scope:** AUTH-01 through AUTH-10, shared navigation, global feedback and responsive behaviour.  
**Status:** Design specification only; no production UI or backend has been implemented by this document.

## 1. Shared responsive shell

### Desktop (minimum target width 1024 px)

- Left sidebar: fixed width 248 px, full viewport height.
- Top bar: 72 px high, aligned to the content area.
- Main content: flexible width, max content width approximately 1440 px, 24–32 px page padding.
- Sidebar top: Career Agency mark and product name.
- Sidebar bottom: Help, Settings, profile avatar/name and Logout entry.
- Top bar left: page title and optional breadcrumb.
- Top bar right: global search (where supported), notifications, wallet balance for job seekers, help icon and avatar menu.
- Main content scrolls independently; sidebar remains stable.

### Mobile (320–767 px)

- Header: 56–64 px; logo/title on left; notification/avatar actions on right.
- Main content: full width with 16 px horizontal padding.
- Bottom navigation fixed above device safe area; content reserves bottom padding so controls are not obscured.
- Job seeker tabs: Home, Jobs, Applications, AI Assistant, Profile.
- A selected tab uses primary blue icon/text and a subtle background; inactive tabs use neutral colour.
- Secondary pages show a back arrow in the header; bottom navigation remains available unless a full-screen flow (e.g. payment provider or document preview) intentionally hides it.
- Primary form action is sticky at the bottom only when it does not cover fields or keyboard content.
- Keyboard opening moves/resizes the content and keeps the focused field visible.

### Tablet (768–1023 px)

- Sidebar collapses to icon rail or drawer.
- Two-column forms where appropriate; single column for narrow content.
- Bottom navigation may be replaced by compact navigation rail depending on available width.

## 2. Global button and feedback rules

- Primary action: solid blue, left aligned with form content or right aligned in desktop dialog footer.
- Secondary action: white/transparent with border.
- Destructive action: red text or red-tinted button; never styled as the primary positive action.
- Icon-only action: tooltip on web and accessible label on all platforms.
- Disabled action: visibly disabled and accompanied by the reason when not obvious.
- Loading action: spinner plus action-specific text (e.g. "Creating account…"); prevent duplicate submission.
- Success: inline confirmation and/or toast; do not rely on colour alone.
- Error: inline field error for validation; page-level alert for service/network failure.
- Toasts do not replace persistent status for payments, applications or support tickets.
- Every action supports keyboard focus and screen-reader name on web.
- Touch targets are at least 44 × 44 px where practical.

## 3. AUTH-01 — Account type

### Layout

- Centre a card (max width 680 px) on a calm neutral background.
- Header: Career Agency logo, title "How will you use Career Agency?", short explanatory sentence.
- Three selectable cards in a row on desktop and a vertical stack on mobile:
  1. Job Seeker — find opportunities and manage applications.
  2. Employer — publish roles and manage applicants.
  3. Recruiter — source and manage candidates.
- Footer: "Already have an account? Log in", plus Privacy and Terms links.

### Buttons and actions

**Job Seeker card**
- Position: first card; entire card is clickable.
- Default: neutral border, icon, title, short description.
- Hover/focus: primary-blue border and subtle shadow.
- Selected: blue border, pale blue background, check indicator.
- Tap: select job seeker and navigate to AUTH-02 with requested account type preselected.

**Employer card**
- Same interaction; tap → AUTH-02 with employer type selected.
- Explain that publishing jobs may require organisation verification later.

**Recruiter card**
- Same interaction; tap → AUTH-02 with recruiter type selected.
- Explain that recruiter verification may be required for candidate access.

**Log in link**
- Position: bottom below cards.
- Tap → AUTH-03.

**Privacy / Terms**
- Open LEG-01 / LEG-02 in a new route or accessible web view.
- Preserve the in-progress account-type selection when returning.

### States

- Initial: no card selected.
- Selected: one card selected.
- Continue action appears after selection; tap → AUTH-02.
- Network is not required at this step.
- Admin is not offered as a self-selected account type.

## 4. AUTH-02 — Sign up

### Layout and field order

A single-column form, max width 520 px:
1. Page title "Create your account".
2. Account-type summary with Change link.
3. Full name.
4. Email address.
5. Country selector (Nigeria selected only if the user chooses it; do not infer country silently).
6. Password.
7. Confirm password.
8. Required Terms and Privacy consent checkbox.
9. Primary "Create Account" button.
10. Existing account "Log in" link.

### Field behaviour

**Full name**
- Required; trim leading/trailing whitespace.
- Do not force uppercase or reject legitimate name punctuation.
- Error: "Enter your name."

**Email**
- Required; normalise whitespace and validate format.
- Error: "Enter a valid email address."
- If already registered, use safe wording and direct the person to log in or reset password without disclosing sensitive account details.

**Country**
- Searchable list with country code.
- Required if used for location/payment/legal requirements.
- Save ISO country code, not a free-form country string.

**Password**
- Minimum policy must be documented and consistently enforced server-side.
- Show/hide icon toggles visibility without changing value.
- Password meter gives guidance but does not disclose the password.
- Never log the password or send it to analytics.

**Confirm password**
- Must match password.
- Error: "The passwords do not match."

**Consent**
- Checkbox unchecked by default.
- Terms and Privacy links open legal pages.
- Create Account stays disabled until required fields and consent are valid.

### Buttons

**Create Account**
- Position: full width below consent; primary blue.
- Tap: disable button; show "Creating account…"; send signup request.
- Success: create an unverified account, send verification email, route to AUTH-06.
- Validation error: keep form values, focus first invalid field, show inline error.
- Email already in use: neutral message and links to login/reset.
- Network/server error: keep form values and show Retry.
- Repeated tap: blocked client-side and deduplicated server-side.

**Change account type**
- Position: beside account-type summary.
- Tap: AUTH-01; preserve non-sensitive fields if safe.

**Log in**
- Tap: AUTH-03.

## 5. AUTH-03 — Login

### Layout

- Centred form max width 440 px.
- Logo and "Welcome back".
- Email, password, show/hide, optional "Remember this device" control, Forgot Password, Login.
- Links to create account and help.
- Do not expose role choice on the login screen.

### Buttons

**Show/Hide password**
- Trailing icon inside password field.
- Tap toggles visibility; password value remains unchanged.

**Forgot Password**
- Below password field, aligned right.
- Tap → AUTH-04.

**Log In**
- Full-width primary button.
- Tap: validate client fields, disable, show "Signing in…", submit credentials over TLS.
- Server validates password, account state, MFA and role.
- Job seeker → JS-01.
- Verified employer → EMP-01.
- Verified recruiter → REC-01.
- Admin → ADM-01 only after admin-specific MFA and authorization.
- Unverified account → AUTH-06.
- MFA required → MFA challenge screen (to be added to the detailed security flow).
- Wrong credentials: neutral "Email or password is incorrect."
- Locked/rate-limited: explain temporary restriction and safe recovery.
- Network failure: retain email only, clear password if security policy requires, show Retry.
- Never trust a role value sent by the browser.

**Create Account**
- Tap → AUTH-01.

**Help**
- Tap → SUP-01.

## 6. AUTH-04 — Forgot password

- Heading: "Reset your password".
- Explain that the user can request a secure reset link.
- Email field.
- Primary "Send reset link".
- Secondary "Back to login".

**Send reset link**
- Tap: show loading; server responds with the same user-facing message whether or not the account exists.
- Result: "If an account matches that email, reset instructions will be sent."
- Apply rate limits and abuse controls.
- Do not reveal whether an email is registered.
- Reset token is random, single-use, stored hashed and expires.
- Link → AUTH-05.

**Back to login**
- Tap → AUTH-03.

## 7. AUTH-05 — Reset password

- Opened from valid reset link.
- Show New Password and Confirm New Password.
- Show password guidance and visibility controls.
- Expired/invalid/used token: show explanation and "Request a new link" → AUTH-04.

**Reset Password**
- Disabled until both fields satisfy policy and match.
- Tap: server validates token and updates password using Argon2id (or approved password hash).
- Revoke other active sessions and reset tokens.
- Success → confirmation then AUTH-03.
- Failure → preserve safe state and offer a new link.

## 8. AUTH-06 — Email verification

- Show masked destination email, e.g. `c•••••@example.com`.
- Six-digit code entry or secure verification link.
- Explain spam/promotions folder and resend cooldown.
- Buttons: Verify Email, Resend Code, Change Email, Log Out.

**Verify Email**
- Tap: validate code/link on server; success marks email verified and routes to role-specific onboarding.
- Invalid code: inline error; do not clear all input unnecessarily.
- Expired code: show "Code expired" and enable resend.
- Too many attempts: temporary cooldown and support route.

**Resend Code**
- Disabled during cooldown.
- Tap: server applies rate limit and sends new code; previous code invalidated.
- Show success message and new countdown.

**Change Email**
- Tap → account email correction flow; require re-verification.

**Log Out**
- Revoke current session and return to public landing.

## 9. AUTH-07 — Job-seeker onboarding

### Progress

A 5-step wizard with progress indicator and "Step x of 5":
1. Basics.
2. Career target.
3. Skills and experience.
4. Education and projects.
5. CV and preferences.

### Shared wizard buttons

**Back**
- Left side of footer.
- Goes to previous step; preserves entered values.

**Continue**
- Right side primary action.
- Validates current step; first invalid field receives focus.
- Saves draft server-side before advancing.

**Save and Exit**
- Secondary action in header or overflow menu.
- Saves draft and routes to JS-01 (dashboard with onboarding incomplete banner).

**Skip for now**
- Only appears on optional steps; never skips required identity/consent fields.
- Moves to next step and records incomplete profile state.

**Finish Setup**
- Final step primary action.
- Saves profile and preferences; routes to JS-01.
- Dashboard shows profile completion and recommended next actions.

### Step-specific fields

**Step 1 — Basics:** display name, location/country, headline, work authorisation where relevant and optional profile photo.

**Step 2 — Career target:** desired role(s), industry, experience level, work mode (remote/hybrid/on-site), preferred locations and salary range (optional).

**Step 3 — Skills and experience:** skills, proficiency (optional), experience entries, employment type and dates. Do not require work history for new graduates.

**Step 4 — Education and projects:** education, certifications, projects and portfolio links. All entries are user-supplied; no fabricated credentials.

**Step 5 — CV and preferences:** upload CV (optional), preferred job alerts, notification preferences and privacy visibility.

## 10. AUTH-08 — Employer onboarding

- Steps: organisation details, representative details, verification evidence, review.
- Save Draft always available.
- Continue validates current step.
- Submit for Verification sends evidence to restricted review queue.
- Pending status allows profile edits but gates publishing or other high-trust actions.
- Rejected status shows reason and "Resubmit Evidence".
- Never display private verification documents publicly.

## 11. AUTH-09 — Recruiter onboarding

- Steps: recruiter identity, organisation/affiliation, recruiting focus, evidence, review.
- Save Draft and Continue behave like employer onboarding.
- Submit for Verification enters review queue.
- Candidate data access remains restricted until approved and permissioned.

## 12. AUTH-10 — Recovery and security challenge

- Offer verified recovery methods only.
- Do not reveal whether an unverified recovery address or phone belongs to an account.
- High-risk recovery requires additional verification and may revoke all sessions.
- Recovery events are logged and notify the account owner.
- Support staff cannot ask users for passwords or one-time codes.

## 13. Missing screens to add to the master screen inventory

The earlier product specification should be extended with:
- AUTH-11: Multi-factor authentication challenge.
- AUTH-12: Set up authenticator app / recovery codes.
- AUTH-13: Session/device review.
- AUTH-14: Suspicious login notification and secure-account flow.
- AUTH-15: Account locked / appeal / recovery state.
- PUB-04: Public pricing and credit-package explanation (without recurring subscriptions).
- PUB-05: Public trust and safety / employer verification explainer.
- PUB-06: Accessibility statement.
- SYS-01: Maintenance / service unavailable.
- SYS-02: Permission denied / access request.
- SYS-03: Not found.
- SYS-04: Global error / retry.
- SYS-05: Offline / reconnect state.

## 14. Acceptance tests

- User can sign up, verify email and log in.
- Login routes only by server-verified role.
- A user cannot select admin role during public signup.
- Passwords are not stored in plaintext or fast unsalted hashes.
- Reset links are single-use, expiring and rate-limited.
- Forgot-password response does not disclose account existence.
- MFA is enforced for admin.
- A user cannot access another user's profile by changing an ID.
- Draft onboarding survives refresh and sign-out/sign-in.
- All form controls work with keyboard and screen reader.
- Mobile 320 px layout has no horizontal overflow.
- Loading, empty, validation, network failure and success states are tested.
