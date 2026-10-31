# Career Agency — Repository Audit

**Audit baseline:** `main` at commit `9eb55335394761832564cb7240d6d21b15cecd6d`  
**Audit type:** Source-level inventory and preliminary risk review  
**Date:** 2026-10-31

## Repository snapshot

The repository is a public Python/Flask project with seven root files:

- `.gitignore`
- `README.md`
- `app.py` (8,591 lines; approximately 467 KB)
- `auto_fetcher.py`
- `requirements.txt`
- `start_app.sh`
- `test_app.py` (39 detected test functions)

The main application contains 57 detected Flask route declarations and approximately 101 Python functions. The code includes job discovery, an application pipeline, AI chat and streaming, CV upload/extraction, ATS/job matching, cover-letter generation, interview practice, career-roadmap generation, workspace tasks, profile/settings, recruitment inbox, voice-command handling and SQLite persistence.

## Critical findings

1. **Missing module:** `app.py` imports `v25_engine`, but no `v25_engine.py` file exists in the audited `main` tree. A clean checkout may fail during import until this dependency is reconciled.
2. **Password hashing:** Registration uses SHA-256 directly for passwords. Replace with a password-hashing scheme designed for passwords (for example Argon2id or scrypt, with a carefully planned migration).
3. **Authentication enforcement:** No `login_required` decorator or global request authentication middleware was detected in the inspected source. Authentication exists in parts of the application, but protected routes need a complete access-control audit.
4. **Unsafe identity fallback:** A profile API defaults to user ID 1 when the session does not contain a user ID. Remove fallback identity and enforce authenticated ownership.
5. **Shared data model:** Several routes query shared SQLite tables without a consistent authenticated-user ownership filter. This is incompatible with safe multi-user public operation.
6. **Duplicate routes:** `/profile` and `/settings` are each registered more than once. Consolidate route ownership and remove ambiguous endpoint registrations only after preserving behaviour.

## High-priority findings

1. Database initialisation seeds sample application records.
2. The Gmail sync route inserts sample recruitment emails rather than demonstrating a verified mailbox integration.
3. The application embeds large HTML/CSS/JavaScript templates inside `app.py`, increasing maintenance and regression risk.
4. The README on `main` is only a few heading lines and does not explain setup, dependencies, configuration or deployment.
5. `auto_fetcher.py` imports BeautifulSoup, but `requirements.txt` does not declare `beautifulsoup4`.
6. `start_app.sh` is Termux-specific, operates from the home directory, kills matching processes broadly and creates a restart loop. It is not a production deployment strategy.
7. AI provider keys are stored in the local SQLite settings table. Production secret storage, access control, encryption and key rotation need a dedicated design.
8. File uploads, public routes, state-changing GET routes, session handling, CSRF protection and object-level authorization require a complete security review.
9. The current design uses SQLite and process-local background threads. Production multi-user operation needs a managed database, task queue and worker lifecycle.
10. The source includes profile defaults and sample content that must not be treated as real public-user data.

## Existing features to preserve or reconcile

- Job collection and discovery.
- Job queue and application pipeline.
- AI assistant, chat history and streaming.
- CV upload and text extraction.
- ATS and job-match analysis.
- Cover-letter and application-material generation.
- Interview practice and interview preparation.
- Career roadmap.
- Workspace tasks.
- Profile and settings.
- Recruitment inbox.
- Voice-command endpoint.
- Export and backup-related functionality.
- Existing automated tests.

Every capability must be mapped to a new screen, API, data owner, migration requirement and acceptance test before it is replaced.

## Existing GitHub work

- Default branch: `main`.
- Existing branch: `career-agency-security-review`.
- Pull request #1, **Security hardening for Career Agency**, is open and unmerged.
- This audit does not merge, close, modify or replace that pull request.

The pull request notes that the uploaded ZIP and GitHub version of `app.py` differ. They must be reconciled feature-by-feature; neither should be blindly copied over the other.

## Audit limitations

This is a preliminary source-level audit. It is not a penetration test, full code review, clean-install validation or production certification. The complete test suite has not been executed in this audit. Payment processing, email delivery, OAuth, deployment, backup restoration and all security properties remain to be independently verified.

## Rebuild safeguards

- Preserve the existing `main` branch and repository history.
- Work on `career-agency-production-rebuild`.
- Add new files rather than replacing existing files during specification work.
- Build a feature-preservation matrix before implementation.
- Back up and test data migrations on copies.
- Do not merge into `main`, delete existing work or perform destructive migrations without explicit approval.
