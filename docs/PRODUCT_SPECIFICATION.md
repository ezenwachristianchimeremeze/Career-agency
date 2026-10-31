# Career Agency — Product and Interaction Specification

**Version:** 1.0  
**Status:** Design baseline; implementation has not started  
**Platforms:** Responsive web + dedicated mobile client  
**Visual direction:** Premium enterprise SaaS  
**Repository strategy:** Feature-preserving rebuild on `career-agency-production-rebuild`

## 1. Product scope

Career Agency serves job seekers, employers, recruiters and platform administrators. It combines job discovery, application management, professional documents, AI career tools, recruitment workflows, a prepaid Career Credits Wallet and platform operations.

### Approved commercial rules

- Prepaid Career Credits Wallet only; no monthly subscription or recurring billing.
- Purchased credits never expire.
- Manual CV editing and ordinary document editing are free.
- Paid AI operations disclose their credit cost before execution.
- No silent deductions.
- Credit balance changes are recorded in a ledger.
- Payment is credited only after server-side provider verification.
- Failed or undelivered operations follow a clear refund/retry policy.
- Promotional credits, if introduced, have separate disclosed conditions.

### Approved visual direction

Premium, clean, consistent enterprise SaaS. Desktop uses a fixed left sidebar, top bar and main content area. Mobile uses compact headers, scrollable content and role-specific bottom navigation.

Job-seeker mobile navigation: **Home · Jobs · Applications · AI Assistant · Profile**.

Employer mobile navigation: **Home · Jobs · Candidates · Messages · Company**.

Recruiter mobile navigation: **Home · Candidates · Pipeline · Messages · Profile**.

Admin uses a separate protected workspace.

## 2. Design system

Suggested tokens:

- Navy: `#101C35`
- Primary blue: `#2563EB`
- Success: `#16A34A`
- Warning: `#D97706`
- Error: `#DC2626`
- Main background: `#F7F9FC`
- Card: `#FFFFFF`
- Main text: `#172033`
- Secondary text: `#64748B`
- Border: `#E2E8F0`

Use Inter or a comparable accessible sans-serif. Standard button height 44–48 px, minimum practical touch target 44 × 44 px, card radius 14–18 px. Provide light and dark themes, visible keyboard focus, disabled/loading states and consistent feedback.

### Button contract

Every button must specify:
1. Visible label and icon.
2. Position and visual hierarchy.
3. Destination or operation.
4. Required role and permission.
5. Loading state.
6. Success result.
7. Validation and failure result.
8. Whether confirmation is required.
9. Whether an audit event is required.
10. Whether the action is free or credit-consuming.

No decorative or inert controls may be presented as functional buttons.

## 3. Public website and authentication screens

| ID | Screen | Main layout and controls | Tap/click result |
|---|---|---|---|
| PUB-01 | Public landing | Header: logo, Product, For Job Seekers, For Employers, Pricing, About, Log In, Get Started. Hero, feature sections, FAQs and footer. | Get Started → account type/signup; Log In → login; nav links scroll or open their public pages; Contact/Privacy/Terms/Help open their pages. |
| AUTH-01 | Account type | Three cards: Job Seeker, Employer, Recruiter. Login link. | Select a card → signup with requested account type; Login → login. Admin self-registration is not offered. |
| AUTH-02 | Sign up | Name, email, password, confirm password, country, requested account type, terms/privacy consent. | Create Account validates and creates pending account → email verification; password visibility toggles; legal links open policies. |
| AUTH-03 | Login | Email, password, remember-device option, Forgot Password, Login, Create Account. | Login verifies server-side and routes by verified role; unverified account → verification; invalid credentials → neutral error; lockout → safe message. |
| AUTH-04 | Forgot password | Email field and Send Reset Link. | Send request; show neutral response regardless of account existence; Back → login. |
| AUTH-05 | Reset password | New password and confirmation. | Validate single-use expiring token; save password; success → login. |
| AUTH-06 | Email verification | Masked email, code/link instructions, resend timer. | Verify → onboarding; resend is rate-limited; change email → account details. |
| AUTH-07 | Job-seeker onboarding | Personal details, headline, skills, experience, education, target roles, location, work preference, optional CV. | Back/Continue move steps; Skip only optional steps; Finish → job-seeker dashboard. |
| AUTH-08 | Employer onboarding | Company identity, website, location, industry, size, representative and evidence. | Save Draft; Continue; Submit Verification → pending state. |
| AUTH-09 | Recruiter onboarding | Identity, organisation, work email, focus, affiliation evidence. | Save Draft; Continue; Submit Verification → pending state. |
| AUTH-10 | Account recovery/security challenge | Recovery method and verification challenge. | Verify identity; recover account; revoke sessions when appropriate. |

## 4. Job-seeker screens

| ID | Screen | Layout | Buttons and transitions |
|---|---|---|---|
| JS-01 | Dashboard | Greeting; profile progress; wallet; application metrics; interviews; recommended jobs; recent activity. | Find Jobs → JS-02; View Applications → JS-08; AI Assistant → JS-19; Complete Profile → JS-32; Buy Credits → WAL-01; Transactions → WAL-04; job/application cards open their detail screens. |
| JS-02 | Job discovery | Search at top; filter/sort row; saved-jobs shortcut; result cards. | Search/Refresh query service; Filters → JS-03; Save toggles bookmark; card → JS-04; Load More paginates; Report → support/report flow. |
| JS-03 | Job filters | Drawer on desktop; bottom sheet on mobile. Location, work mode, category, experience, type, salary, date, employer verification and source. | Apply → JS-02 with filters; Reset clears; Cancel closes; Save Search persists; Create Alert opens alert setup. |
| JS-04 | Job detail | Company, title, location, work mode, salary if verified, date/source, description, requirements, benefits and application method. | Apply Now → JS-07; Save; Share; Analyse with AI → JS-05; Compare CV → JS-24; Report; Back. External application links are clearly identified. |
| JS-05 | AI job evaluation | Match summary, skill/experience alignment, missing requirements, risks and recommendations. | Analyse → paid confirmation if applicable; Save Analysis; Tailor CV → JS-24; Prepare Cover Letter → JS-25; Apply → JS-07; Close → JS-04. |
| JS-06 | Saved jobs | Saved job list, filters and expiry state. | Open → JS-04; Remove bookmark; Apply → JS-07; Search Jobs → JS-02. |
| JS-07 | Application preparation | Job summary, CV selection, cover letter, screening answers, employer destination and review checklist. | Choose CV → JS-21; Upload CV; Edit CV; Generate Cover Letter → JS-25; Preview; Save Draft; Continue to Employer opens external destination; Mark Submitted only after user confirms external submission. |
| JS-08 | Application tracker | Desktop kanban; mobile status tabs and cards. Statuses: Preparing, Applied, Under Review, Shortlisted, Interview, Offer, Rejected, Withdrawn. | Add Application; Search; Filter; card → JS-09; Change Status opens selector; Export; Calendar → JS-10. |
| JS-09 | Application detail | Job/employer, current status, timeline, CV/letter versions, notes, interviews and files. | Edit; Change Status; Add Note; Add Interview → JS-10; Upload Document; View Job; Withdraw with confirmation; Delete with destructive confirmation. |
| JS-10 | Interview calendar | Month/week/list views, events and upcoming list. | Previous/Next; Today; change view; Add Event; event → detail; Edit; Cancel with confirmation; Set Reminder. |
| JS-11 | Career goals | Goals, target dates, milestones and progress. | Add Goal; Edit; Add Milestone; Complete; Reminder; Save. |
| JS-12 | Career analytics | Application trends, conversion, status distribution, job activity and skills progress. | Date range; filters; export; metric drill-down to relevant records. |
| JS-13 | Career roadmap | Goal, current capabilities, milestones, learning tasks and progress. | Generate (credit confirmation if paid); Edit Goal; Add/Complete Milestone; Reminder; Save; Export. |
| JS-14 | Skills-gap analysis | Target role, current skills, required skills, missing skills and evidence. | Select Role; Analyse; Add Skill; Mark Learned; Save Plan; View Roadmap. |
| JS-15 | Portfolio builder | Project/publication/skill cards and preview with visibility settings. | Add/Edit/Remove Project; Preview; Publish/Unpublish; Copy Public Link; Export. |
| JS-16 | Professional profile | Photo, headline, bio, location, skills, experience, education, projects, certifications and links. | Edit; Upload/Remove Photo; Add Experience/Education/Skill; Preview Public Profile; Save. |
| JS-17 | Notifications | Categorised feed for applications, interviews, jobs, wallet, AI, security and support. | Open routes to related object; Mark Read; Mark All Read; Delete; Settings. |
| JS-18 | Document library | User-owned documents, type, date, version and access state. | Upload; Open/Preview; Download; Rename; Share where permitted; Delete with confirmation. |
| JS-19 | AI Assistant | Desktop history sidebar + conversation; mobile chat with fixed composer. Context panel optional. | New Chat; Search History; attach; voice input; Send; Stop; Copy; Regenerate; Edit; Read Aloud; Delete; Feedback; Rename; Archive; Export; Clear with confirmation. |
| JS-20 | Chat history | Searchable conversations and archive. | New; Search; Open; Rename; Archive; Delete; Export. |
| JS-21 | CV library | CV cards, format, last updated, default state and target role. | Create → JS-22; Upload; Open; Set Default; Rename; Download; Delete; Analyse ATS → JS-23. |
| JS-22 | CV Studio | Desktop: section navigator, editor, preview and AI panel. Mobile: section selector, editor and preview tabs. | Add/Remove Section; Move Up/Down; Undo/Redo; Save; Preview; Analyse ATS; Improve with AI; Tailor to Job; Export DOCX/PDF; Version History. Manual editing is free. AI edits require cost disclosure and confirmation. |
| JS-23 | ATS analysis | Readability, headings, keywords, formatting, skills alignment, grammar and missing data. | Analyse; Select Job; Improve; Fix Section; Download Report; Back to CV. Never guarantee ATS acceptance. |
| JS-24 | CV tailoring | Selected CV/job, keyword comparison, proposed changes and before/after preview. | Choose CV; Choose Job; Analyse; Generate; Accept/Reject Changes; Edit Manually; Save New Version; Export. Original remains unchanged by default. |
| JS-25 | Cover Letter Studio | Job/employer, selected CV, tone, instructions and editable letter. | Generate; Rewrite Paragraph; Improve Grammar; Undo; Save; Preview; Export DOCX/PDF; Copy; Back. AI operations show cost first. |
| JS-26 | Interview preparation | Job context, interview type, checklist, suggested questions and CV evidence. | Generate Questions; Start Practice → JS-27; View Tips; Save; Add to Calendar. |
| JS-27 | Interview practice | Question, answer editor/voice control, progress and session state. | Start; Record; Stop; Submit; Next; Pause; End; Review → JS-28. Recording requires explicit user action and visible state. |
| JS-28 | Interview feedback | Answer clarity, relevance, structure, evidence and suggestions. | Review; Try Again; Next Question; Save; Export; Finish. |
| JS-29 | Learning resources | Saved resources and learning plan. | Search; Open Resource; Save; Remove; Mark Complete; Add to Roadmap. |
| JS-30 | Professional email writer | Recipient context, purpose, tone and draft. | Generate (if paid); Rewrite; Copy; Save; Export; Clear. |

## 5. Wallet and credit screens

| ID | Screen | Layout | Buttons and transitions |
|---|---|---|---|
| WAL-01 | Wallet overview | Available balance, purchased/used totals, recent activity and policy. | Buy Credits → WAL-02; Transactions → WAL-04; Usage → WAL-05; Receipt; Payment Help. |
| WAL-02 | Credit packages | Grid of package cards. Credit quantity large, bonus beneath, Naira price at bottom. | Select Package → WAL-03; View Costs; Cancel → WAL-01. |
| WAL-03 | Checkout | Package, amount, credits, bonus, provider and terms. | Continue to Payment creates provider session; Change Package; Cancel. |
| WAL-04 | Transaction history | Date, reference, amount, credits and status. | Open Transaction → WAL-06; Filter; Download Receipt; Report Problem. |
| WAL-05 | Credit usage | Feature, debit, date, operation status and refund status. | Open Operation; Filter; Export; Request Support. |
| WAL-06 | Transaction detail | Provider reference, amount, credits, bonus, date, status and receipt. | Download Receipt; Report Problem; Back. |
| WAL-07 | Payment result | Success, pending or failure state with verified transaction data. | Wallet; View Transaction; Receipt; Retry only when safe; Contact Support. |

### Approved credit packages

| Price | Total credits | Bonus |
|---:|---:|---:|
| ₦200 | 200 | 0 |
| ₦300 | 300 | 0 |
| ₦500 | 500 | 0 |
| ₦1,000 | 1,100 | 100 |
| ₦2,000 | 2,200 | 200 |
| ₦3,000 | 3,300 | 300 |
| ₦4,000 | 4,400 | 400 |
| ₦5,000 | 5,500 | 500 |
| ₦10,000 | 11,000 | 1,000 |
| ₦15,000 | 16,500 | 1,500 |
| ₦20,000 | 22,000 | 2,000 |
| ₦30,000 | 33,000 | 3,000 |
| ₦40,000 | 44,000 | 4,000 |
| ₦50,000 | 55,000 | 5,000 |
| ₦100,000 | 110,000 | 10,000 |
| ₦200,000 | 220,000 | 20,000 |

No unapproved package values should be invented.

### Global credit confirmation dialog

Compact dialog hierarchy:
1. Tiny label: USING CREDITS.
2. Feature name.
3. Small label: DEBITING CREDITS.
4. Prominent debit, e.g. `−200 Credits`.
5. Total credits and current balance.
6. Remaining credits.
7. Cancel and Confirm.

Cancel closes without deduction. Confirm asks the server to validate the latest balance and atomically authorise the operation. Idempotency prevents repeated taps from charging twice. Failed or undelivered operations follow the disclosed refund/retry policy.

Example AI prices are provisional until approved: chat 20; CV review 100; CV improvement 50; new CV 200; ATS analysis 30; tailoring 100; cover letter 100; job analysis 50; interview questions 50; interview feedback 100; roadmap 150. Smaller manual AI edits may be priced lower. Manual editing and exporting an existing document are free.

## 6. Employer screens

| ID | Screen | Buttons and results |
|---|---|---|
| EMP-01 | Employer dashboard | Create Job; Manage Jobs; View Applicants; Search Candidates; Schedule Interview; Messages; Company Profile; Analytics. Verification banner gates restricted actions. |
| EMP-02 | Company profile/verification | Edit Profile; Upload Logo; Upload Evidence; Submit Verification; Replace Document; View Status. |
| EMP-03 | Create Job | Save Draft; Preview; Publish or Submit for Review; Cancel. Form includes role, location, type, salary/currency, description, requirements, benefits, application method and closing date. |
| EMP-04 | Manage Jobs | Tabs for Draft, Pending, Published, Paused, Closed, Rejected. Create; Open; Edit; Pause; Resume; Close; Duplicate; Applicants. |
| EMP-05 | Applicant pipeline | New, Reviewing, Shortlisted, Interview, Offer, Rejected. Open Candidate; Shortlist; Move Stage; Schedule; Message; Reject; Internal Note. |
| EMP-06 | Candidate detail | View/Download permitted CV; Shortlist; Schedule Interview; Message; Evaluation; Change Stage; Report. |
| EMP-07 | Candidate search | Search; Clear; Save Search; Open Candidate; Add to Shortlist. Respect candidate visibility. |
| EMP-08 | Interview scheduling | Send Invitation; Save Draft; Reschedule; Cancel; Add to Calendar. Include time zone and meeting details. |
| EMP-09 | Employer messaging | New; Open; Attach; Send; Archive; Report. |
| EMP-10 | Employer analytics | Date Range; Job Filter; Export; Pipeline Drill-down. |

## 7. Recruiter screens

| ID | Screen | Buttons and results |
|---|---|---|
| REC-01 | Recruiter dashboard | Find Candidates; Pipeline; Manage Clients; Create Shortlist; Schedule; Messages. |
| REC-02 | Candidate sourcing | Search; Save Search; Open Candidate; Shortlist; Compare. Respect visibility. |
| REC-03 | Candidate comparison | Add/Remove Candidate; View Profile; Save Comparison; Export permitted report. Use job-relevant criteria only. |
| REC-04 | Recruitment pipeline | Open Candidate; Move Stage; Schedule; Message; Add Note; Close Record. |
| REC-05 | Client/team management | Add/Edit Client; Assign Recruiter; Remove Team Member; Change Permission; View Activity. |

## 8. Admin screens

Admin is a separate protected workspace. Admin access requires server-side role checks, MFA and audit logging. Sensitive actions may require a second approver.

| ID | Screen | Buttons and results |
|---|---|---|
| ADM-01 | Admin dashboard | Users; Employers; Recruiters; Jobs; Applications; Reports; AI; Credits; Payments; Notifications; Support; Analytics; System Health; Audit; Security; Integrations; Settings. |
| ADM-02 | User management | Search; Filter; Open; Suspend; Restore; Appeal; Activity; Export permitted data. |
| ADM-03 | User detail | Suspend/Restore; Change Role with approval; Reset Verification; View Audit; Add Internal Note. |
| ADM-04 | Employer/recruiter verification | Open Submission; View Documents; Approve; Reject; Request More Information; History. |
| ADM-05 | Job moderation | Approve; Reject; Request Edit; Pause; Close; View Employer; View Reports. |
| ADM-06 | Reports/moderation | Open; Assign; Add Note; Request Evidence; Resolve; Escalate. |
| ADM-07 | Application monitoring | Search; Filter; Open permitted record; Export aggregate report; Flag. |
| ADM-08 | AI management | Enable/Disable Provider; Change Model; Test Connection; View Errors; Configure Limits; Usage. Never reveal complete secret keys. |
| ADM-09 | Credit management | Edit Feature Cost; View Transaction; Approved Refund; Promotional Grant; Suspend Operation; Export Ledger. All changes audited. |
| ADM-10 | Payment reconciliation | Refresh; Reconcile; Open Dispute; View Provider Reference; Export. No unverified manual crediting. |
| ADM-11 | Support administration | Assign; Reply; Request Information; Escalate; Resolve; Reopen; View User. |
| ADM-12 | Notifications | Create; Select Audience; Preview; Schedule; Send; Cancel; Delivery Report. |
| ADM-13 | Analytics | Date Range; Filter; Export; View Details. |
| ADM-14 | System health | Refresh; View Logs; View Incident; Maintenance Mode with confirmation; Deployment History. |
| ADM-15 | Audit logs | Search; Filter; Open Event; Export. Protect against ordinary modification/deletion. |
| ADM-16 | Security centre | Revoke Session; Require Reauthentication; Review Alert; Escalate; View Audit. |
| ADM-17 | Roles/permissions | Create Role; Edit; Assign/Remove Permission; Assign User; Review; Save. Deny by default. |
| ADM-18 | Integrations/settings | Configure; Test; Enable/Disable; Rotate Credentials through secure secret management; Save. |

## 9. Account, support and legal screens

| ID | Screen | Buttons and results |
|---|---|---|
| SET-01 | Settings hub | Profile card; Account; Security; Connected Accounts; Notifications; Appearance; Language; Accessibility; AI Preferences; Privacy; Help; About. Logout at bottom. |
| SET-02 | Account details | Edit Name; Change Email/Phone/Country; Save; Cancel. Sensitive changes require verification. |
| SET-03 | Security | Change Password; Enable/Disable MFA; Active Sessions; Log Out Other Devices; Login History; Recovery. |
| SET-04 | Connected accounts | Connect; Disconnect; Revoke Access; show scopes and consent. |
| SET-05 | Preferences | Save; Reset Defaults; Preview Theme; set language, time zone, notifications, accessibility and AI preferences. |
| SET-06 | Privacy/data | Privacy Settings; Download My Data; Review Permissions; Cookie Settings where applicable; Request Deletion. |
| SUP-01 | Help Centre | Search; Open Article; Contact; Support Centre; Report Problem. |
| SUP-02 | Contact Us | Attach/Remove File; Submit Message; Cancel. Fields: name, email, subject, message, optional attachment. |
| SUP-03 | Support centre | Create Ticket; Open; Reply; Attach; Close; Reopen. |
| SUP-04 | Ticket detail | Reply; Attach; Send; Close; Reopen; Rate Support. |
| PUB-02 | About Career Agency | Product description, mission, vision, version and release notes. |
| PUB-03 | Meet the Founder | Actual approved photograph, full name, approved biography, role, vision, mission and approved links. |
| LEG-01 | Privacy Policy | Reviewed policy content and contact details. |
| LEG-02 | Terms | Reviewed terms. |
| LEG-03 | Cookie Policy | Applicable cookie information and controls. |
| LEG-04 | Credit Purchase Policy | Package, credit, payment and expiry rules. Purchased credits never expire. |
| LEG-05 | Refund/Dispute Policy | Clear eligibility, processing and contact route. |
| LEG-06 | AI Use Disclosure | Explain AI-generated content, limitations and user review responsibility. |
| LEG-07 | Marketplace Rules | Employer, recruiter, candidate and job-listing rules. |

## 10. Shared interaction requirements

### Navigation and unsaved work

- Back navigation preserves safe drafts.
- Leaving a dirty form prompts to save, discard or stay.
- Tab changes do not silently erase user input.
- Deep links open the intended screen only after permission checks.
- Mobile keyboard and safe-area behaviour are tested.

### Search and lists

- Search is debounced where appropriate.
- Filters are visible and removable.
- Pagination has loading and empty states.
- Expired jobs are clearly marked.
- Duplicate jobs are detected.
- User-facing records are scoped to the authenticated owner.

### Dialogs and sheets

- Destructive actions require confirmation.
- Dialogs have clear Cancel and Confirm actions.
- Escape/backdrop close behaviour is consistent and never silently confirms.
- Mobile dialogs use accessible bottom sheets where suitable.
- Focus is trapped and returned appropriately on web.

### AI actions

- Show loading and cancellation where supported.
- Show provider failure and retry.
- Display generated content as a draft for user review.
- Do not invent user qualifications.
- Record operation status and disclosed cost.
- Do not charge twice on retry or repeated taps.

### Wallet actions

- Verify payments on the server.
- Process provider webhooks idempotently.
- Keep an append-only or tamper-evident ledger.
- Reconcile provider amount and internal amount.
- Do not credit on a browser redirect alone.
- Purchased credits do not expire.
- Never silently deduct credits.

---

## 11. Target architecture

### Clients

- Responsive React web application.
- React Native mobile application.
- Shared design tokens and component rules.
- Typed API client and common validation contracts.

### Backend domains

1. Identity and authentication.
2. User profile.
3. Jobs and sources.
4. Applications.
5. CV and documents.
6. AI orchestration.
7. Interviews and career development.
8. Employers.
9. Recruiters.
10. Wallet and credit ledger.
11. Payments.
12. Notifications.
13. Support.
14. Administration.
15. Analytics.
16. Audit and security.

### Infrastructure

- Python API service with modular boundaries.
- PostgreSQL production database.
- Redis for cache, rate limits and task coordination.
- Background task workers.
- Secure object storage.
- Email provider.
- Payment provider.
- AI provider gateway.
- Centralised logs and monitoring.
- Automated backups and tested restoration.

SQLite may remain useful for local development and migration utilities, but it is not the target multi-user production database.

### API groups

- `/api/v1/auth`
- `/api/v1/users`
- `/api/v1/profiles`
- `/api/v1/jobs`
- `/api/v1/applications`
- `/api/v1/cvs`
- `/api/v1/documents`
- `/api/v1/ai`
- `/api/v1/interviews`
- `/api/v1/wallet`
- `/api/v1/payments`
- `/api/v1/employers`
- `/api/v1/recruiters`
- `/api/v1/notifications`
- `/api/v1/support`
- `/api/v1/admin`
- `/api/v1/analytics`

Every endpoint documents authentication, permissions, request/response schema, validation, errors, rate limits, audit and idempotency.

## 12. Core data model

Identity: users, user_roles, role_permissions, sessions, verification_tokens, reset_tokens, mfa_methods, login_events.

Profiles: user_profiles, skills, user_skills, experiences, education_records, certifications, portfolio_projects, connected_accounts.

Marketplace: employers, employer_members, recruiter_profiles, recruiter_clients, jobs, job_sources, saved_jobs, applications, application_events, application_documents, interview_events, candidate_evaluations.

Documents/AI: cvs, cv_versions, cover_letters, documents, ai_conversations, ai_messages, ai_operations, ai_feedback, career_roadmaps, career_milestones.

Wallet: wallets, credit_packages, wallet_ledger, payment_transactions, payment_webhook_events, credit_cost_rules, refund_requests, promotional_credit_grants.

Operations: notifications, support_tickets, support_messages, moderation_reports, audit_events, admin_approvals, system_incidents, feature_flags.

All user-owned records require ownership identifiers and server-enforced object-level access checks. Schema changes use versioned migrations.

## 13. Security and privacy baseline

- Use Argon2id or another approved password-hashing scheme.
- Secure, HTTP-only, same-site session cookies or a carefully designed token strategy.
- CSRF protection where cookie authentication is used.
- MFA for administrators.
- Server-side role and object-level authorization on every protected operation.
- Rate limiting and abuse controls.
- Secure upload validation and isolated storage.
- Encryption in transit and appropriate encryption at rest.
- Secret manager for provider keys.
- Payment webhook signature validation.
- Audit sensitive actions.
- Data export and deletion workflows.
- Data retention rules.
- Dependency scanning and security review.
- No secrets, production database or user uploads committed to GitHub.

## 14. Existing feature preservation

Existing functionality to map and preserve:

- Job discovery and auto-fetching.
- Job queue and application pipeline.
- AI chat, streaming and history.
- CV upload and extraction.
- ATS and job matching.
- Cover-letter generation.
- Interview practice.
- Career roadmap.
- Workspace tasks.
- Profile and settings.
- Recruitment inbox.
- Voice-command endpoint.
- Export and backup functions.
- Existing automated tests.

For each feature, record its existing route, template, database tables, behaviour, dependencies and tests; map it to a new screen/API; add a migration and acceptance test; then decide preserve, rebuild or retire. Retirement requires owner approval.

## 15. Delivery sequence

### Phase 0 — Audit and preservation
Complete repository inventory, dependency reconciliation, route/security audit, feature matrix, data inventory and migration safeguards.

### Phase 1 — Product/interface specification
Complete desktop and mobile layouts, screen flows, button contracts, permissions, empty/loading/error/success states and design review.

### Phase 2 — Architecture
Approve domain boundaries, database schema, API contracts, auth model, AI operation lifecycle, wallet ledger and migration strategy.

### Phase 3 — Foundation
Authentication, user profiles, app shells, database migrations, permissions, logging and tests.

### Phase 4 — Job-seeker workspace
Dashboard, jobs, applications, CV Studio, AI Assistant, interview tools and career development.

### Phase 5 — Wallet and payments
Packages, checkout, verification, ledger, confirmation dialog, refunds and disputes.

### Phase 6 — Employer and recruiter workspaces
Verification, job management, candidates, pipeline, messaging and interviews.

### Phase 7 — Admin and support
Moderation, user management, AI and credit operations, reconciliation, support, audit and security.

### Phase 8 — Mobile application
Mobile client, document picker, push notifications, deep links and real-device testing.

### Phase 9 — Production hardening
Security, performance, backups, monitoring, legal review, incident response and launch gates.

## 16. Release acceptance gates

Do not launch until core advertised features work; critical security issues are resolved; account isolation is tested; payments are verified end-to-end; wallet reconciliation passes; AI failures follow the refund policy; backups restore successfully; legal content is reviewed; support is operational; web and mobile journeys pass; and monitoring/rollback are ready.

## 17. Repository safeguards

- Keep `main` unchanged during the rebuild.
- Work on `career-agency-production-rebuild`.
- Preserve the open security-review branch and pull request.
- Add new documentation and implementation files without replacing existing files during early phases.
- Reconcile the uploaded ZIP against the GitHub source before importing anything.
- Back up user data and test migrations on copies.
- Do not merge, delete existing work, or run destructive migrations without explicit approval.

**Product rule:** Every screen has a purpose, every button performs its advertised action, every protected action checks permissions, every paid operation discloses its cost, and every failure has a safe result. This document is a design baseline; production readiness must be demonstrated by implementation, tests and operational evidence.
