# Career Agency — Brand, Welcome and Account Access Experience

**Status:** Implemented foundation; production sign-off pending external integrations and security review.

## 1. Brand system

- Product name: Career Agency.
- Logo: original monogram/forward-path mark rendered as inline SVG; do not depend on a third-party image URL.
- Primary display font: Manrope, weights 500–800.
- Interface font: DM Sans, weights 400–700.
- Font fallbacks: system-ui, sans-serif. The interface remains legible if Google Fonts is unavailable.
- Palette: midnight navy/near-black surfaces, restrained blue accent, high-contrast white text, muted slate secondary text.
- Visual language: premium, calm, trustworthy, focused on professional progress; avoid loud gradients, excessive glass effects and distracting motion.
- Responsive layout: centered, constrained panel on desktop; safe-area-aware single-column panel on mobile.

## 2. First-screen and greeting rules

- An unauthenticated visitor opening / is redirected to /auth/login.
- Login is the first app screen; there is no public marketing page ahead of it.
- Greeting: “Welcome back.”
- Supporting line: “Your next opportunity starts with one focused step. Sign in to continue.”
- The authenticated root route must later route to a server-verified role dashboard. The current migration guard keeps unfinished legacy workspaces isolated.

## 3. Account journey screens

| Route | Purpose | Main action |
|---|---|---|
| /auth/login | Sign in | Sign in |
| /register | Create account | Create account |
| /verify-email | Verify or resend email | Verify link / resend |
| /forgot-password | Request reset | Send reset link |
| /reset-password?token=... | Set new password | Update password |

### Login

- Email and password fields use browser autocomplete semantics.
- Password is masked by default.
- Submit button disables while the request is in flight and returns to its resting state after completion.
- Errors appear in an accessible alert region.
- Forgot Password and Create Account remain secondary links.
- Successful sign-in stores the server-verified role in the session and sends the user to the app entry route.

### Registration

- Required: full name, email, password, password confirmation, account type and explicit Terms/Privacy consent.
- Public self-registration permits job seeker, employer and recruiter. Admin is never self-selectable.
- Password minimum: 10 characters. Server repeats validation; browser validation is not trusted.
- Registration creates a pending-verification account with zero credits.
- The server creates a single-use email verification token with a 24-hour expiry and sends a verification email through the configured server-side email adapter.
- The user is not authenticated until the email is verified.
- Duplicate email responses do not disclose account details beyond a generic conflict response.

### Email verification

- Verification tokens are random, single-use, stored as SHA-256 hashes, expire after 24 hours and are consumed transactionally.
- A valid token marks the email verified and activates the pending account.
- Resend uses a neutral response so account existence is not disclosed.
- Delivery failures are logged server-side without logging the token.
- The verification screen provides a clear success, invalid/expired and resend state.

### Password recovery

- Forgot Password always returns the same neutral success message whether or not the address exists.
- Reset tokens are random, single-use, stored as SHA-256 hashes and expire after one hour.
- Password reset requires a new password of at least 10 characters.
- Reset increments the user's session version, invalidating all existing browser sessions on their next request.
- The reset screen does not reveal whether an email is registered.

## 4. Security controls in this implementation

- Password hashes use Werkzeug scrypt.
- CSRF token endpoint: GET /api/v1/auth/csrf.
- Mutating browser requests require X-CSRF-Token, except the Paystack webhook, which uses provider signature verification.
- Login and registration have IP/email or IP-based throttling.
- Server-side role allowlist excludes admin from public registration.
- Session cookie is HttpOnly and SameSite=Lax; Secure must be enabled in HTTPS production.
- Session version is checked on authenticated requests.
- Tokens are never returned in API responses.
- Email provider credentials remain server-side environment secrets.

## 5. Required configuration before account flows can be used by real customers

Set:
- CAREER_AGENCY_SECRET_KEY to a high-entropy secret.
- CAREER_AGENCY_PUBLIC_URL to the canonical HTTPS application origin.
- CAREER_AGENCY_COOKIE_SECURE=1.
- CAREER_AGENCY_AUTH_EMAIL_ENDPOINT to the trusted email adapter.
- CAREER_AGENCY_AUTH_EMAIL_API_KEY in the server secret store.

The repository includes an environment template, not production secrets. Email delivery has not been live-tested in this repository environment.

## 6. Outstanding production requirements

- Configure and verify the transactional email provider, sender domain, SPF, DKIM and DMARC.
- Add MFA/passkeys and account recovery support policy.
- Add dedicated native-mobile access/refresh token rotation before mobile app launch.
- Add abuse monitoring, CAPTCHA or equivalent adaptive friction where risk warrants it.
- Complete privacy policy, terms, data-retention schedule and Nigerian legal/compliance review.
- Complete independent security review and full application regression tests.
- Ensure all legacy routes have ownership checks before re-enabling them.

## 7. Test coverage

The core test suite covers:
- pending registration and email verification;
- blocked sign-in before verification;
- successful sign-in and wallet access after verification;
- password reset and session invalidation;
- branded login/register/verification/recovery screen rendering.
