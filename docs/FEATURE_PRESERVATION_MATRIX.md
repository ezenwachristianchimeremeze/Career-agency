# Feature Preservation and Rebuild Matrix

**Baseline:** GitHub `main` commit `9eb55335394761832564cb7240d6d21b15cecd6d`  
**Working branch:** `career-agency-production-rebuild`  
**Purpose:** Prevent accidental loss of current capabilities during the rebuild.

This matrix records the current feature families identified during the preliminary source audit. It is a planning and verification checklist, not evidence that each feature currently works correctly. Before implementation, each row must be expanded with exact route names, templates, functions, database tables, dependencies and test names from the source.

| Existing capability | Destination in new product | Preservation rule | Required verification |
|---|---|---|---|
| Job discovery and collection | JS-02 to JS-06; jobs API | Preserve source adapters, filters and useful job records; replace unsafe scraping only after source review | Unit tests for source adapters, deduplication, expiry and pagination; integration tests |
| Job queue | JS-02, JS-08; background job service | Preserve user-visible queue behaviour and retry semantics | Queue lifecycle, cancellation, retry and ownership tests |
| Application pipeline | JS-07 to JS-10 | Preserve statuses, notes, history and user data | Migration test plus status transition and ownership tests |
| AI chat and streaming | JS-19 and JS-20; AI service | Preserve conversations and streaming UX; move provider access behind server-side gateway | Streaming, cancellation, provider failure, history and credit idempotency tests |
| CV upload and extraction | JS-18, JS-21 and JS-22 | Preserve supported file formats and extracted user content | MIME/size validation, malicious upload tests, extraction regression tests |
| ATS and job matching | JS-05, JS-23 and JS-24 | Preserve scoring inputs and explainability; do not promise ATS pass | Golden test cases, keyword alignment, formatting and no-fabricated-facts tests |
| Cover-letter generation | JS-25 | Preserve prompts and useful output behaviour; add cost preview and draft review | Output quality cases, credit debit/refund tests |
| Interview practice | JS-26 to JS-28 | Preserve question/session functionality; add consent and recording state | Session lifecycle, permission, accessibility and AI feedback tests |
| Career roadmap | JS-11, JS-13 and JS-14 | Preserve saved goals and milestones | Migration, progress, reminders and ownership tests |
| Workspace tasks | JS-11, JS-13 and dashboard widgets | Preserve task data and completion state; map tasks to goals where possible | CRUD, due-date, reminder and ownership tests |
| Profile and settings | JS-16, SET-01 to SET-06 | Preserve user preferences and profile content | Validation, privacy, session and migration tests |
| Recruitment inbox | EMP-09 / REC-05 and messaging service | Preserve message history; add tenant/participant access rules | Message permissions, attachment scanning and delivery tests |
| Voice-command endpoint | JS-19 voice input and mobile voice UI | Preserve as optional interface; do not assume microphone permission | Permission-denied, no-speech, transcription error and accessibility tests |
| Export functions | CV/document exports and data export | Preserve formats where safe; separate document export from personal-data export | DOCX/PDF rendering, selectable text and data export completeness tests |
| Backup-related functions | Platform operations | Replace ad hoc backup with managed, encrypted, scheduled backup and tested restore | Restore drill, retention and access-control tests |
| Existing tests | New domain and integration test suites | Keep useful tests, port them and add regression coverage; do not delete to make builds green | Test inventory, baseline results and coverage report |

## Required source-mapping worksheet

For every existing capability, fill the following before replacing its code:

- Current source file and exact line/function.
- Current URL/route and HTTP method.
- Template or client component.
- Database tables/columns and sample record count.
- External services and environment variables.
- Current test names and current pass/fail status.
- User-visible behaviour and edge cases.
- New screen IDs and API endpoints.
- Data migration or compatibility plan.
- Acceptance test and rollback plan.
- Decision: preserve as-is temporarily, refactor, rebuild, or retire.
- Approval reference for any retirement or destructive change.

## Stop conditions

Do not begin destructive replacement if:
- the current database has not been backed up;
- a feature has no mapped destination;
- user-owned data has no migration plan;
- the replacement has no acceptance test;
- the old and new app versions cannot be run or compared safely;
- a required dependency or imported module is missing;
- a payment, authentication or privacy control is only simulated.

## Completion criteria

The matrix is complete only when every existing route, important function, database table and automated test has an explicit disposition. The rebuild can then proceed feature by feature, with old behaviour protected by regression tests.
