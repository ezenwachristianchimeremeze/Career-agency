# Detailed Interaction Specification — CV Studio, AI Assistant and Career Tools

**Scope:** JS-11 to JS-30.  
**Status:** Product interaction specification; implementation pending.

## 1. JS-21 — CV library

### Layout
- Desktop: page title and primary Create CV button; list/grid of CV cards in main area.
- Mobile: title, full-width Create CV, stacked CV cards.
- Each card: CV title, target role, last edited, file type, default marker and overflow menu.

### Controls
**Create CV** → JS-22 with a blank profile-backed draft.
**Upload CV** → native file picker; accept configured document formats; validate size, extension and actual MIME; scan before processing.
**Open/Edit** → JS-22.
**Set as Default** → server saves default CV; one default per user/profile context.
**Rename** → inline or dialog; Save/Cancel.
**Download** → generated document download after permission check.
**Analyse ATS** → JS-23; disclose cost before analysis.
**Delete** → confirmation explains that the CV is removed from the user's library; preserve any application snapshot required by retention rules.
**Version History** → opens version list; select version to preview or restore as a new version, never silently overwrite current content.

States: no CV (Create or Upload); processing (progress and cancel where supported); unsupported file; extraction failure; duplicate upload; service unavailable; ready.

## 2. JS-22 — CV Studio

### Desktop layout
- Top command bar: Back to CVs, document title, Saved/Unsaved indicator, Undo, Redo, Preview, Export.
- Left rail (220–260 px): section navigator.
- Centre (flexible): document editor, page-like preview or structured fields.
- Right rail (280–320 px): AI tools and contextual guidance.
- Main Save action visible in top bar; autosave status displayed.

### Mobile layout
- Header: back, document title and more menu.
- Tabs: Sections, Edit, Preview, AI.
- Section list opens as a full-height panel.
- Editor uses large fields and clear section boundaries.
- Bottom action row: Save and Preview; keyboard must not obscure focused fields.

### Sections
Contact details; Professional Summary; Skills; Work Experience; Education; Projects; Certifications; Publications; Awards; Languages; Links. Users may add, remove or reorder optional sections.

### Controls
**Add Section**: opens section picker; selecting adds an editable section.
**Remove Section**: overflow action; confirmation if it contains content; user may cancel.
**Move Up / Move Down**: reorder section; update preview immediately.
**Edit Field**: manual changes are free; save locally then sync.
**Undo / Redo**: revert editor changes within available history.
**Save**: persist draft; show saved timestamp. If offline, mark local pending sync and retry later.
**Preview**: opens document preview; Back returns to same editing location.
**Improve with AI**: opens tool menu; selecting an operation opens the global credit confirmation before sending content to AI.
**Tailor to Job**: → JS-24.
**Analyse ATS**: → JS-23.
**Version History**: view, compare, preview and restore as new version.
**Export**: choose DOCX or text-based PDF; preview before download. Exporting an existing saved CV is free under current design rules.
**Back to CVs**: if unsaved changes remain, show Save, Discard, Stay.

### Truthfulness controls
- AI may improve expression but cannot create employers, job titles, dates, qualifications, certifications, metrics or skills.
- If information is missing, show a prompt to supply it.
- Clearly mark AI-proposed changes and let the user accept/reject them individually.
- Preserve the original version when applying AI changes.

## 3. JS-23 — ATS analysis

### Layout
- Header: CV name and selected target job (optional).
- Score/compatibility estimate card with explanation that no ATS pass is guaranteed.
- Sections: file readability, headings, keyword alignment, skills, experience, grammar, layout, missing information.
- Right/secondary panel: recommended improvements.

### Controls
**Run Analysis**: show exact cost in credits and global confirmation; on confirm run analysis; show progress and result; failed delivery follows refund/retry policy.
**Choose Job**: select saved job or paste job description; validate text.
**View Finding**: jump to affected CV section in JS-22.
**Fix Manually**: JS-22 at that section; free.
**Improve with AI**: show operation and cost confirmation.
**Download Report**: export accessible PDF/text report.
**Back to CV**: JS-22.
No universal pass percentage, ranking or interview outcome may be promised.

## 4. JS-24 — CV tailoring

### Layout
- Top: selected job and CV.
- Two-column comparison on desktop: current CV content and proposed changes.
- Mobile: Current / Proposed tabs.
- Change list grouped by section; every suggested edit has evidence/context.

### Controls
**Select CV** and **Select Job**: choose source records.
**Analyse Requirements**: identify relevant keywords and requirements; cost disclosed if paid.
**Generate Suggestions**: global credit confirmation; do not alter source CV.
**Accept Change**: apply that single change to a new draft version.
**Reject Change**: remove suggestion.
**Accept All**: confirmation summarises number of changes; only applies to a new version.
**Edit Manually**: free editor.
**Save New Version**: creates version linked to target job.
**Export**: DOCX/PDF.
**Cancel**: return to previous screen without changing original CV.

## 5. JS-25 — Cover Letter Studio

### Layout
- Job selector and CV/profile context at top.
- Tone selector (professional, concise, warm, formal) and optional instructions.
- Editable letter area.
- Preview and history panel.

### Controls
**Choose Job**: select saved job or enter job details.
**Choose CV/Profile**: select source facts.
**Generate Letter**: show cost confirmation; generate draft.
**Rewrite Paragraph**: select paragraph, show smaller operation cost, confirm, replace only after acceptance.
**Improve Grammar**: show cost if AI-powered; manual edits remain free.
**Undo**: revert last change.
**Save Draft**: persist.
**Preview**: formatted preview.
**Copy**: copy letter text.
**Export DOCX/PDF**: generate download.
**Back**: preserve draft.
AI must not invent relationship to employer, achievements or experience.

## 6. JS-19 — AI Assistant

### Desktop layout
- Left conversation rail (280 px): New Chat, search, recent conversations, archived.
- Centre: conversation transcript and composer.
- Optional right context panel: selected job, CV, application or document.
- Header: current conversation title, model/provider status only if useful, overflow menu.

### Mobile layout
- Header with back/menu and conversation title.
- Chat transcript scroll area.
- Composer fixed above safe area and keyboard.
- Attachment and voice controls beside composer; send button at far right.
- History opens as a full-screen drawer.

### Composer controls
**Text field**: multiline; Enter sends only if user preference allows; Shift+Enter inserts newline on web.
**Attach**: opens file picker; user reviews selected attachment before sending; remove attachment before send.
**Voice Input**: asks for microphone permission; show recording/listening indicator; Stop ends capture; user reviews transcript before sending. Denied permission offers typed input.
**Send**: primary arrow button; disabled for empty content or while the same message is submitting; creates message and streams response.
**Stop**: replaces Send during streaming; stops generation if provider supports cancellation; partial response remains labelled incomplete.
**Regenerate**: menu on assistant message; shows any credit cost and confirmation before another paid generation.
**Copy**: copies selected message; toast confirms.
**Read Aloud**: text-to-speech playback; Play/Pause/Stop controls; does not send content externally beyond configured speech service.
**Edit and Resend**: available on user's own message; show preview and confirmation if it triggers paid processing.
**Feedback**: thumbs up/down with optional reason; no public exposure.
**Delete Message**: confirmation; clarify whether conversation remains.
**Rename Chat**: inline title editor; Save/Cancel.
**Archive**: removes from active list but retains in archive.
**Delete Conversation**: destructive confirmation and clear retention explanation.
**Export**: download selected conversation in supported format.
**New Chat**: create blank conversation.
**Clear History**: confirmation; never silently delete all conversations.

### AI response states
- Streaming; completed; stopped; provider unavailable; timeout; safety refusal; context too long; attachment unsupported; offline.
- Retry does not double-charge. Server operation ID and idempotency key bind retries.
- Show AI-generated content as a draft and remind users to review important claims.
- Do not train on user data or share data with providers beyond the disclosed processing terms.

## 7. JS-20 — Chat history

**Search** filters titles and permitted conversation content.
**Open** loads selected thread.
**Rename** updates title.
**Archive** moves thread to archive.
**Restore** returns archived thread.
**Delete** confirmation then delete according to retention policy.
**Export** creates file.
**New Chat** opens JS-19.
Empty state links to New Chat.

## 8. JS-26 — Interview preparation

### Layout
- Job/application context card.
- Interview type and experience level.
- Preparation checklist.
- Generated question set and suggested evidence areas.

### Controls
**Choose Application**: links an application from JS-09.
**Choose Interview Type**: behavioural, technical, screening, case, general.
**Generate Questions**: show credit debit confirmation; generate question set.
**Start Practice**: → JS-27.
**Save Set**: stores question set.
**Add Interview to Calendar**: → JS-10 with linked application.
**Preparation Tips**: open contextual guidance.
Generated questions are practice material, not a prediction of exact employer questions.

## 9. JS-27 — Interview practice

### Layout
- Progress (e.g. Question 2 of 8).
- Current question.
- Answer text area and optional voice input.
- Timer is optional and user-controlled; no pressure-based countdown by default.
- Previous/Next controls and session status.

### Controls
**Start Session**: begins practice and creates session.
**Record Answer**: requests microphone permission and starts visible recording.
**Stop Recording**: ends capture; transcript is shown for review.
**Edit Transcript**: user corrects transcription before submission.
**Submit Answer**: stores answer; AI feedback is separately priced and disclosed before use.
**Next Question**: advances; save current answer first.
**Previous Question**: returns without deleting answer.
**Pause**: pauses session.
**End Session**: confirmation; saves completed answers and opens summary.
**Review Feedback**: → JS-28.
Never record in the background; user can use text-only mode.

## 10. JS-28 — Interview feedback

- Show rubric categories: relevance, structure, clarity, evidence and completeness.
- Explain that AI feedback is advisory and may be imperfect.
- Quote only relevant snippets from the user's own answer.
- Do not infer protected traits or judge accent, appearance or identity.

Buttons:
**View Suggestion**: expands guidance.
**Try Again**: returns to JS-27 with answer retained.
**Next Question**: advances.
**Save Feedback**: stores report.
**Export**: downloads session report.
**Finish**: returns to JS-26 or application.

## 11. JS-11 / JS-13 / JS-14 — Goals, roadmap and skills gap

### Career Goals (JS-11)
- Goal cards show target, due date, progress and milestones.
- Add Goal opens title, description, target date and category.
- Save creates goal.
- Edit opens form; Save/Cancel.
- Add Milestone appends milestone.
- Complete marks milestone and records timestamp.
- Delete requires confirmation.
- Reminder configures notification.
- Open Goal → JS-13.

### Career Roadmap (JS-13)
- Header identifies goal and target role.
- Timeline of milestones, skills and learning tasks.
- Generate Roadmap uses AI; disclose cost before generation.
- Edit Goal opens goal form.
- Add Task creates manual free task.
- Complete Task updates progress.
- Reminder configures schedule.
- Save and Export preserve roadmap.

### Skills Gap (JS-14)
- Choose Target Role and select current profile/CV.
- Analyse Skills discloses cost and confirms.
- Results distinguish required skills, preferred skills and transferable evidence.
- Add Skill updates profile only after user confirmation.
- Mark Learned asks for evidence/source; no automatic credential claim.
- Save Plan creates roadmap tasks.
- View Roadmap → JS-13.

## 12. JS-15 / JS-16 / JS-18 / JS-29 / JS-30

### Portfolio Builder (JS-15)
- Add Project opens project form: name, description, role, dates, technologies, links, media and visibility.
- Save validates and stores.
- Edit changes selected project.
- Remove requires confirmation.
- Preview opens public-facing preview.
- Publish/Unpublish changes visibility after confirmation.
- Copy Public Link copies only if published.
- Export creates permitted portfolio summary.
- Never invent project results or ownership.

### Professional Profile (JS-16)
- Edit Profile opens editable fields.
- Upload Photo opens image picker and crop preview; Save commits; Remove asks confirmation.
- Add Experience/Education/Skill opens validated form.
- Save persists.
- Preview Public Profile shows only public fields.
- Visibility controls are explicit; private data remains private by default.

### Document Library (JS-18)
- Upload opens file picker and security validation.
- Open/Preview uses safe viewer.
- Download streams authorised file.
- Rename changes metadata only.
- Share creates time-limited, revocable link only when supported and explicitly confirmed.
- Delete requires confirmation and explains associated application references.
- Filter by type/date; search by name.

### Learning Resources (JS-29)
- Search, category filters, Open Resource, Save, Remove, Mark Complete, Add to Roadmap.
- External links show destination and open after user tap.
- No paid resource or third-party course purchase is silently initiated.

### Professional Email Writer (JS-30)
- Fields: purpose, recipient context, tone, key points.
- Generate discloses credit cost and confirms.
- Rewrite discloses cost; copy and save are free.
- Clear asks before discarding unsaved draft.
- User reviews and edits before sending; app does not send email unless a separately authorised email integration exists.

## 13. Acceptance tests

- Manual CV editing, saving, section reordering and existing document export work without credits.
- AI actions show exact debit before execution.
- AI failure does not cause duplicate debit.
- Original CV is preserved when tailoring.
- AI never fabricates user history or credentials.
- File uploads are validated, scanned and access-controlled.
- Chat can stop generation and preserve partial output safely.
- Voice features require explicit permission and visible recording state.
- Conversations and documents are private to their owner.
- Mobile editor remains usable with keyboard open.
- DOCX/PDF output is readable and text-selectable.
