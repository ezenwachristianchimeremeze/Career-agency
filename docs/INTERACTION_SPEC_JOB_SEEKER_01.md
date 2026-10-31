# Detailed Interaction Specification — Job-Seeker Workspace

**Scope:** JS-01 to JS-10, with exact layout regions, control placement, tap outcomes and states.  
**Status:** Design specification only.

## 1. Workspace navigation

### Desktop sidebar order

1. Overview
2. Find Jobs
3. Saved Jobs
4. Applications
5. Interview Calendar
6. Career Goals
7. CV Studio
8. Cover Letters
9. Interview Preparation
10. Career Roadmap
11. Portfolio
12. AI Assistant
13. Analytics
14. Documents

Sidebar footer: Help Centre, Settings, profile summary and Logout.

### Mobile bottom navigation

- Home
- Jobs
- Applications
- AI
- Profile

Secondary pages are opened from these destinations. Use a back arrow in the top bar and preserve the active bottom tab.

## 2. JS-01 — Job-seeker dashboard

### Desktop layout

- Top bar: "Good morning/afternoon/evening" greeting; global search; notification bell; wallet balance chip; avatar menu.
- First row: 4 compact metric cards — Applications, Interviews, Saved Jobs, Profile Completion.
- Main left column (about 2/3): Application progress chart; Upcoming Interviews; Recommended Jobs.
- Right column (about 1/3): Wallet card; profile completion checklist; career tip; recent activity.
- Use clear empty states instead of fabricated metrics.

### Mobile layout

- Greeting and avatar at top.
- Wallet balance card directly below greeting.
- Horizontal metric cards.
- Upcoming interview card.
- Recommended jobs list.
- Recent activity.
- Fixed bottom navigation.

### Controls

**Global Search**
- Position: top bar desktop; compact search field below greeting on mobile.
- Tap/submit: search jobs and relevant user-owned records; show grouped results; selecting a job → JS-04; selecting application → JS-09.

**Notification bell**
- Top right.
- Tap → JS-17; unread count is an accessible badge.

**Wallet balance**
- Top bar and wallet card.
- Tap → WAL-01.
- Display actual available balance from server; never a hardcoded demo amount in production.

**Find Jobs**
- Primary dashboard action, first row above recommended jobs.
- Tap → JS-02.

**View All Applications**
- Link at top right of application widget.
- Tap → JS-08.

**Continue Profile**
- Button inside profile checklist.
- Tap → JS-16 at first incomplete section.

**Buy Credits**
- Button inside wallet card.
- Tap → WAL-02.

**View Transactions**
- Secondary wallet link.
- Tap → WAL-04.

**Job recommendation card**
- Entire card opens JS-04.
- Save icon toggles saved state without opening detail.
- Apply button → JS-07.
- Match percentage appears only if backed by an actual comparison; tap opens JS-05.

**Application activity item**
- Tap → JS-09 for that application.
- More menu: Add Note, Change Status, Open Job; destructive delete is not placed in the quick menu.

### Dashboard states

- New user: onboarding completion card, no fabricated jobs/applications.
- Returning user: current metrics and recent activity.
- No job matches: refine preferences / Find Jobs.
- No applications: Start Searching → JS-02.
- Wallet empty: Buy Credits; free features remain accessible.
- Service unavailable: stale data is labelled with last-updated time and Retry.
- Loading: skeletons that match final card geometry.

## 3. JS-02 — Job discovery

### Desktop layout

- Page title and result count.
- Search row: keyword, location, Search button.
- Filter toolbar below: Filters, Sort, Saved Searches, Create Alert.
- Main content: job result cards.
- Optional right rail: job search tips and recently viewed jobs.

### Mobile layout

- Search field at top.
- Location field below or combined when space permits.
- Filter and Sort buttons in a sticky row.
- Job cards stacked vertically.
- Avoid a permanently visible right rail.

### Job card structure

- Employer logo (fallback initials).
- Job title and verified employer indicator.
- Employer name, location and work mode.
- Salary only when supplied and clearly labelled with currency/period.
- Posted date and source.
- Short description excerpt.
- Match indicator only when valid.
- Bottom actions: Save icon and View Job button.

### Controls and outcomes

**Keyword field**
- Enter title, skill or company; Enter submits.
- Preserve current search when returning from job detail.

**Location field**
- Search location; user may choose remote or specific region.
- Do not silently use precise device location.

**Search**
- Desktop right of search fields; mobile keyboard action and optional visible button.
- Tap: request first page; update URL/query state; show skeletons.
- Empty result: offer Clear Filters and Edit Search.
- Error: show Retry without clearing the query.

**Filters**
- Opens JS-03 as desktop side drawer or mobile bottom sheet.
- Badge count shows number of active filters.
- Apply returns to JS-02 with filters applied.

**Sort**
- Menu: Relevance, Newest, Closing Soon, Salary (when reliable).
- Selecting option refreshes results and closes menu.

**Saved Searches**
- Opens saved-search list.
- Selecting a saved search restores its query and filters.
- Rename/Delete available in each saved-search menu.

**Create Alert**
- Opens alert setup with current search prefilled.
- Save Alert stores frequency/channel and routes to alert confirmation.
- User can disable alerts in settings.

**Save icon**
- Tap toggles saved state; show brief confirmation.
- If unauthenticated, route to login and return to the job after login.
- Prevent duplicate records.

**View Job / card**
- Tap → JS-04.
- Open in same app; preserve search scroll position on Back.

**Load More**
- Bottom of list; loads next page and appends results.
- Disable while loading; do not duplicate jobs.

**Report Job**
- In overflow menu; opens report dialog with reason and optional details.
- Submit creates moderation report; confirmation includes report reference.

## 4. JS-03 — Job filters

### Desktop

Right-side drawer about 400 px wide; overlay dims results. Drawer header has title and close icon. Footer is sticky with Reset and Apply Filters.

### Mobile

Bottom sheet expands to near full height. Header and footer remain visible; filter content scrolls.

### Filter controls

- Location / radius where user explicitly supplies it.
- Remote, hybrid, on-site.
- Employment type.
- Experience level.
- Industry/category.
- Salary minimum/maximum and currency.
- Date posted.
- Employer verification.
- Job source.
- Application method.

### Buttons

**Close (X)**
- Top right; closes without applying draft changes.

**Reset**
- Bottom left; clears all filter selections in the drawer.
- Does not refresh until Apply Filters is tapped.

**Apply Filters**
- Bottom right primary.
- Applies selected values, closes drawer, refreshes JS-02 and updates active-filter chips.

**Save Search**
- Secondary action after filters are selected.
- Opens small dialog for search name and alert preference.
- Save persists; Cancel closes.

## 5. JS-04 — Job detail

### Desktop layout

- Breadcrumb/back link.
- Main column: title, employer, metadata, description, responsibilities, requirements, benefits and application instructions.
- Right sticky panel: salary, location, work mode, posted/closing date, employer status, Apply Now and Save Job.
- Lower section: similar jobs and report link.

### Mobile layout

- Back arrow and overflow menu.
- Job title and employer.
- Metadata chips.
- Description sections.
- Sticky bottom action bar: Save icon and Apply Now.
- Similar jobs below.

### Controls

**Back to Results**
- Returns to JS-02 at previous scroll position and filters.

**Apply Now**
- Primary action in right panel / mobile sticky bar.
- Internal application: JS-07.
- External application: show clear destination disclosure and open external site after user action.
- Do not mark as submitted automatically when the external site opens.
- If already applied, label becomes View Application → JS-09.

**Save Job**
- Toggles saved state; updates JS-06.
- Show saved/removed feedback.

**Share**
- Native share sheet on mobile; copy link fallback on web.
- Do not include private user information in shared URL.

**Analyse with AI**
- Opens JS-05.
- Show the exact credit cost before AI execution and use global credit confirmation.

**Report**
- Opens report dialog; select reason, optional details, Submit.
- Confirmation → JS-17 or report receipt.

**Company name/logo**
- Opens employer public profile, with only approved public details.

## 6. JS-05 — AI job evaluation

### Layout

- Header identifies job and selected CV/profile.
- Summary card: match estimate with clear methodology note.
- Sections: relevant strengths, missing requirements, transferable skills, potential concerns, suggested next steps.
- Bottom actions: Tailor CV, Cover Letter, Apply, Save Analysis.

### Buttons

**Analyse Job**
- Primary when no report exists.
- Opens compact global credit dialog with feature name, debit, total and remaining balance.
- Cancel closes without debit.
- Confirm starts server operation; button changes to "Analysing…".
- Success displays report; failed operation follows refund/retry policy.

**Choose CV**
- Opens CV selector; selection refreshes the comparison only after user confirms.

**Tailor CV**
- → JS-24 with job and selected CV prefilled.

**Prepare Cover Letter**
- → JS-25 with job context prefilled.

**Apply**
- → JS-07.

**Save Analysis**
- Stores report in user documents/history; no extra charge unless explicitly disclosed.

**Back to Job**
- → JS-04.

### Safety and quality rules

- Do not infer missing experience or credentials.
- Distinguish required from preferred qualifications.
- Explain that a match estimate is guidance, not an employer decision or ATS guarantee.
- Clearly label uncertainty where job descriptions are incomplete.

## 7. JS-06 — Saved jobs

### Layout

- Page title, saved count, search within saved jobs, filter chips.
- Cards reuse JS-02 job card structure.
- Expired/closed jobs remain in history but cannot be applied to.

### Buttons

**Open Job** → JS-04.
**Apply** → JS-07 only if still open.
**Remove Saved Job** → removes bookmark; no deletion of the employer's listing.
**Find More Jobs** → JS-02.
**Filter** → saved-job filter drawer.
**Sort** → date saved, newest posted, closing soon.

Empty state: "No saved jobs yet" with Find Jobs button.

## 8. JS-07 — Application preparation

### Layout

- Step indicator: 1 Review, 2 Documents, 3 Questions, 4 Final Check.
- Job summary strip pinned at top.
- Main form column and optional guidance rail.
- Mobile uses sequential steps and a sticky footer.

### Step 1 — Review application

Fields: applicant name/contact pulled from profile, editable per-application if allowed; job destination and employer; application method; deadline.

Buttons:
- Edit Profile → JS-16.
- Back → JS-04.
- Continue → Step 2 after validation.

### Step 2 — Documents

Controls:
- CV selector.
- Upload CV.
- Cover letter selector/editor.
- Optional supporting documents.

Buttons:
- Choose CV opens selector.
- Upload opens secure file picker and validates type/size.
- Create CV → JS-22.
- Create Cover Letter → JS-25.
- Preview opens document preview.
- Remove attachment removes it from this application only, not from the document library.
- Continue → Step 3.

### Step 3 — Screening questions

- Render employer-provided questions with appropriate input types.
- Required questions visibly marked.
- Save Draft stores partial answers.
- Back → Step 2.
- Continue → Step 4 when required answers validate.

AI may help phrase a truthful response but must not invent work history, authorisation, qualifications or legal declarations.

### Step 4 — Final check

- Checklist of destination, CV, cover letter, required answers and attachments.
- Preview Application.
- Save Draft.
- Continue to Employer (external) or Submit Application (internal API).

**Submit Application**
- Confirmation dialog summarises job and documents.
- Confirm submits once with idempotency key.
- Success creates application record and routes to JS-09.
- Failure leaves draft intact and offers safe retry.
- If external: button says "Continue to Employer"; after opening, user must return and explicitly mark as submitted. Do not claim the application was submitted by Career Agency.

## 9. JS-08 — Application tracker

### Desktop

- Board/list toggle at top right.
- Kanban columns by status; each card shows job, employer, date and next event.
- Filters and search above board.

### Mobile

- Horizontal status tabs and vertically stacked cards.
- Avoid tiny drag-and-drop targets; use Change Status menu.

### Controls

**Add Application**
- Opens manual application form; Save creates record → JS-09.

**Board/List toggle**
- Changes presentation only; preserves filters and scroll.

**Search**
- Searches user's own application records.

**Filter**
- Status, date, employer, role, source and next interview.

**Export**
- Exports only the current user's selected records; confirm scope and format.

**Application card**
- Tap → JS-09.

**Change Status**
- Opens status menu. Selecting a status shows confirmation when it has consequential meaning (e.g. Withdrawn).
- Record status event with timestamp and actor.

**Calendar**
- → JS-10.

### Empty and error states

- No applications: Add Application and Find Jobs.
- No filtered results: Clear Filters.
- Load error: Retry; do not replace existing local display with blank data.

## 10. JS-09 — Application detail

### Layout

- Header: role, employer, current status badge, overflow menu.
- Main: timeline, job details, documents, screening answers, notes.
- Side panel: next interview, reminders, quick actions.
- Mobile sections become tabs or stacked cards.

### Buttons

**Edit**
- Opens editable application fields; Save persists; Cancel discards only unsaved changes.

**Change Status**
- Opens status selector.
- Applied / Under Review / Shortlisted / Interview / Offer / Rejected / Withdrawn.
- Confirm consequential changes and add timeline event.
- A rejected application cannot silently become an offer; all transitions are explicit.

**Add Note**
- Opens text dialog; Save creates timestamped private note.

**Add Interview**
- → JS-10 with application linked.

**Upload Document**
- Secure file picker; attach to this application only.

**View Job**
- → JS-04 if listing still exists; show archived snapshot if removed.

**Withdraw**
- Confirmation explains effect; Confirm sets Withdrawn and records event. This does not contact employer unless a supported withdrawal integration exists.

**Delete**
- Overflow menu, red destructive action; confirmation requires explicit Delete.
- Explain whether deletion removes only the tracker record or also attachments; default is to remove the user's record and associated copies in line with retention policy.
- Do not offer irreversible delete if a legal hold or dispute applies.

## 11. JS-10 — Interview calendar

### Desktop layout

- Header: title, date navigation, view selector (Month / Week / List), Add Interview.
- Main calendar grid.
- Right rail: upcoming interviews and reminders.

### Mobile layout

- Month strip or date picker, then chronological agenda list.
- Add Interview floating/primary button above bottom navigation.

### Buttons

**Previous / Next**
- Move calendar period; do not change event data.

**Today**
- Return to current date.

**Month / Week / List**
- Switch view and preserve selected date.

**Add Interview**
- Opens form: title, linked application, date, start/end, time zone, location/video link, interviewer, reminder and notes.
- Save creates event; Cancel closes.
- Validate end after start and display time zone.

**Interview event**
- Tap opens event detail sheet.
- Edit opens form.
- Cancel Interview requires confirmation; record cancellation.
- Join Meeting appears only when a valid meeting URL exists and opens only after user tap.
- Add to Device Calendar exports an .ics/calendar event; it does not grant calendar account access.

**Reminder settings**
- Choose notification timing and channel; save in user preferences.

## 12. Shared quality gates for JS-01 to JS-10

- Every list is paginated and has loading, empty, error and retry states.
- Every record is scoped to the authenticated user.
- Back navigation preserves search, filters, board view and safe drafts.
- Every date/time displays the user's configured time zone.
- External links are clearly labelled and never auto-submit.
- All destructive actions require confirmation.
- No mock balances, fake metrics or invented job data in production.
- Mobile layout tested at 320, 360, 390 and 430 px widths.
- Web keyboard navigation, focus order and screen-reader labels are tested.
