# Career Agency — Mobile Authentication and Onboarding Contract

## Status

Backend foundation implemented on the rebuild branch. A native mobile UI still needs to be built and tested on real Android/iOS devices.

## Mobile authentication endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | /api/v1/mobile/auth/login | Verify credentials and issue access + refresh tokens |
| POST | /api/v1/mobile/auth/refresh | Rotate a refresh token and issue a new access token |
| POST | /api/v1/mobile/auth/logout | Revoke the refresh-token family and its access tokens |
| GET | /api/v1/auth/me | Return the authenticated account using a Bearer access token |

## Token policy

- Access token lifetime: 15 minutes.
- Refresh token lifetime: 30 days.
- Access tokens are signed with the server secret and carry subject, role, session version, token ID and token-family ID.
- Refresh tokens are random high-entropy values. Only SHA-256 hashes are stored.
- Every refresh is single-use and rotates to a new refresh token.
- Reuse of a consumed refresh token revokes the entire token family.
- Logout revokes the refresh-token family and all access tokens in that family.
- Password reset increments the account session version and revokes all mobile access and refresh tokens.
- Every authenticated request checks account status, session version and access-token revocation state.

## Native app storage rules

- Store access and refresh tokens only in platform-protected storage: Android Keystore-backed encrypted storage or iOS Keychain.
- Never put refresh tokens in plain preferences, logs, analytics, crash reports or clipboard.
- Keep the access token in memory where practical; refresh before expiry.
- On HTTP 401, attempt one refresh. If refresh fails, clear protected tokens and return to sign-in.
- Do not automatically retry a non-idempotent payment or credit action after an ambiguous network failure without its original idempotency key.
- Do not store user passwords on the device.

## Mobile onboarding

The mobile app uses the same authenticated onboarding endpoints:
- GET /api/v1/onboarding
- PUT /api/v1/onboarding/profile
- PUT /api/v1/onboarding/preferences
- POST /api/v1/onboarding/complete

The backend derives the account role from the verified user record. The app must not allow a client-side role change to grant privileges.

## Current implementation boundary

The backend exposes mobile login, rotating refresh, logout and Bearer authentication. The native application screens, device secure-storage implementation, deep-link verification handling, push notifications, store signing, release builds and device-level tests are not yet complete. The responsive web login is not a substitute for a native mobile release.
