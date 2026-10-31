# Detailed Interaction Specification — Employer, Recruiter and Admin Workspaces

**Scope:** EMP-01 to EMP-10, REC-01 to REC-05, ADM-01 to ADM-18.  
**Status:** Design specification only; role permissions and server implementation pending.

## 1. Role and tenant rules

- Employer and recruiter accounts are separate workspaces.
- Organisation verification gates high-trust actions such as publishing jobs or accessing restricted candidate information.
- Recruiter candidate access is limited by consent, visibility and assigned client/team permissions.
- Admin is never a public signup choice.
- Every admin route checks server-side role and permission; hiding a button is not authorization.
- High-impact admin actions require a reason, confirmation and immutable audit event.
- Sensitive/high-value actions may require a second authorised approver.
- Admins must not be able to view user passwords, full payment credentials or complete provider secret keys.

## 2. Employer workspace navigation

Desktop sidebar:
1. Overview
2. Company Profile
3. Jobs
4. Applicants
5. Candidate Search
6. Interviews
7. Messages
8. Analytics
9. Settings

Mobile tabs: Home, Jobs, Candidates, Messages, Company.

## 3. EMP-01 — Employer dashboard

### Layout
- Header with company name, verification status and avatar.
- Metric cards: Active Jobs, Total Applicants, Shortlisted, Interviews.
- Main: recent applicants and job performance.
- Right rail: verification checklist, quick actions and support.

### Buttons
**Create Job**: primary; → EMP-03. If not verified, open verification explanation → EMP-02.
**Manage Jobs**: → EMP-04.
**View Applicants**: → EMP-05.
**Search Candidates**: → EMP-07, only if permitted.
**Schedule Interview**: → EMP-08.
**Messages**: → EMP-09.
**Company Profile**: → EMP-02.
**Analytics**: → EMP-10.
**Applicant card**: → EMP-06.
**Job card**: → EMP-04 detail.

Empty state: Create first job, complete verification, or invite team member depending on account status.

## 4. EMP-02 — Company profile and verification

### Layout
- Company identity: legal/trading name, website, industry, size, location, description, logo.
- Verification section: status, required evidence and submission history.
- Private evidence panel separated from public profile.

### Buttons
**Edit Profile**: enables editable fields; Save/Cancel.
**Upload Logo**: file picker, preview/crop, Save; validate file and remove metadata where appropriate.
**Upload Evidence**: secure file picker; classify evidence; show private status.
**Replace Document**: replace pending evidence while preserving audit history.
**Submit Verification**: confirmation summarises submitted items; sends to review queue.
**View Status**: shows Pending, Approved, More Information Required or Rejected.
**Resubmit**: enabled when evidence/reason is supplied.
Do not publish legal documents or private evidence on public company page.

## 5. EMP-03 — Create/edit job

### Desktop layout
- Stepper: Role Details, Description, Requirements, Application, Review.
- Main form and right preview panel.
- Sticky footer: Save Draft, Back, Continue/Preview.

### Mobile layout
- Single step per screen.
- Progress at top.
- Sticky Save Draft and Continue footer above safe area.

### Fields
Title, department, employment type, seniority, location, work mode, salary range/currency/pay period (optional but transparent), description, responsibilities, essential requirements, preferred requirements, benefits, closing date, application method, screening questions and contact route.

### Buttons
**Save Draft**: saves incomplete draft and returns to EMP-04.
**Continue**: validates current step and moves next.
**Back**: previous step, preserving values.
**Preview**: opens candidate-facing preview; Back returns to editor.
**Publish Job**: available only to verified/authorised employer and after all validation. If moderation is required, status becomes Pending Review, not Published.
**Submit for Review**: enters moderation queue.
**Cancel**: if dirty, prompt Save Draft, Discard, Stay.
**Duplicate Job**: creates a new draft; never republishes automatically.

## 6. EMP-04 — Manage jobs

- Tabs: Draft, Pending Review, Published, Paused, Closed, Rejected.
- Search and filter by status/date/role.
- Job row shows applicants, posted date, closing date and status.

Buttons:
**Create Job** → EMP-03.
**Open** → job detail and applicants.
**Edit** → EMP-03 with existing data.
**Pause**: confirmation; stops new applications if supported; existing records retained.
**Resume**: revalidate status and permission.
**Close**: confirmation; closes listing; does not delete application history.
**Duplicate**: creates draft.
**Applicants** → EMP-05.
**View Public Listing** opens public job detail.
Rejected listing shows moderator reason and Request Review/Edit path.

## 7. EMP-05 — Applicant pipeline

### Layout
- Search and filters.
- Board/list toggle.
- Stages: New, Reviewing, Shortlisted, Interview, Offer, Rejected.
- Candidate cards show name/initials, applied role, date, permitted profile summary and stage.

Buttons:
**Open Candidate** → EMP-06.
**Shortlist**: changes stage with audit event and optional note.
**Move Stage**: selector; consequential transitions require confirmation.
**Schedule Interview** → EMP-08 with candidate/job linked.
**Message** → EMP-09 with context.
**Reject**: confirmation; optional reason; communicate only through supported messaging/notification.
**Add Internal Note**: private employer-team note, never visible to candidate.
**Export**: aggregate or permitted candidate data only; log sensitive exports.
Drag-and-drop is optional on desktop; mobile always has explicit Move Stage action.

## 8. EMP-06 — Candidate detail

- Candidate information limited to profile visibility and application consent.
- CV/document preview with download permissions.
- Application answers and timeline.
- Evaluation form and private notes.

Buttons:
**View Profile**: opens permitted public profile.
**Preview CV**: secure viewer.
**Download CV**: only when permitted; log access if policy requires.
**Shortlist**: stage transition.
**Schedule Interview** → EMP-08.
**Message** → EMP-09.
**Evaluation**: opens structured form; Save stores employer-only evaluation.
**Change Stage**: stage menu and confirmation.
**Report**: opens abuse/privacy report flow.
No sensitive-trait inference or discriminatory ranking features.

## 9. EMP-07 — Candidate search

- Search by skills, role, location, experience and availability only where candidate has made fields discoverable.
- Filters are transparent and job-related.
- Candidate cards show public/consented fields.

Buttons:
**Search**: query permitted index.
**Clear**: reset filters.
**Save Search**: name and optional alert.
**Open Candidate**: EMP-06 or public profile.
**Add to Shortlist**: select target job/pipeline; confirm.
**Compare**: add to EMP-10 comparison view if available.
If candidate visibility is off, the record must not appear.

## 10. EMP-08 — Interview scheduling

Fields: candidate, job, interview title/type, date, start/end, time zone, location/video link, interviewer(s), notes and reminder.

Buttons:
**Send Invitation**: preview recipient/time/zone; confirm; send notification/email only through configured provider.
**Save Draft**: stores without notifying.
**Reschedule**: edit and send updated invitation after confirmation.
**Cancel Interview**: confirmation and cancellation notice if supported.
**Add to Calendar**: create calendar file/link.
**Copy Meeting Link**: only if a meeting URL exists.
Display time zone explicitly and handle daylight-saving conversions.

## 11. EMP-09 — Employer messaging

- Inbox list with unread state, search and filters.
- Thread shows participants, linked job/application and messages.
- Attachment status and scanning indicator.

Buttons:
**New Message**: choose permitted recipient and context.
**Open Thread**: load history.
**Attach**: secure file picker and validation.
**Send**: disabled when empty; rate limited; delivery state shown.
**Archive**: hides from inbox, preserves history.
**Report**: report abuse or suspicious content.
**Block**: only if product policy supports it; explain consequences.
Never expose email/phone unless shared by the participant or required by a consented workflow.

## 12. EMP-10 — Employer analytics

- Filters: date range, job, team and status.
- Metrics: views, applications, qualified pipeline counts, time-to-stage and interview outcomes where data supports it.
- Avoid unsupported demographic analytics.

Buttons:
**Date Range**: applies period.
**Job Filter**: select jobs.
**Export**: export authorised company aggregate data.
**Drill Down**: opens relevant job/applicant view.
Show data definitions and minimum sample thresholds where needed.

## 13. Recruiter workspace navigation

Desktop: Overview, Candidate Search, Pipeline, Clients, Messages, Reports, Settings.  
Mobile: Home, Candidates, Pipeline, Messages, Profile.

## 14. REC-01 — Recruiter dashboard

Cards: active requisitions, candidate pipeline, interviews, client tasks and alerts.

Buttons:
**Find Candidates** → REC-02.
**Pipeline** → REC-04.
**Manage Clients** → REC-05.
**Create Shortlist** opens client/job selection.
**Schedule** → employer interview flow with recruiter permission.
**Messages** → employer/recruiter messaging.
Candidate/task cards open the relevant record.

## 15. REC-02 — Candidate sourcing

- Search only candidates discoverable to the recruiter.
- Filters: job-related skills, role, experience and location.
- Results show visibility/consent status.

Buttons:
**Search** runs query.
**Save Search** stores filter.
**Open Candidate** opens permitted detail.
**Shortlist** selects client/requisition and records action.
**Compare** → REC-03.
**Report** opens moderation report.

## 16. REC-03 — Candidate comparison

- Side-by-side cards for job-relevant criteria.
- Show evidence and missing information; no inferred protected attributes.
- Mobile uses candidate tabs.

Buttons:
**Add Candidate** opens search.
**Remove Candidate** removes from comparison only.
**View Profile** opens permitted profile.
**Save Comparison** stores private workspace artifact.
**Export** only permitted fields; log export.
**Back** returns to sourcing with filters preserved.

## 17. REC-04 — Recruitment pipeline

- Board/list stages configurable by organisation.
- Candidate, client, requisition, stage and next action.

Buttons:
**Open Candidate** opens permitted detail.
**Move Stage** selector and confirmation.
**Schedule** opens interview form.
**Message** opens thread.
**Add Note** private note.
**Close Record** confirmation; preserves audit history.
All changes log actor and timestamp.

## 18. REC-05 — Client and team management

Buttons:
**Add Client** creates client record after required consent/relationship checks.
**Edit Client** changes permitted fields.
**Assign Recruiter** selects authorised team member.
**Remove Team Member** confirmation and access revocation.
**Change Permission** shows explicit permission matrix; Save logs change.
**View Activity** shows authorised audit events.
A recruiter cannot grant themselves organisation-owner permissions.

## 19. Admin workspace navigation

Separate admin shell with left sidebar:
1. Overview
2. Users
3. Employers
4. Recruiters
5. Jobs
6. Applications
7. Reports & Moderation
8. AI Management
9. Credit Management
10. Payments & Reconciliation
11. Notifications
12. Support Tickets
13. Analytics
14. System Health
15. Audit Logs
16. Security Centre
17. Roles & Permissions
18. Integrations
19. Platform Settings
20. Admin Profile
21. Logout

Admin pages are not discoverable from public navigation. Admin access requires MFA and explicit permissions.

## 20. ADM-01 — Admin overview

- Summary cards: total accounts, active employers, pending verifications, jobs awaiting review, open reports, support backlog, payment exceptions and service status.
- Charts for account/job activity and system health.
- Recent high-priority audit events.
- Do not expose user content unnecessarily.

Buttons:
**Users** → ADM-02.
**Employers/Recruiters** → ADM-04.
**Jobs** → ADM-05.
**Reports** → ADM-06.
**AI** → ADM-08.
**Credits** → ADM-09.
**Payments** → ADM-10.
**Support** → ADM-11.
**System Health** → ADM-14.
**Audit** → ADM-15.
**Security** → ADM-16.
Each metric card opens a filtered list with permission check.

## 21. ADM-02 / ADM-03 — User management and detail

### User list
Search by permitted identifier; filters by role, status, verification and creation date. Never expose password hashes or secrets.

Buttons:
**Search** filters list.
**Open User** → ADM-03.
**Suspend** opens reason, duration and confirmation.
**Restore** confirms restoration and logs actor.
**View Appeal** opens appeal record.
**Export** only authorised minimal fields.

### User detail
Tabs: Overview, Roles, Verification, Sessions, Reports, Support and Audit.

Buttons:
**Suspend/Restore** require reason and confirmation.
**Change Role** requires elevated permission, reason and possibly second approver.
**Reset Verification** only through a controlled process.
**Revoke Sessions** confirms and invalidates sessions.
**Add Internal Note** private and audited.
**View Audit** filters events for that account.
No admin action may impersonate a user without a separately designed, audited support mode.

## 22. ADM-04 — Employer/recruiter verification

- Queue tabs: Pending, More Information, Approved, Rejected.
- Review organisation identity and private evidence in restricted viewer.

Buttons:
**Open Submission** shows evidence and history.
**Approve** requires permission and confirmation; writes status and audit.
**Reject** requires reason and provides user-visible explanation.
**Request More Information** specifies missing evidence and due date.
**View History** shows previous submissions.
Evidence downloads are logged and access-limited.

## 23. ADM-05 — Job moderation

- Queue filters: Pending, Reported, Published, Paused, Closed.
- Detail shows listing, employer verification, reports and history.

Buttons:
**Approve** publishes only if policy conditions pass.
**Reject** requires reason.
**Request Edit** returns job to employer with instructions.
**Pause/Close** confirmation and reason.
**View Employer** → permitted employer record.
**View Reports** → related moderation cases.
Every decision creates audit event and user notification.

## 24. ADM-06 — Reports and moderation

- Queue by severity, age, type and assigned moderator.
- Case detail shows report, subject, evidence and actions.

Buttons:
**Assign** selects moderator.
**Add Note** internal note.
**Request Evidence** sends safe request.
**Resolve** requires outcome/reason.
**Escalate** routes to authorised lead.
**Reopen** requires reason.
**Restrict Content/Account** only with policy permission and confirmation.
Maintain evidence retention and appeal history.

## 25. ADM-07 — Application monitoring

- Search/filter by date, job, employer, status and exception.
- Show operational metadata, not unrestricted private application content.

Buttons:
**Open Record** only if permission and legitimate need.
**Flag** creates internal review.
**Export Aggregate** provides anonymised/aggregated metrics where possible.
Sensitive access is audited.

## 26. ADM-08 — AI management

- Provider status, configured model, request volume, latency, errors, fallback status and cost metrics.
- Secret values are never displayed.

Buttons:
**Enable/Disable Provider** confirmation and permission check.
**Change Model** select approved model, run validation and save.
**Test Connection** uses server-side secret without exposing it; returns redacted result.
**View Errors** opens redacted logs.
**Configure Limits** sets usage, rate and spend limits.
**Usage** shows aggregate metrics.
Provider fallback must preserve operation ID and avoid double charging.

## 27. ADM-09 — Credit management

- Feature pricing table with version, cost, effective date and status.
- Ledger search and adjustment queue.

Buttons:
**Edit Feature Cost** opens amount, rationale, effective date and preview; approval required.
**View Transaction** → WAL-06.
**Refund** requires reason, transaction/operation reference and permission; high-value may require second approval.
**Grant Promotional Credits** requires recipient, amount, reason, terms and expiry if any; purchased-credit rules are not changed.
**Suspend Paid Operation** blocks new operations only after confirmation.
**Export Ledger** restricted and audited.
Never directly overwrite a wallet balance.

## 28. ADM-10 — Payment reconciliation

- Payment provider totals vs internal verified transactions.
- Exception queues: pending too long, amount mismatch, duplicate event, refund mismatch, settlement mismatch.

Buttons:
**Refresh** reloads provider/internal status.
**Reconcile** runs safe matching and produces report; no blind crediting.
**Open Dispute** creates case.
**View Provider Reference** shows permitted redacted metadata.
**Export** permission-gated.
Manual adjustment uses ADM-09 controlled ledger adjustment, never direct SQL or silent balance edit.

## 29. ADM-11 — Support administration

- Queue: New, Assigned, Waiting for User, Escalated, Resolved.
- Ticket detail includes user-visible thread and separate internal notes.

Buttons:
**Assign** selects support agent.
**Reply** sends public reply after preview.
**Request Information** sends user-facing request.
**Escalate** routes to specialist.
**Resolve** requires resolution summary.
**Reopen** records reason.
**View User** shows only necessary account context.
Never request passwords, OTPs, payment PINs or full card data.

## 30. ADM-12 — Notifications

Fields: title, body, audience, channel, schedule, deep link and expiry.

Buttons:
**Create** opens editor.
**Preview** shows web/mobile rendering.
**Schedule** sets time and audience.
**Send** confirmation with recipient estimate.
**Cancel** cancels scheduled notification.
**Delivery Report** shows success/failure counts.
Use rate limits and opt-out preferences where applicable.

## 31. ADM-13 — Analytics

- Filters: date, role, country/region where lawful, product module and status.
- Show definitions, aggregation thresholds and data freshness.

Buttons:
**Date Range**, **Filter**, **Export Aggregate**, **Drill Down**.
Avoid exposing personal records from aggregate analytics.

## 32. ADM-14 — System health

- Services: API, database, cache, queue, workers, email, payment, AI provider, object storage.
- Show uptime, latency, error rate, queue depth, recent deployments and incidents.

Buttons:
**Refresh** updates status.
**View Logs** opens redacted logs.
**View Incident** opens incident record.
**Maintenance Mode** requires high permission, reason, impact preview and confirmation; user-facing banner shown.
**Deployment History** opens release list.
Never use a UI action to delete logs or backups.

## 33. ADM-15 — Audit logs

- Search by actor, action, target, time, request ID and severity.
- Append-only/tamper-evident event records.

Buttons:
**Search**, **Filter**, **Open Event**, **Export**.
No ordinary edit/delete control.
Export access itself is audited.

## 34. ADM-16 — Security centre

- Active alerts, suspicious login patterns, admin sessions, security incidents and policy checks.

Buttons:
**Revoke Session** confirmation.
**Require Reauthentication** triggers user security step.
**Review Alert** opens event.
**Escalate** creates incident.
**View Audit** opens ADM-15.
No mass account action without explicit scope, approval and audit.

## 35. ADM-17 — Roles and permissions

- Role list and permission matrix.
- Deny by default; permissions grouped by domain and action.

Buttons:
**Create Role** names role and starts with no permissions.
**Edit Role** opens matrix.
**Assign Permission** requires explanation.
**Assign User** selects user and role.
**Remove Assignment** confirmation.
**Review Changes** shows diff.
**Save** persists with audit and may require second approver.
Prevent privilege escalation and last-admin lockout.

## 36. ADM-18 — Integrations and platform settings

- Integration cards for email, payment, AI, storage and analytics.
- Configuration fields reveal only masked values and metadata.

Buttons:
**Configure** opens settings.
**Test** validates connection.
**Enable/Disable** confirmation.
**Rotate Credential** uses secret manager and never displays prior secret.
**Save** validates and writes securely.
Feature flags include description, rollout percentage and rollback path.
Changes are versioned and audited.

## 37. Acceptance tests

- Employer cannot publish before required verification.
- Employer cannot access another company's candidates or applications.
- Recruiter sees only candidates discoverable/consented and client-assigned records.
- Employer team roles enforce least privilege.
- Admin pages reject unauthorised roles server-side.
- Admin MFA is required.
- Sensitive admin actions produce immutable audit events.
- Credit refunds/grants use ledger adjustments, not direct balance writes.
- Payment reconciliation never credits unverified transactions.
- AI provider keys never appear in browser responses or logs.
- Moderation decisions have reasons, history and appeal route.
- Support staff cannot access passwords or one-time codes.
