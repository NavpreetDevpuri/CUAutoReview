# 5. Platform, teams, datasets and workflows

Current terminology and local UX: [Runs, navigation and comparison](11-runs-navigation-and-comparison.md). The UI calls bulk analysis **Runs**; historical batch storage and appendable behavior remain compatible.
**Implementation status:** Core local workspace workflows now exist in the Compose platform. This specification still describes the design target, including production and runner behavior that is not implemented or verified. See [local platform status](../platform/README.md), [acceptance scenarios](../platform/ACCEPTANCE.md) and [test results](../platform/TEST-RESULTS.md). The [five-service Compose design](08-local-deployment-and-queue.md) uses PostgreSQL work/outbox records, shared RabbitMQ queues and Celery; batches/waves need no separate broker, queue or container.

## Product model and default review routes

```text
Workspace: users ↔ teams → scoped batch grants
  Dataset: source catalog, task revisions, discovered attempts
    Batch: selected members, pinned configuration, team grants
      Sync waves: initial and later additions to the same logical queue
```

- **Task:** instruction/environment definition. **Rollout:** one execution; a task can have K. **Batch:** selected work, fixed or open to additions. **Wave:** one sync's additions. **Analysis run:** review under one resolved configuration.
  - Dataset references are reused without copying raw data. An attempt can belong to several authorized batches; assignments, corrections and selected results remain batch local. Processing retries never create another agent attempt.
- **Both scored routes run by default:** evaluator failure selects `review_kind=failure_analysis`; pass/full score selects `pass_recovery`. Unknown/error grades defer. Full-score mapping follows the pinned evaluator policy.
  - Pin each route's prompt, reviewer recipe, session and budget. Both use one logical trajectory session, shared helpers/YAML and independent recovery fields.
  - Pass recovery scans every compact step for mistakes and supported mistake-to-correction links. Expand evidence/escalate unresolved cases within that route. Passing alone proves no recovery; retain the pass grade and use `outcome_contribution=not_applicable`. Failure contribution remains `contributing/noncontributing/uncertain`.
  - Existing batches need an explicit successor run with scope/budget to adopt this policy. Historical passes do not become reviewed automatically.

## People and permissions

| Role | Allowed scope |
|---|---|
| Workspace admin | Users/teams/connectors; datasets/batches; delegation, grants, sync/configuration/pause/reanalysis; review and viewing |
| Batch manager | Dataset/batch creation and delegation within delegated dataset scope; grants/append/sync/configure/pause/reanalysis and viewing for assigned batches; annotation only with a review grant |
| Reviewer | Annotate/adjudicate and view within assigned scope |
| Viewer | Assigned progress, trajectories, scores and results only |

- Grant roles directly or through teams, differently per batch. Display every effective access path. Removing one grant may leave inherited access; deactivation revokes all workspace access. Taxonomy publication separately requires curator permission.
- Batch grants expose neither connector credentials nor the whole dataset. Authorize search, counts, exports and evidence; recheck requests and invalidate permission-sensitive caches after membership changes. The evidence proxy supports immediate revocation, but cannot recall downloaded files.
- Background work uses a scoped workspace service identity, so submitter removal does not orphan work. Discovery/retrieval/proposal citations obey visibility rules; shared taxonomy examples require approved sanitization. Reused machine output never shares another batch's access or review changes.

## Sync and optional execution

1. **Discover:** select source/adapter; preview tasks, attempts, artifacts and scoring coverage. Commit cursor and discovered records together.
2. **Select:** explicit members or a saved inclusion rule; declare `fixed` or `appendable`. Dataset additions never silently join fixed batches.
3. **Preview:** new task IDs, further attempts, revised/unchanged inputs and tombstones. Never substitute a revised task for a selected revision.
4. **Append atomically:** immutable wave membership plus durable work intents. Repeated `(batch, source identity, revision, run configuration)` admissions are no-ops.
5. **Process:** pinned settings, unchanged existing progress/results. Tombstone removals; explicitly admit revisions while preserving prior members/results.

- Manual sync and continuous discovery share this path. Upload registration admits promptly; periodic listing/reconciliation finds external arrivals. Notifications are optional acceleration.
- **Import-only first:** scored trajectories enter the appropriate review route; task-only inputs stay `awaiting_rollout`. Sync does not execute tasks.
- **Execution connector later:** a pinned runner/evaluator launches missing attempts, collects artifacts/grades, then routes both failed and passed results. Its connector owns VM/environment provisioning, not the reviewer worker.
  - Example: a 20-task batch gains 3 tasks and 2 further attempts. Preview them separately; execute only the 3 unexecuted tasks' K attempts, reuse completed attempts, or leave task-only members waiting in import mode. Review each scored attempt once per selected configuration/route.
  - Reserve `(execution_set_id, task_revision, execution_preset_revision, seed/replicate)` uniquely. With 2 of K=3 attempts, launch only the missing slot. On dispatch timeout reconcile that same key, never blindly relaunch. Deliberate repeats get a new execution-set identity.

## Typed plugins and readable artifacts

Use a small approved/versioned registry in isolated workers, not a general arbitrary-code workflow builder.

| Extension | Required contract |
|---|---|
| Source | Cursor discovery, stable IDs/revisions, fetch artifact manifest, normalized steps/actions/observations/screenshots/grades; schema/platform/modalities/unsupported fields |
| Runner | External sandbox, task/environment/agent revisions, K/seeds/limits, cancellation, artifacts and attempt identity |
| Evaluator | Imported checks/scores or approved checker over retained final state; exact rubric/code, available per-check results, raw score, distinct outcome/error |
| Review workflow | Route-specific prompt/recipe, versioned helpers, one sequential trajectory session, step annotations, episode/recovery reconciliation/validation; separate assignment/curation |
| Model | Text/image/structured-output capabilities, versions, rate/cost accounting, provider errors; secret references |
| Execution backend | Per-stage `model_api`/`agent_harness`; submit/stream/cancel/result, authentication checks, capability and permission limits, provider/harness versions, usage/errors/raw events; LiteLLM or ACP/acpx/native adapter |

- Emit [canonical contracts](02-data-and-contracts.md), retain lossless source references, report conversion losses, and namespace source-specific extensions. New formats need an adapter and conformance fixtures; unknown schemas fail visibly.
- Author evidence indexes/presets/taxonomy and validated reviews in YAML; preserve native JSON/JSONL/images and JSON transport. Agent/UI share proposed versioned compact/render helpers. Omission markers expand to authorized originals; compact views never replace evidence.
- Reject incompatible modalities or missing evaluator prerequisites before dispatch. Missing-evidence results are valid; screenshots alone cannot fabricate a grade. Raw APIs, Codex, Gemini CLI and Claude Code are adapter targets, not universally suitable backends. Text-only models cannot inspect pixels; scored OSWorld execution needs a compatible desktop runner/evaluator.
- API keys/workload credentials are the unattended default. Native login is optional and eligibility-specific; containers inherit no host login. Authentication does not grant evidence/tool/billing access. See [backend/auth contracts](10-harnesses-and-authentication.md).

## Presets, versions and rescoring

- **Execution/evaluation preset:** harness/task-suite revision, agent model, environment, K/limits, evaluator code/rubric.
- **Analysis preset:** source/normalizer/helper/render versions, YAML schema, route/prompt/reviewer recipe, session/checkpoint policy, per-stage backend/model, harness/adapter/auth mode/helper allowlist, parameters, per-call/trajectory/workspace budgets, assignment recipe and taxonomy release.
  - Author YAML; resolve defaults/overrides to an immutable typed snapshot/hash. Store secret references, actual provider metadata and pinned capabilities. Unavailable pinned models block work, never silently switch.
  - Examples: `failed-rollout-triage`, `pass-recovery-scan`, `deep-visual-review`, `taxonomy-reclassification`.
- **Separate curation preset:** proposal/feedback model or harness, retrieval scope, draft schema/budget and mandatory approval. It consumes validated, authorized evidence/feedback asynchronously; never changes a batch's pinned taxonomy. Analysis and assignment may share models, but separate jobs/sessions keep reclassification cheap and prevent feedback rewriting diagnosis.
- New arrivals retain the run snapshot. Preset edits affect deliberately selected future runs; active configuration changes create a successor with visible boundary, explicit new-only/selected historical scope and budget. More batches cannot bypass workspace quotas/fairness. Failure/pass pools may isolate capacity, but neither route may starve or silently lose coverage.
- **Shared taxonomy proposals:** parallel trajectory reviewers see the approved taxonomy and latest shared proposal pool, then append immutable new/edited-label revisions. A separate post-batch consolidation agent compares near-duplicates and proposes canonical mappings/aliases with rationale. Preserve raw reviews and proposal history; conflicts/stale edits require explicit resolution or rebase. A versioned candidate still needs human approval of its exact draft/base/evidence before any production release.
- **Focused local POC:** one batch of five actual trajectories, a read-only viewer and a prominent red POC banner. It may show provisional labels and a candidate taxonomy; it does not implement production taxonomy approval/publication. Scope and status: [Local POC](../poc/README.md).
- [`jev-fast-triage`](07-jev-fast-analysis.md) optionally routes inspection or matches existing modes using text. It replaces neither visual understanding nor the evaluator; its predeclared baseline fallback records the actual route.
- **Imported scores:** unknown/different evaluator versions block strict batches as `incompatible_evaluation`. Rescore only with required final state, or choose another run/cohort. `as-recorded exploration` can review historical failed/passed attempts with unknown provenance, warnings and separate cohorts; it cannot claim evaluator comparability. Never relabel imported scores; runners actually execute pinned evaluators.
- **Rubric versus taxonomy:** a rubric checks success, such as a required setting/saved artifact; a mode explains a mechanism, such as completion claimed without checking it. A failed grade identifies no cause; a passed grade proves no error-free path.
- Results reference exact known task/environment/agent/evaluator/input/workflow/model/taxonomy revisions; unknown provenance stays unknown. Strict runs require pins; multiple results can share versions.
  - Human-readable `major.minor.patch` plus immutable IDs/hashes: taxonomy patch changes wording only, minor adds concepts without changing definitions, major restructures/merges/splits. Even additions can change assignments, so compare exact releases. Evaluator numbers never replace checker/config hashes.
  - Rescoring appends an evaluation record and queues the correct route with new result revisions. Preserve original grades/annotations/reports; explicitly select successors. Never overwrite history or silently reinterpret an old pass as reviewed.

## UI, progress and controls

| Screen | Required view |
|---|---|
| Workspace/teams | Invite/deactivate, team membership, effective batch grants |
| Dataset | Source, task/attempt/scoring counts, last sync, preview and batches |
| Batch | Members/waves, pinned routes/presets, teams, start/pause/resume, arrivals, cost/status |
| Trajectory | Task/grade; synchronized compact steps/screenshots; declared/inferred/unknown intent, action/UI/effect/assessment; coverage, episode/recovery links, separate contribution/mode; expand originals/export YAML |
| Review/taxonomy | Cited assignments; optional family → mechanism → subtype; definition diff/examples/conflicts/impact; feedback/redraft/approve/reject/publish; stale approval/version badges |

- In the trajectory viewer, let the document header scroll away. Provide one minimizable sidebar for task and step selection. Show screenshots at full available content width, followed by all explanations; keep each selected screenshot at the same vertical position during step navigation.
- Use compact, readable typography (14px platform body text), restrained headings and self-explanatory category names. Keep definitions always visible inline. Show consistent category colors and IDs, with a “Recorded label” disclosure for the original name and ID. See the [platform feedback](../platform/UX-FEEDBACK.md) and [preserved POC feedback](../poc/VIEWER-FEEDBACK.md).
- When a step links to multiple problems, show a separate numbered problem group for each link and assign its step an independent role. Reuse the same task-local number in all onset, related and recovery groups; count linked problems rather than creating new mistakes for every marker. For multi-problem steps, show a compact summary with a jump to each problem's first anchor and episode card.
- Version 2 stores `problem_number` and `first_observed_step_id` on every episode. Numbers are unique within the task and follow first-observed source-trace order. The `episode_id` and `onset_step_ids` remain intact. Show “First observed at step X,” “First observed here,” and “Also observed here” from explicit version 2 fields. For saved legacy records with no schema version, derive “First flagged at step X” from the earliest explicit `onset_step_ids` in source order; show “First flagged here” and “Also flagged here” only at those explicit links. Related and recovery groups display the same first-anchor link. Do not infer an anchor when IDs are absent.
- Keep step role, failure category and recovery status separate. Link only recorded onset/recovery steps and `step.episode_refs`; never infer intermediate mistake steps. Missing evidence stays `insufficient_evidence` or `inconclusive`. Resolve presentation text from the pinned taxonomy while preserving raw review outputs and historical IDs.
- **POC acceptance checks:** the header leaves the viewport on normal page scroll; task and step selection share one collapsible sidebar; screenshots use the full content width with explanations below; definitions remain visible inline; category chips use consistent colors and IDs; problem numbers and first anchors persist across onset/related/recovery groups; counts reflect linked problems; each marker and summary jumps only to a recorded step; **Screen ↑** returns to the selected screenshot; sparse evidence is visibly uncertain; next/previous navigation keeps screenshot alignment stable.

- **Outcome is not processing status:** agent failed or passed while review succeeded. New passes use `pass_recovery`, not `skipped_by_failure_policy`; that legacy status stays historical until explicit reprocessing. Unknown/error grades show `awaiting_evaluation`/`evaluation_error`.
- Separate analysis-ready, assignment-pending/unclassified and taxonomy-review states; delays never hide valid explanations. Zero episodes set `classification_status=not_applicable`, reason `no_episodes`, with no classifier job/assignment. Show a complete no-issue result only when evidence/coverage support it; partial/inconclusive/abstained reviews retain their status. Show intent/action/receipt/effect uncertainty and citations. Reuse standard tables/forms/auth; specialize evidence/diff views. [UI reuse](09-open-source-reuse.md).
- Recovery: `not_assessed/none_observed/partial/recovered/unknown`, with original episode, correction steps/evidence and observation boundary. It is not another label. Filter recovered mistakes even in failed tasks. Contribution is separate, including `not_applicable` for passes. A step can link several episodes.
- Count every normalized step as `reviewed/not_reviewed/insufficient_evidence` with source references; partial cannot look complete. Per-wave item states are disjoint: awaiting rollout/evaluation, incompatible evaluation, explicitly skipped, queued, running, retrying, succeeded, quarantined, dead-letter, cancelled. Derive `terminal_total`; success means processing finished, not agent success/full coverage.
  - Separate task/attempt/job counts and review backlog. Open streams show “caught up as of watermark,” arrivals/throughput/backlog age/stage progress, never permanent 100%. Show ETA's estimation basis.
- Pause dispatch while discovery continues; in-flight work normally finishes. Resume backlog. Cancel pending work and cooperatively stop calls, retaining completed history. Retry resumes validated checkpoints, never the evaluated task agent; a new rollout is a separate request.
- Cancellation removes one batch's demand; shared work continues for other authorized consumers. Charge workspace compute once; show batch marginal cost versus reuse estimates. Review changes cross batches only through explicit authorized selection, never a global mutable result pointer.
