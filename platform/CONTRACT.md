# Local platform implementation contract

The original POC remains intact. Build a working local workspace with the documented core workflows, using FastAPI, SQLAlchemy, PostgreSQL, RabbitMQ/Celery, S3-compatible storage, React-admin and MUI. Production hardening and unsupported integrations must be named honestly.

## API conventions

- API prefix `/api`; JSON; cookie session authentication, same-origin in built deployment. Vite dev proxies `/api` to `127.0.0.1:8000`.
- List responses `{items: [...], total: N}`. Errors use FastAPI `detail`.
- IDs strings. Dates ISO UTC. Permission enforcement on the server; UI reflects effective roles.
- Signup `{name,email,password}`; password >=8. First account local workspace admin; later accounts viewer until granted access. Login `{email,password}`. Endpoints `/auth/signup`, `/auth/login`, `/auth/logout`, `/auth/me`.
- GET `/overview`: counts, recent batches, activity, provider/queue mode.
- GET/POST `/teams`; PATCH/DELETE `/teams/{id}`; POST `/teams/{id}/members` `{user_id}`; DELETE `/teams/{id}/members/{user_id}`; GET `/users`; PATCH `/users/{id}` `{active,role}` (admin).
- GET/POST `/datasets` `{name,description,source_adapter}`; GET `/datasets/{id}` with tasks and batches. POST `/datasets/{id}/import` accepts `{format: "cuautoreview", tasks:[...]}` normalized saved task records. POST `/imports/zip/validate` accepts raw `application/zip` bytes and returns a task/screenshot preview plus warnings; it does not persist records. POST `/datasets/{id}/import-zip` accepts the same ZIP and revalidates before importing task revisions and screenshot assets. ZIPs contain exactly one root `dataset.json` or `dataset.yaml` manifest and may reference PNG/JPEG/WebP assets under `assets/`. Main bounds: 32 MB archive, 128 MB expanded, 1,000 entries, 10 MB and 16 million decoded pixels per image. Technical manifest bounds: 5,000 tasks, 2,000 steps per task, 50,000 total steps, 512 KB per task record and 100 nesting levels. Missing screenshots are warnings unless explicitly referenced; unsafe paths and unsupported files are errors. No arbitrary paths or URL fetch.
- GET/POST `/batches` `{dataset_id,name,description,mode:"fixed"|"appendable",preset_id,task_ids?,team_ids?}`. GET `/batches/{id}` returns detail, progress, waves, grants. GET `/batches/{id}/tasks`; GET `/batches/{id}/tasks/{task_id}` returns source task plus selected review. POST `/batches/{id}/sync` admits new task revisions idempotently as new wave. POST `/batches/{id}/start`, `/pause`, `/resume`, `/cancel`. Explicit run required for hosted inference; default replay only.
- POST `/batches/{id}/grants` `{team_id?,user_id?,role:"manager"|"reviewer"|"viewer"}`; DELETE `/batches/{id}/grants/{grant_id}`.
- GET/POST `/presets`; POST creates immutable new preset revision from `{name,backend,model,reasoning,budget_usd,configuration}`. GET `/providers` returns supported/configured/capabilities, never keys. GET `/providers/models?backend=...` returns `{backend,models,source,fetched_at,status,note}` from the secret-free provider metadata snapshot; new deployments return `status:"unknown"` and an empty model list until an authorized sync. Admin-only POST `/providers/models/sync` stores model IDs/capability metadata supplied by the credential-owning runner and never calls providers itself. Default backend `saved_replay` is marked as replay of retained evidence, not new inference. API backend uses LiteLLM with explicit credentials/limits. CLI backends must report available/unavailable truthfully.
- GET `/taxonomy` returns `{releases,proposals,candidates,labels}`. POST `/taxonomy/proposals` `{name,description,kind,base_release_id?,label_id?,evidence_refs?}`. POST `/taxonomy/proposals/{id}/feedback` `{text}`. POST `/taxonomy/consolidate` creates versioned candidate. POST `/taxonomy/candidates/{id}/approve` `{expected_hash,version}` publishes exact immutable candidate; `/reject` `{reason}`. Updates/feedback append revisions; approval stale on changed base/draft.
- GET `/jobs`; POST `/jobs/{id}/retry`; GET `/activity`.
- POST `/batches/{id}/tasks/{task_id}/feedback` `{text,step_id?,episode_id?}`. GET same `/feedback`. GET same `/export?format=yaml|json` authorized export.
- GET `/artifacts/{task_id}/{relative_path:path}` is authorized and resolves only recorded evidence in S3 or controlled bundled files. `member_id` pins batch evidence; `revision_id` pins dataset evidence. Backend adds same-origin `screenshot_url` fields to steps and a `raw_url` for controlled exports. Unknown referenced files show missing evidence, never inferred paths.
- Seed retained latest five POC tasks/reviews into an initial dataset/batch and draft taxonomy, only for first local admin, preserving provenance and making no model calls.

## Core local behavior

- Dataset revisions and batch membership/waves immutable. Sync idempotent. Fixed batches do not silently append.
- Original evaluator outcome separate from processing status. Failed -> failure analysis; passed -> recovery scan; unknown/error -> waiting.
- Queue authoritative SQL records plus outbox, RabbitMQ delivery, Celery late ACK, generation/fence ownership, and at most four application attempts total (initial attempt plus up to three retries for retryable failures). Pause prevents new dispatch; completed results are retained. No Celery backend/Redis needed.
- Store raw/validated YAML through S3 adapter; local file adapter allowed explicitly for developer fallback, not claimed as S3 test.
- New results append revisions; taxonomy release pinned on batch config, human approval creates release. Shared proposals and consolidation remain separate.
- No automatic run creation or default model fallbacks. Budget/error/usage visible. A configured hosted task allowance applies to each attempt; the planned total includes the maximum retry count and can be up to four times the per-attempt amount. This is an estimate, not a hard provider cap.
- Visual evidence provenance distinguishes source frames (present in the authorized task revision), supplied frames (attached to a provider request), omitted frames, and cited frames (referenced by the review output). A citation is a model claim, not independent proof of visual inspection. Gemini CLI 0.61.0 image transport was checked against a loopback fake provider with outbound networking disabled; no vision-quality conclusion follows from that transport check.

## UX

- Distinct platform shell, compact readable 14px body text, restrained headings, collapsible left nav, clear status cards, deliberate empty/loading/error states. Mobile layouts preserve touch targets and full-width evidence.
- Pages: Overview, Datasets, Batches, Teams, Presets, Taxonomy, Activity, focused trajectory workspace and in-app Markdown guides at `/docs/:slug`. Light/dark appearance is persisted in browser local storage and can be changed on sign-in or from the workspace top bar.
- Reuse React-admin MIT core and MUI; specialize trajectory viewer. Avoid a giant CRUD form as primary UX.
- Task selector searchable card dialog: evaluator outcomes, recorded problems, label counts, flagged/recovery steps and quick links. Step sidebar includes numbered problem badges/first anchor. Full-width screenshot and details below. No hover-only meanings, no forced whole-page scroll trapping. Stable next/previous alignment.
- Taxonomy review shows exact candidate, definitions, feedback, merge rationale and explicit approve/reject. Use self-explanatory labels; no em dashes in copy/docs.
- Local signup includes name/email/password. Show saved-replay identity clearly so fixture tests are not presented as new model reviews.

## Verified local boundaries

- The implementation uses one bounded review request per trajectory. Bounded ZIP screenshot uploads are implemented. Helper-tool loops, additional source adapters, ACP execution, source discovery and production hardening remain the broader design target.
- The local UI's Task record contains one rollout; revisions correct that same recorded attempt. Independent attempts must use separate record IDs. Grouping K attempts under a shared task definition remains a design target; a new review run reanalyzes evidence, not a new computer-use execution.
- New batches queue their own review even when source data includes a retained diagnosis. Saved replay retains original provenance; it is not a new diagnosis.
- A worker snapshots the batch-pinned release plus current shared drafts when it claims a job. The exact label snapshot accompanies its result; a later retry may see newer drafts without changing earlier results.
- Member IDs disambiguate source revisions in batch views, feedback, exports and artifact links. Dataset screenshot links pin the source revision separately. Imported screenshot URLs cannot bypass the recorded artifact endpoint.
- Resume re-arms queued delivery that may have been consumed during a pause. Old generations and duplicate deliveries cannot publish a second result.
- Taxonomy model curation requires `{preset_revision_id, confirm_budget, expected_budget_usd}`. Empty input assembles a no-cost candidate, preserving unresolved merge suggestions for review. No automatic publication or automatic curation call.

## Completion reconciliation

- Final workers flush member/job changes before locking the batch and checking completion. Queued/running/retrying jobs keep it active; unknown outcomes stay awaiting review. Pause and cancellation remain authoritative.
- Managers may POST `/batches/{id}/reconcile` to repair an old stored running status when persisted records safely derive completed or awaiting review. The endpoint is audited, starts no jobs, and otherwise returns `reconciled: false`. GET requests do not mutate status.

## Run API and hierarchy

- `/runs` is the primary UI/API term; existing `/batches` records and endpoints remain compatible.
- POST `/runs`: `name`, either `dataset_ids` or `task_definition_ids`, `workflow_revision_id`, `execution` (`backend`, `model`, `reasoning`, `budget_usd`, `configuration`), optional `team_ids` and `user_ids`. Pins a fixed multi-source selection.
- GET `/runs/{id}` includes source dataset counts, immutable workflow/execution snapshots and separate source-outcome, processing-status, saved/missing-review, invocation-attempt and retry counts. Its planned allowance sums configured per-attempt allowances through the maximum attempt count. `/configure` is draft-only; `/start` requires explicit live budget confirmation. `/rerun` creates a successor. `/pause`, `/resume`, `/cancel`, `/archive`, `/restore` preserve existing evidence.
- Run aliases retain task `/feedback`, `/export`, grants and `/reconcile`. A direct run grant authorizes only the selected source evidence.
- GET `/workflows` returns versioned stage prompts separately from execution presets. The local build supplies `trajectory_review@1`; custom workflow authoring is not yet implemented.
- GET `/datasets/{dataset}/tasks/{definition}` returns source revisions and all accessible run/review history. Export supports JSON/YAML. Task archive/restore is reversible.
- GET `/directory?q=` searches active names/emails and teams. GET/PUT `/datasets/{id}/shares` manages direct/team roles and optional `workspace_shared` read access.
- GET `/catalog` supplies permission-scoped selection cards. POST `/analytics/query` accepts dataset/run/task-definition ID arrays with OR within groups and AND across groups. Empty intersections return zero matched rows.
- Analytics distinguishes unique matched tasks, selected scope, run appearances, review counts, episode frequencies, source-frame gaps, unavailable artifacts and known/unknown cost estimates.
- POST `/analytics/compare` accepts result IDs from the same task definition and source revision. Returns both full reviews, harness/model identity and field differences; it does not declare a winner.
- Archive filters are explicit. Results and source revisions remain immutable; archived fixture data is hidden from normal demo lists.
