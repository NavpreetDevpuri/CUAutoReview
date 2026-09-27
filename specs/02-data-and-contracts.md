# 2. Data and contracts

Local implementation refinement: [Runs, navigation and comparison](11-runs-navigation-and-comparison.md). New runs pin a multi-dataset task selection, a workflow revision and a separate execution snapshot; existing batch identifiers stay valid.
## Identify inputs and choose a review route

- `task_id + task_revision` identifies a definition; `rollout_id` identifies an attempt. Retain agent build, environment revision, available seed, domain and evaluator version. Identical bytes never merge independent attempts.
- A ready manifest contains `schema_version`, rollout/task/agent/environment references, evaluator result/reference, creation time and artifacts `{artifact_id, kind, bucket, key, version_id, sha256, bytes, required}`. Validate required trajectory/outcome objects; briefly retry missing ones, then quarantine. Missing optional screenshots produce coverage warnings. Preserve original manifests and JSON/JSONL; adapters emit normalized YAML references.
- Hash the canonical manifest as `source_revision`. Corrections name `supersedes_source_revision`; advance the current pointer only from that parent. Reconcile missing predecessors and resolve branches explicitly, never by arrival order. Record historical imports' initial revision. Use S3 versions or checksum-verified controlled immutable keys; ETag is not a content hash.
- Task-only members remain `awaiting_rollout`. The **selected evaluation record**, interpreted by its pinned evaluator, determines review kind; no assumed numeric threshold:

| Outcome | Default review |
|---|---|
| `failed` | `failure_analysis` |
| `passed`, including full score | `pass_recovery` |
| `unknown` / `error` | Defer pending resolution |

Both routes are enabled, with separate prompt/agent recipes, logical sessions and budgets. One trajectory runs only its selected route; continuation/escalation does not start the other route or one agent per step. Rescoring appends an evaluation record and requires an explicit route/review decision. Preserve the original grade. Existing batches retain pinned policies; successor runs explicitly admit historical passes, with no automatic retroactive review.

## YAML artifacts and one typed identity

Use versioned YAML for human/model-readable inputs, evidence indexes, presets, taxonomy and review output. Preserve source JSON, JSONL, logs and images; references avoid a second authoritative trajectory. API/provider JSON and PostgreSQL JSONB remain valid representations of the same typed contract.

| Artifact | Required content |
|---|---|
| Manifest/index | Source revision, immutable locators/checksums, ordered step IDs, event/row pointers, screenshot timing, missing evidence |
| Analysis preset | Preset/recipe revisions, input/output schemas, review-kind route mapping, prompt/agent/model, chunk/context/call limits, selection/coverage, spend/retry budgets |
| Taxonomy | Independent schema version and release, mode IDs, definitions/boundaries/examples, parent/lineage, approved proposal |
| Trajectory review | Analysis/input/preset revisions, selected evaluation and `review_kind`, prompt/agent recipe, index reference, coverage, every step review, episodes, provenance |

- `schema_version` versions structure; `taxonomy_release` versions definitions and can be null before classification. Every artifact has a type, schema and immutable reference. Pinning taxonomy never makes review depend on assignment readiness.
- Parse restricted **YAML 1.2**: string-keyed mappings, sequences, JSON-compatible scalars. Reject tags, duplicate keys, anchors/aliases, merge keys and multiple documents. Bound bytes, depth, collection/scalar sizes and parse time; never construct arbitrary objects. Quote identifiers/version strings, check types and treat model YAML as untrusted.
- Validate once, then hash canonical JSON with fixed number/time rules and semantic sequence order. Comments/key order/formatting do not affect logical identity. Also retain exact artifact-byte SHA-256. YAML, API JSON and rows must not become independently editable copies. Native model structured output can be validated and serialized to YAML.

## Logical records

Use foreign keys and `workspace_id` in shared-deployment keys/access checks. Bulky payloads belong in S3-compatible storage. JSONB can hold arrays; task/model/domain/version/outcome/time filters are typed/indexed. Index mode/release assignments and analysis episodes. Embeddings carry model/version/scope; incompatible vector spaces cannot mix. pgvector supplies candidates, followed by definition/evidence checks.

| Records | Fields and purpose |
|---|---|
| `workspace`, `membership`, `team`, `team_member`, `batch_grant` | User status, direct/team roles, effective access, audit |
| `dataset`, `source_connection`, `discovery_checkpoint` | Source/adapter revision, credential reference, catalog, committed cursor/watermark |
| `batch`, `batch_run`, `sync_wave`, `batch_member` | Fixed/appendable rule, immutable resolved preset, admitted task/input revisions, wave/progress |
| `execution_set`, `execution_slot`, `batch_result_selection` | Idempotent runner identities; batch-local analysis/classification selection and review scope |
| `plugin_revision`, `preset_revision` | Typed source/runner/evaluator/workflow/model contracts; immutable reusable configuration |
| `task_revision` | Task ID/revision, objective, domain, environment constraints |
| `rollout`, `input_revision`, `evidence_index` | Attempt/task/agent/environment, recorded outcome/evaluator, manifest/index references and logical hashes, step IDs/completeness |
| `evaluation_record` | Original/successor grade, exact evaluator/rubric, raw score/checks, passed/failed/unknown/error, provenance |
| `recipe`, `analysis_profile` | Immutable review-kind route/prompt/agent configuration, classifier recipe, taxonomy release |
| `job`, `job_attempt`, `outbox_event` | Authoritative work/audit; unique key/stage/state, delivery generation, attempt, lease/fence, cost/error, atomic dispatch intent, available-at/confirmed-send state |
| `backend_invocation`, `credential_binding` | Stage/backend/harness/adapter/provider/model versions, session/exit, capability/permission policy, invocation/usage/raw-event references; credential owner/auth mode/secret reference only |
| `inference_reservation` | Invocation/claim, concurrency/request/token/spend reservations, deadline, settled usage, remaining trajectory budget; separate from job lease |
| `analysis_run`, `analysis_revision` | Unique input/evaluation/route/recipe run; immutable YAML revisions, step coverage, evaluator agreement, abstention, artifact/response, cost |
| `step_review`, `evidence` | Revision/step, coverage, intent/action/UI/effect/assessment and episode links; artifact/source-row pointers; exact source version, JSON/frame/crop/time coordinates, observation/alignment certainty |
| `episode`, `episode_link`, `alignment_check`, `episode_evidence` | Analysis revision and episode/evidence IDs; symptoms/onset/terminal spans, expected/actual state, mechanism/alternatives, origin/impact; recovery/contribution; precursor/consequence links; task/intent/action/effect/grade checks with evidence and consistent/conflicting/unknown status; supporting/contradicting claim links |
| `taxonomy_release`, `mode_revision`, `mode_lineage`, `taxonomy_parent` | Immutable definitions/concept IDs, one-parent acyclic release edges, inclusion/exclusion examples, merge/split/rename/deprecation; semantic successors get new IDs |
| `classification_run`, `classification_revision`, `episode_classification`, `assignment` | Exact analysis/taxonomy/classifier, immutable revision, assigned/unclassified/ambiguous/insufficient_evidence, candidate definitions/fit evidence/boundary conflicts, chosen mode revision, role, calibrated confidence, decision source |
| `proposal`, `proposal_revision`, `feedback`, `review_event` | Shared pool of append-only proposal revisions; change/base/diff/hash, evidence/review preconditions, supporting/conflicting examples, overlap/impact/cost; feedback target/revision/comment/evidence/resolution; author/curator decisions/time |
| `consolidation_run`, `taxonomy_candidate`, `candidate_mapping` | Post-batch review cutoff and raw review/proposal references; versioned candidate/base/hash; near-duplicate comparisons, proposed canonical label/mapping/alias and rationale; conflicts and stale bases |
| `report_snapshot`, `report_member` | Cohort/filter/cutoff/profile/review kind, exact selected input/evaluation/analysis/classification revisions, coverage/exclusions |

Normalized events retain source event ID/sequence/time, actor/type, optional visible intent/message, requested action/arguments, separate execution/response/effect, screenshot timing and pointers. Missing intent/receipts stay missing. Harness summaries/exit codes are not grades; reviewer events belong to its invocation, not the evaluated agent. Record conversion losses/partial streams. [Backend contract](10-harnesses-and-authentication.md).

## Step reviews, checkpoints and episodes

One logical reviewer emits a compact record for **every normalized step**, including ordinary/recovery steps. Both routes use the same helpers/schema; a classifier later adds labels without rewriting observations.

Each `step_review` contains:

- `step_id`, `review_status` (`reviewed`, `not_reviewed`, `insufficient_evidence`), gap reason and evidence actually inspected. Text review does not imply image inspection.
- `intent`: kind (`declared`, `inferred`, `unknown`), text/evidence. Declared means a visible statement; inference is tentative; unsupported intent stays unknown. No hidden-reasoning claim.
- `action`, `observed_ui`, `effect`, `assessment`: requested action, visible state, observed change and task/intent alignment. Acknowledgment alone proves no effect; use null/unknown for unsupported detail.
- `evidence_refs`, `episode_refs` with roles such as onset/recovery. Resolve through the pinned index to immutable objects and exact source/normalized-row pointers; indexed rows also point into the output artifact.

The local platform also records image delivery separately from review citations: **source** frame IDs mark task steps that reference screenshots in the authorized revision, even if an image is later unavailable; **supplied** IDs identify frames whose bytes were attached to a model request; **omitted** IDs identify source references not sent; **cited** IDs identify supplied frames referenced in the returned review. Supplied does not prove a model inspected an image, and cited is a model claim, not independent validation. Historical CLI reviews must retain their text-only provenance even after image transport is enabled.

Validation requires exactly one record per expected step, valid revision-matched references, ordered spans and reconciled overlapping/conflicting chunks. Enforce selected-outcome/review-kind/contribution consistency. `coverage_summary` counts across all three statuses sum to expected steps and state whether review is partial.

Checkpoints are partial drafts, not published analyses or successful completion. Persist input/evaluation/review-kind/recipe/preset, cursor, validated annotations/evidence, episode state and bounded continuation summary. Log new provider-session IDs after restart without claiming hidden context survived. Missing/truncated chunks remain incomplete/retryable. An explicit budget/policy stop may finalize partial output with reasoned `not_reviewed` placeholders for every gap and complete ID reconciliation. Reports disclose/exclude gaps under their coverage policy. Evidence-based abstention differs from truncation or processing failure.

An analysis may have zero, one or many episodes; an episode can remain unclassified. Empty episodes with `no_issue_observed` describe reviewed evidence only and never certify error-free behavior; no inspected evidence requires abstention. Pass review inspects all compact steps, seeks evidence-backed error/correction pairs, expands frames/long gaps and can escalate within its route. Passing does not prove recovery: preserve the pass while recording unresolved mistakes or evaluator concerns.

Zero episodes set **`classification_status: not_applicable`**, reason `no_episodes`: no classifier job, assignment or fabricated classification revision. Reports retain the exact analysis revision and explicit null classification reason. This stage status is separate from episode assignment and outcome-contribution enums. Empty episodes caused by missing evidence retain partial/inconclusive or abstained review status, never become no-issue results merely through this bypass.

Each episode stores onset span, mechanism and impact independently from taxonomy:

| Field | Contract |
|---|---|
| `recovery.status` | not_assessed / none_observed / partial / recovered / unknown |
| Recovery detail | `step_ids`, supporting/contradicting `evidence_refs`, `assessed_through_step_id`, restored `scope` |
| `outcome_contribution` | Failed records: contributing / noncontributing / uncertain, with rationale/evidence. Passed records: **not_applicable**; other impacts remain separate. |

`none_observed` means no recovery in assessed evidence, not impossibility; `unknown` means insufficient evidence; `not_assessed` means unchecked. A later success is not automatically recovery. Partial fixes stay partial. Recovery is episode/scope specific; a recovered mistake can still contribute to a failed outcome through irreversible effects or earlier cost. Unclear failed-outcome impact stays uncertain. Never combine recovery with contribution as `recovered_or_unrelated`.

## POC problem numbers and first-observed anchors

The local viewer's version 2 agent output requires `problem_number` and `first_observed_step_id` on each episode. `problem_number` runs from 1 through N in first-observed source order, with episode-array order breaking ties. `first_observed_step_id` must equal the earliest explicit onset ID in source order. Reuse that number wherever the episode appears; it is not a substitute for `episode_id`. Keep `episode_id` and `onset_step_ids` unchanged. `first_observed_step_id` must refer to an explicit source step and records when the reviewer first observed/flagged the problem, not a new onset definition.

Onset/recovery steps must reference their episode in `episode_refs`; additional evidence-backed references are related/context links, not new onsets. Several episodes may share a step. Duplicate references and conflicting numbers/anchors fail validation.

Illustrative excerpt:

```yaml
schema_version: "2"
episodes:
  - episode_id: "ep1"
    problem_number: 1
    first_observed_step_id: "s12"
    onset_step_ids: ["s12"]
```

The viewer labels the version 2 anchor “First observed at step X,” the anchor step “First observed here,” and any other explicitly linked onset “Also observed here.” Every related or recovery group shows the same problem number and first anchor; summary and detail buttons jump to that anchor. For existing unversioned records, preserve the saved artifact and derive a display-only legacy anchor from the earliest explicit `onset_step_ids` entry in source-trace order. Label it “First flagged at step X,” with “First flagged here” at that step and “Also flagged here” at other explicit onset IDs. If IDs are absent, do not infer an anchor or fill an intermediate step. See the [local POC viewer contract](../poc/README.md#problem-number-and-first-observed-contract).

## Work identity and publication

| Unique work | Key |
|---|---|
| Review/extraction | `(workspace_id, rollout_id, source_revision, evaluation_record_id, review_kind, review_recipe_id)` |
| Classification | `(analysis_revision_id, taxonomy_release_id, classifier_recipe_id)` |
| Assignment | `(classification_revision_id, episode_id, mode_revision_id)` |
| Batch demand | `(batch_run_id, member_revision_id, stage)`; review stage includes its selected review kind |

At most one primary mode per episode; a primary outcome-contributing episode is optional for failed rollouts. Reuse only permitted identical work, linking it to batch-local membership/review and authorizing every read through the batch. Same bytes imply no shared access. Intentional model experiments get a new configuration/replicate identity; transport retries retain identity.

A recipe hash pins code-image digest, adapters/workflows, parser/redaction, **review kind and prompt/agent recipe**, model/decoding, selection/budget, output schema and embeddings. Batch snapshots additionally pin source, execution/evaluation, route eligibility and taxonomy. Retain actual provider/model metadata and raw responses. Replayable configuration guarantees neither stochastic equality nor permanent hosted-model availability.

Machine runs publish revision 1. Reviewed corrections append `supersedes_revision_id`, author/rationale/scope and conditionally advance only authorized batch selections. Recheck classification eligibility for that exact new revision: classify its episodes, or bypass with `not_applicable`/`no_episodes` if empty. Neither rerun the original job nor silently change other batches.

```text
pending → running → succeeded
              └──→ retry_wait → running
              └──→ quarantined / dead_letter
expired running lease → reclaim with higher fencing token
```

1. **Register:** transactionally write input/membership, unique job and outbox. Broker outage still permits durable admission. Elected relay sends due events to durable quorum queues with publisher confirms, then records confirmation. A crash can duplicate publication; messages contain IDs/generation, never trajectories/secrets.
2. **Claim:** Celery conditionally claims that job ID/generation in PostgreSQL, reserves workspace execution capacity and sets running state, trajectory lease/attempt/fence using database time; commit immediately. Workers do not scan a ready-work queue. Stale/completed messages are no-ops; live-owner duplicates may ACK because lease recovery redispatches. Quota deferral durably schedules one future dispatch before ACK, without an inference attempt.
3. **Invoke:** run outside transactions; heartbeat only matching live claims/deadlines. Before **every call**, atomically reserve provider concurrency, request/token rate and estimated spend under workspace/provider/remaining-trajectory limits. Settle usage and release concurrency afterward; unknown usage is not zero. Initial reservations never authorize unlimited follow-ups. Checkpoints permit bounded deferral/resume. Restrict prefetch; RabbitMQ/Celery cannot enforce global inference limits/idempotency.
4. **Publish:** write bulky artifacts to attempt-specific keys. Lock/validate the current **unexpired, uncancelled claim**; atomically commit structured results and pointers, dependent jobs/outbox, quota release and completion; then ACK. Post-commit duplicates are harmless; pre-commit crashes can repeat inference charges.
5. **Recover:** retry transaction writes future `available_at`/state and releases quota before ACK. Lease recovery fences old owners and increments delivery generation; all attempt-owned success/retry/failure transitions need live tokens. Reconcile stranded work without new logical jobs. Disable Celery ETA/autoretry/countdown; the outbox owns timing. Reconcile broker delivery limits/DLQ separately from application attempts/dead letters.

- Relay `SKIP LOCKED` is short reservation coordination, not worker delivery. RabbitMQ owns transport; PostgreSQL owns state/publication. Cancellation/completion serialize; another batch's shared demand survives. Sweep orphan objects after grace. [Queue semantics](08-local-deployment-and-queue.md).
- Allow **four application attempts total** (initial attempt plus up to three retries for retryable failures), honoring provider hints. The local per-attempt allowance estimates spending; hard trajectory spend caps and **one bounded schema repair** remain design targets. Redrive requires operator decision or recipe fix, never unchanged poison loops. Planned checkpoints avoid repeated normalization/inference. Cache keys include input/recipe/access/redaction; no cross-permission reuse.

## Reprocessing, releases and reproducible views

- Backfills pin cohort/recipes, estimate cost and use separate quota. Taxonomy-only changes reuse episodes; missing distinctions require selective extraction.
- Parallel trajectory reviewers read the approved taxonomy and latest shared proposal pool; new/edited proposals append immutable revisions, visible to other reviewers without changing the release. Conflicting edits and stale bases remain separate for explicit resolution or rebase.
- After all reviews in a batch finish, a separate consolidation run compares near-duplicate new/edited labels and proposes canonical mappings or aliases with rationale. Preserve raw reviews/proposals; version the resulting candidate taxonomy and bind it to its base and evidence.
- Proposal lifecycle is draft → in_review → approved → published, with rejected/superseded/stale branches. Approval binds the exact candidate/revision/hash/base and reviewed evidence; edits, feedback redrafts or changed dependencies invalidate it. Publication atomically checks curator permission/base/approval. Models cannot publish names/descriptions/new/merge/split/deprecate changes; assignment reads released definitions only. Feedback drafts artifacts, never trains weights. Review-ready, assignment-pending and curation-pending are independent.
- A run selects admitted input/evaluation revisions and batch-local results under its pinned profile. Source updates cannot replace membership. Missing compatible results stay pending/incomplete, never borrow an older profile's output. Classification references exact analysis; only atomically published results appear. Late old work cannot change the active profile.
- After shadow evaluation/coverage review, create a successor run with explicit membership boundary; rollback restores selection. Display changes never mutate old runs. Human corrections append events/results; reports freeze membership/results using a consistent database snapshot. [Platform version rules](05-platform-and-workflows.md).

## Fictional YAML example

Wrong-field action followed by local recovery. IDs are fictional. This excerpt belongs to a selected failed record; retained evidence does not reveal later effects/final state. A real artifact needs complete manifest/index locators, hashes, evaluation/preset/recipe references and provenance.

```yaml
schema_version: "1"
artifact_type: trajectory_analysis
review_kind: failure_analysis
taxonomy_release: null
steps:
  - step_id: "s12"
    review_status: reviewed
    intent:
      kind: declared
      text: "Edit the title."
      evidence_refs: ["e12-intent"]
    action: "Clear the notes field."
    observed_ui: "Notes changed from their original text to empty."
    effect: "Notes content was removed."
    assessment: "The action targeted a different field from the stated intent."
    evidence_refs: ["e12-action", "e12-before", "e12-after"]
    episode_refs: [{episode_id: "ep1", role: onset}]
  - step_id: "s13"
    review_status: reviewed
    intent:
      kind: declared
      text: "Undo the accidental notes change."
      evidence_refs: ["e13-intent"]
    action: "Undo."
    observed_ui: "Notes match their original text."
    effect: "Local notes content was restored."
    assessment: "Recovery of the notes content is visible."
    evidence_refs: ["e13-action", "e13-after", "e12-before"]
    episode_refs: [{episode_id: "ep1", role: recovery}]
episodes:
  - episode_id: "ep1"
    onset_span: {start_step_id: "s12", end_step_id: "s12"}
    mechanism: "Action targeted the wrong field."
    recovery:
      status: recovered
      step_ids: ["s13"]
      evidence_refs: ["e12-before", "e13-after"]
      assessed_through_step_id: "s13"
      scope: "Visible local notes content."
    outcome_contribution: uncertain
    contribution_rationale: "Later effects and final state are unavailable."
```

The mechanism stays unchanged by recovery. Classification later uses an independently versioned release. For a passed evaluation, the same evidence instead uses `review_kind: pass_recovery` and `outcome_contribution: not_applicable`; it does not invent a different mechanism.

## Query contract

- Failure mode share includes only selected **failed** records: contributing episodes, deduplicated to `(rollout_id, mode_id)`. Exclude noncontributing; report uncertain separately. Recovery is independent, so recovered episodes with residual contribution remain eligible. Keep the denominator of analyzed failed attempts, including abstentions, explicit.
- Report passing recovery separately with its own cohort/coverage/denominators; never mix not-applicable contribution into failure prevalence. Discovery may use episodes from both routes. “Mode observed anywhere” is a separate metric. Return counts, sampling, coverage/pending/abstention, review-kind/profile/taxonomy IDs with rates.
- APIs: bounded filtered aggregates, timeline/evidence, related episodes, cost-estimated reprocessing, proposal review and release publication. Researchers have read/review scope; authorized operators publish or launch large backfills. Pagination/scoped filters bound expensive retrieval.
