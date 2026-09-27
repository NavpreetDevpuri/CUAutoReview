# Local verification

Verified on 27 September 2026 using the local Docker Compose stack. Regression and service checks use saved replay or isolated fixtures and make no provider calls. Live CLI attempts are reported separately; replay retains the original uncertainty and provenance.

| Check | Evidence | Result |
|---|---|---|
| Backend behavior and provider boundaries | `docker compose -f platform/compose.yaml exec -T app env TMPDIR=/dev/shm PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q -p no:cacheprovider --disable-warnings --basetemp=/dev/shm/pytest-of-final` | 95 passed; 6 warnings; 13.79 seconds; followed by the focused serialization check below |
| Final job-detail serialization | Existing hosted-retry and attempt-cost tests with additional assertions | 2 passed after the final edit; verifies pinned harness/model, all-unknown costs and mixed known/unknown subtotals |
| Runs, hierarchy, analytics and sharing | `python3 platform/scripts/check_runs_analytics.py`, [results](runs-analytics-verification.json) | 7 real-service checks passed; 0 provider calls; temporary fixtures soft-archived |
| Real services and five tasks | `python3 platform/scripts/e2e_local.py`, [machine-readable results](verification.json) | 11 scenario checks passed; PostgreSQL, RabbitMQ/Celery and SeaweedFS's S3-compatible endpoint used; 0 provider calls |
| Pause, duplicate delivery and retry | `python3 platform/scripts/verify_queue.py`, [results](queue-verification.json) | 4 checks passed against the real broker; 3 immutable result revisions retained |
| Object immutability | Real SeaweedFS conditional PUT, GET, identical repeat and conflicting overwrite | Same bytes preserved; conflicting write rejected |
| Frontend | `npm run build` from `platform/web` | Build passed; approximately 1.36 MB initial bundle warning; earlier dependency audit reported 0 vulnerabilities |
| Browser UX | Actual local browser, desktop and 800px-wide layout | Passed the focused checks below; [trajectory capture](screenshots/trajectory-review.png), [task picker](screenshots/task-picker.png) |
| Demo seed and role logins | API checks plus repeated `python3 platform/scripts/seed_demo.py`; [results](demo-verification.json) | 7 checks passed: 5 accounts, 3 populated teams, 5 shared example tasks, access boundaries, unchanged identities/passwords/grants/jobs on repeat; 0 model calls |

## Latest visual-review and clarity checks

- Both native CLI paths attach trusted image bytes. The network-disabled Gemini transport probe verifies the exact model ID for token counting and generation, image content and JSON schema settings.
- All eight Gemini visual reviews and one matched GPT-6 Sol review completed. One unsupported-evidence result retried automatically; a separate storage failure required an explicit recovery. Original OSWorld scores remain unchanged. [Results and all attempt costs](LIVE-RESULTS.md).
- Dataset task rows show saved assessments, problem counts, unique flagged steps and distinct labels. Expanding a task shows each run/model; the task detail retains the matching source revision.
- Framework result, review processing and review assessment have separate labels. Jobs explain failures and display preserved attempt/cost history. Review steps state source screenshot availability, request delivery and model citations separately.
- Final tests include access-controlled summaries, bounded retry/recovery, image-reference validation, source-ID-safe attachments, cost denominators and correct task breadcrumbs for multi-dataset runs.
- Final browser check: the matched task shows 4 runs, 4 saved reviews, 7 problem occurrences and 6 unique flagged steps, with per-model counts. Each overlay distinguishes screenshots sent and frames cited; historical text-only reviews explain why visible source images were not available to that reviewer. The run-review breadcrumb returns to the correct dataset task. [Capture](screenshots/task-review-summary-20260927.png).
- Historical run rows distinguish model-reported assessments from source image availability and delivery metadata. Job details show Gemini CLI / Gemini 3.8 Flash, the JSON-format error, preserved attempt and cost. [Error detail capture](screenshots/review-job-error-20260927.png).

## Responsive UI verification, 27 September 2026

This pass changes the frontend only. `npm run build` passed; the existing large-bundle advisory remains. No provider calls or review jobs ran, and the backend tests above were not rerun for these visual changes.

| Check | Result |
|---|---|
| Phone, 320px and 390px | Task evidence and job details fit without horizontal page overflow; body text is 14px; header actions wrap |
| Mobile step navigation | All steps opens a full-screen picker; selecting step 7 closes it and aligns the screenshot toolbar; Next advances to step 8 |
| Tablet, 768px | Compact evidence layout fits; light mode checked, then original dark mode restored |
| Desktop, 1280px | Aligned problem, relation, review and model fields; screenshot uses remaining panel width; no horizontal page overflow or browser console errors |
| Card navigation | Task and run card bodies open their detail pages; expansion arrows, job links and comparison checkboxes work independently |
| Scope selection | Card body toggles once; checkbox changes only its selection; separate native link does not change selection; task-only scope correctly reports 1 task across 1 dataset |
| Mobile navigation and forms | Drawer fits the viewport and closes after navigation; run composer fills the phone screen; no analysis submitted |
| Model evidence settings | Gemini CLI exposes Gemini 3.8 Flash and screenshot allowance up to 32; CLI forms no longer force text-only requests |

Captures: [desktop flags](screenshots/desktop-aligned-flags-20260927.png), [mobile steps](screenshots/mobile-step-picker-final-20260927.png), [mobile evidence](screenshots/mobile-evidence-20260927.png). [Measurements and interaction record](responsive-ui-verification-20260927.json). These are responsive browser checks, not physical-device or exhaustive accessibility certification.

## ZIP and batch-status regression checks

- `python3 platform/scripts/check_zip_import.py`: five real-service checks passed. Preview saves no tasks; repeated import is unchanged; invalid multi-task archives commit no task revisions; viewer access is rejected; changed image bytes create a revision with distinct, preserved screenshot links. Batch sync carries those images into member-scoped S3 access. [Results](zip-import-verification.json).
- `python3 platform/scripts/check_batch_completion.py`: four checks passed. Five saved tasks completed through RabbitMQ/Celery and the batch settled before any repair request. Reconciliation was a no-op for completed work; unknown outcomes remained awaiting review with no jobs. [Results](batch-completion-verification.json).
- The reported stale batch was explicitly reconciled from running to completed after all six members were confirmed finished. No review restarted. [Repair record](batch-status-repair.json).
- Isolated tests cover corrupt images, archive limits, path traversal, symlinks, duplicate IDs/keys, deep manifests, YAML aliases, bounded diagnostics, trusted screenshot checksums, and pause/cancel/retry fencing. These tests are functional regressions, not an exhaustive security audit.

## Browser checks

- Login, overview, saved batch and trajectory loaded. Dataset, team and immutable preset dialogs rendered with required-field controls; no paid run was started.
- Task search found the weather task using its plain-language label, “Command entered incorrectly.” Task, step, export and evidence links retained the selected member revision.
- Step 15 showed Problem 2 recovery alongside Problem 3's first flag, with separate colored labels and inline definitions. Next/previous kept the step toolbar and evidence aligned; sidebar rows remained readable.
- Navigation and the step sidebar collapsed; the 800px-wide evidence view fit without horizontal page overflow. The temporary viewport override was reset.
- Taxonomy cards distinguished pending, rejected and stale candidates. The rejected candidate's approve/reject controls were disabled. No taxonomy release was published.
- Jobs showed concise replay/usage summaries, bounded attempts, and expandable raw details. Final UI changes passed the Docker frontend build; backend code was unchanged after its passing suite.
- After demo seeding, the browser showed all three populated teams and five accounts with their intended roles. The Manager dropdown option rendered correctly; no existing browser session was signed out. [Capture](screenshots/demo-teams.png).

## Current import, theme and help browser checks

- Created **Example ZIP walkthrough** from the optional ZIP field. The preview showed one task, one screenshot and an unknown-outcome warning; confirmation saved one task without a review run. [Preview](screenshots/zip-import-preview.png).
- The existing-dataset import dialog rejected a ZIP with a missing referenced screenshot, showed `tasks[0].steps[0].screenshot`, and disabled confirmation. [Error](screenshots/zip-import-error.png).
- The example download matched the local template byte for byte. The picker supports keyboard activation.
- Light/dark mode persisted after refresh. Help opened from the collapsed sidebar, rendered Markdown, and preserved `/docs/datasets?section=main-zip-limits` when using its heading index.
- The repaired batch showed **100% Completed**, with six completed, zero active, zero queued and zero failed. The expanded sidebar exposes Help at the bottom; the top bar exposes the appearance switch. [Capture](screenshots/batch-completed.png).
- At the current 919px CSS viewport, document width was also 919px. The 760px task table scrolled within its 565px panel instead of stretching the page. Final UI builds passed with the documented bundle-size warning.

## Earlier text-only live model calls

The matched Gemini 3.8 Flash / GPT-6 Sol pair completed with valid nine-step outputs. The subsequent seven-task Gemini run produced five valid reviews and two malformed-JSON failures. Every distinct task was attempted, including a passing recovery review; no automatic reruns occurred. [Token counts, estimated costs, limitations and retained setup failures](LIVE-RESULTS.md). Live inference is separate from the provider-free regression suite.

## Latest hierarchy and model-control browser checks

- Dataset task view renders current-revision steps with review/model-attributed problem, related-step and recovery flags. Other runs and reviews remain below.
- Next/previous changes the exact source frame and scrolls the evidence into place. Both navigation and step sidebar collapse; document width stays within the 1020px viewport.
- The preset model dropdown selects **Gemini 3.8 Flash** for Gemini CLI and **GPT-6 Sol** for Codex. The new hosted allowance is **$0.10**; no preset or provider call was created by this check. [Capture](screenshots/model-picker-gemini38.png).
- Final UI check confirms both failed rows say **Review failed / No review produced** and multi-dataset breadcrumbs no longer name only the first source.
- The multi-dataset run shows **7 / 7 finished**, **2 failed**, and **Finished with errors**, with all three source datasets and per-dataset task coverage.
- Run-filtered analytics shows 7 unique tasks, 5 reviews, 2 missing completed reviews, and a $0.1101 usage estimate. [Capture](screenshots/live-run-analytics.png).
- A real Gemini/Codex comparison opened both nine-step reviews on the same source revision. The disagreement note saved to both histories, confirmed by the UI. [Capture](screenshots/live-model-comparison.png).
- The note flags an evidence-grounding difference, not a human verdict: Gemini inferred mis-targeting and recovery from repeated actions; Codex kept those effects unverified. Both harnesses received text only.

## What the checks establish

- First signup/admin and subsequent viewer roles; authenticated sessions; cross-origin cookie mutations rejected.
- Team grants allow review/feedback/export. Removing membership immediately blocks task, screenshot and export access. Deactivation invalidates existing sessions.
- Duplicate imports and syncs do not create duplicate revisions or members. Revised source tasks remain separately selectable; fixed batches reject sync. Existing batches retain their preset revision.
- Five real saved trajectories traverse the outbox, RabbitMQ and worker. Four failure analyses and one passing recovery review finish with checksummed YAML in S3 and zero new inference cost.
- Duplicate and obsolete deliveries do not create attempts in the real broker. A message consumed while paused is re-delivered on resume; explicit replay retries append immutable results. Repeated batch start preserves work. Invalid model JSON retains known usage; unknown prices and server opt-out block requests before execution.
- Exact taxonomy approval, stale feedback, rejected candidates, explicit hosted budgets and stale model curation are covered by isolated tests. Live API checks reject stale and rejected candidates. No POC taxonomy was automatically approved during verification.
- Unknown paths and traversal are denied. A review cannot cite an unattached screenshot as inspected evidence.
- New runs pin task revisions from multiple datasets, keep workflow and execution snapshots separate, and create configurable successors after cancellation. Single-task histories retain every completed review.
- Analytics intersects dataset/run/task filters and distinguishes unique tasks from review appearances. Direct run grants expose only authorized members, with no unrelated hidden-dataset tasks. Revocation removes that access.
- Comparison returns both full reviews on the same source revision and records field differences without declaring a winner. Saved-replay comparison tests establish the application flow, not independent model agreement.

## Local fixes found during testing

- Docker disk exhaustion interrupted RabbitMQ writes. Unused build cache was cleared, then the broker restarted with its volume and queues preserved. No database or object-storage volume was removed. Tests used tmpfs while space was recovered.

- Codex runs inherit the allowlisted server region; the final container resolves the required US endpoint without a per-run override.
- Corrected API/UI response shapes, asset MIME handling, missing step explanations, role scope and revision links.
- Closed artifact-access fallback after grant revocation and stale/rejected taxonomy publication paths.
- Disabled Celery's transient control queues for RabbitMQ 4.3; workers consume the review queue only. SQL records provide progress.
- Set SeaweedFS mini volumes explicitly to 64 MB, maximum four, after automatic sizing could not allocate a volume on this Docker disk. This is a small local configuration, not production sizing.

## Limits

- These are functional checks, not model accuracy, load/HA, backup/restore, adversarial security or cloud-provider certification.
- Earlier Gemini 3.8 Flash and GPT-6 Sol runs produced text-only reviews. New visual checks are recorded in LIVE-RESULTS.md. See the platform guide for tokens, estimates and failed setup attempts. These calls do not establish diagnosis accuracy. Claude's requested independent review is blocked by the missing key; Jev's free-credit check returned 403. No review text was invented.
- Test accounts/data are labeled as local acceptance fixtures. The local test administrator credentials are in ignored `platform/.local/test-account.json`; they are not embedded in source or reports.
- Retained POC screenshots remain bundled, read-only evidence. Imported ZIP screenshots and new review YAML use S3. Additional benchmark adapters remain future work.
