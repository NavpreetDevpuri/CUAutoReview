# Platform brainstorm: captured 26 September 2026

This records your requested additions. It is separate from the original assignment. The work remains local documentation and research; implementation and publication are future steps.

| Your idea | Captured decision / next step |
|---|---|
| Run the whole platform locally with Docker Compose | Updated to five core services: app, Celery worker, PostgreSQL, RabbitMQ, and SeaweedFS; offline fixture default, optional real local models. |
| Switch local services to live infrastructure through environment settings | Same application/S3 client with configurable endpoints, database URL, bucket, and credential source. Provisioning and data migration remain explicit deployment work. |
| Keep the queue minimal; consider PostgreSQL | Earlier PostgreSQL queue choice superseded after your scale/reuse request: RabbitMQ quorum delivery + Celery; PostgreSQL keeps work state/outbox and fenced publication. PostgreSQL was not ruled out as inherently unscalable. |
| Use the straightforward name CUAutoReview | Accepted project name: **Computer Use Auto Review**. Local folder and authored document links renamed; original assignment preserved. |
| Use the newly released Jev model for quick analysis | Evaluate TypeSafe Jev as optional text-based triage and existing-mode classification. Preserve the evaluator and evidence/VLM pipeline; see [the proposal](../specs/07-jev-fast-analysis.md). |
| Build a platform with admins, viewers, and teams | Workspace membership, team membership, and scoped batch roles; users can be added and removed. |
| Assign teams to particular batches | Team-to-batch grants; access to one batch does not expose an entire dataset. |
| Datasets contain several batches | A dataset is the source catalog; each batch selects work and has its own configuration and team grants. |
| Add several tasks now and more later | Record additions as immutable sync waves within an appendable batch, or create another batch. |
| Show exactly which tasks are new | Sync preview separates new tasks, new attempts, revised inputs, unchanged items, and source removals. |
| New tasks receive the same evaluation as earlier tasks | Pin execution/evaluation and analysis preset revisions. New arrivals inherit those revisions; editing a preset does not change a running batch. |
| Add arriving work to a running queue | Idempotently enqueue matching new items; preserve running/completed work and show a fresh wave of arrivals. |
| Support different trajectory formats | Versioned adapters normalize source formats while retaining original artifacts and source-specific metadata. |
| Support different workflows, models, and configurations | Approved workflow stages, model/provider adapters, and reusable immutable preset revisions. |
| Clearly monitor progress | Per-wave progress, continuous-batch backlog and throughput, retries, budget, blocked items, and last sync. |
| Have a UI to inspect actual trajectories | Timeline, screenshots, actions, task instructions, evaluator score/checks, evidence, and review annotations. |
| Choose a strong open-source computer-use benchmark first | Research OSWorld and alternatives; prefer inspectable tasks, actual traces, and executable outcome checks over a popularity claim. |
| Find examples with mistakes already flagged by people | Distinguish human-reviewed failure annotations from machine-scored failures and successful demonstrations; preserve annotation provenance. |
| Generate examples if suitable traces cannot be found | First inspect public artifacts; later run the chosen harness in an isolated environment only for missing coverage. Do not manufacture scores or human labels. |
| Understand the correct result and available scoring | Record the task's success criteria, evaluator implementation/revision, result, and any reference solution; a single golden action sequence may not exist. |
| Earlier request: analyze failures, not ordinary passing trajectories | **Superseded by the recovery-review request below.** Historical presets retain this policy; new presets review both known outcomes through separate agents/prompts. Unknown/error outcomes still await resolution. |
| Treat taxonomy as versioned failure labels | Labels have definitions, examples, and lineage. Pin taxonomy and scoring versions independently; never overwrite historical results. |
| Use the Data OS / Harbor dataset-sync interaction as inspiration | Preserve your described interaction pattern. No Data OS implementation or UI has been inspected or assumed. |

Details: [platform specification](../specs/05-platform-and-workflows.md) and [benchmark research](../specs/06-benchmark-and-example-data.md).

## Follow-up decisions: scale, harnesses, taxonomy, and reuse

| Your request | Captured design |
|---|---|
| Prefer a dedicated scalable queue | RabbitMQ quorum queues/Celery, outbox/confirm/ACK recovery; local single node versus production three-node HA; compare SQS/NATS/Temporal/Redis and retain measured tradeoffs. |
| Support raw APIs, Codex, Gemini CLI and Claude Code | Separate per-stage model API and harness backends; LiteLLM versus ACP/acpx/native adapters; optional Harbor benchmark runner. No automatic desktop-agent parity. |
| Let the deployed system authenticate and run | API key/workload identity default; secrets per invocation, auth/capability preflight, no implicit host login. Native subscription paths require current provider eligibility; no collected subscription-token broker. |
| Explain what the agent says versus does | Preserve task, visible intent, action request/execution, effect and grade; distinguish wrong plan, intent/action mismatch, execution/environment problems and evaluator disagreement with evidence and uncertainty. |
| Separate fast label assignment from taxonomy improvement | Independent validated-analysis, assignment and curator jobs; provider/model can be shared but recipes/contracts/history remain separate. |
| Propose a new label or rename/improve an existing label | Reviewed shallow hierarchy, definition boundaries/examples; proposal diff/impact plus mandatory human approval for every taxonomy change. |
| Give feedback in UI and revise in the background | Feedback pins target/evidence revision; background successor draft; stale/edited proposals lose approval; no automatic publication or model-weight update. |
| UI matters but the assignment is design-only | Specify trajectory and taxonomy review flows; reuse React-admin core if implemented. Do not build/deploy the full UI/stack for this submission. |
| Research deeply and minimize custom work | Source-backed selection/license/operations matrix in spec 9; prefer libraries over extra platforms. Runtime conformance/load/quality experiments remain unperformed and explicitly future work. |
| Keep human review concise | README summarizes all ten specs; expandable contracts/reuse details preserve the important qualifications. |

New research: [queue](../specs/08-local-deployment-and-queue.md) · [open-source reuse](../specs/09-open-source-reuse.md) · [harness/authentication](../specs/10-harnesses-and-authentication.md). Everything remains local documentation.

## Follow-up: explicit decisions, YAML and trajectory-level agents

| Your clarification | Captured design and reason |
|---|---|
| Make our assumptions/decisions prominent and explain why | An early README decision table distinguishes the OSWorld source assumption from assignment requirements, followed by progressively deeper workflow details. |
| Assume tasks/rollouts initially come from OSWorld | OSWorld-Verified supplies concrete examples and checkers; an adapter keeps other sources possible. Historical provenance gaps remain visible. |
| Use YAML for people, agents and code | Versioned evidence indexes, presets/taxonomy and step-review outputs use validated YAML. Native JSON/JSONL/images and JSON APIs are retained; YAML is an artifact format, not a database replacement. |
| One reviewing agent per trajectory | Sequential step review shares task/context and sees later recovery. Bounded windows/checkpoints preserve one logical session; no fresh agent per step. Efficiency must be measured across all calls. |
| Helper scripts compact and render trajectories | Deterministic shared agent/UI views retain source links, mark omissions and support expansion. Original evidence is never deleted merely to shorten context. |
| Compact explanations for every step | Record declared/inferred/unknown intent, action, observed UI/effect, assessment, evidence and linked episodes. Unreviewed or insufficient-evidence steps stay explicit. |
| Track recovery separately from failure labels | Episode recovery and its later steps/evidence are separate from taxonomy and final-outcome contribution. A repaired mistake can still have lasting impact. |
| Reuse step summaries for Jev | Optional typed routing/assignment consumes selected validated text. Jev is not the visual/sequential reviewer or an automatic taxonomy author. |
| Show the complete taxonomy stage | Diagram includes assignment to a pinned release, draft new/changed/retired labels, human approval, new immutable version and explicit reassignment. No silent history rewrites. |

Earlier fixed-call cost estimates are retained only as an illustrative comparison; the selected multi-call trajectory workflow needs a new measured budget. No implementation, helpers, model calls or deployment were run.

## Follow-up: passing recovery review and compact detailed specs

| Your clarification | Captured design and reason |
|---|---|
| Passing/full-score attempts can contain mistakes and later recovery | Default `pass_recovery` reviews every compact step for supported mistakes, later repair and unresolved issues. Preserve the evaluator grade; a pass does not prove recovery or an error-free path. |
| Use a different prompt and agent for this quick review | Separate immutable prompt, agent recipe, logical session and budget from `failure_analysis`; models/helpers may be shared. Expand evidence when needed; speed/cost savings remain unmeasured. |
| Recovery is separate from failure levels/labels | Use the same mechanism taxonomy, independent recovery status and repair evidence. Failed-outcome contribution is `not_applicable` for passed episodes; keep passing and failing metrics/cohorts separate. |
| Include both routes in the complete platform design | Update work identities, presets, UI, workflow diagrams, queue sizing, reporting, Jev costs and validation. At 10k/day with 40% failures, review 4k failed plus 6k passed attempts. |
| Preserve history | Existing failed-only batches remain pinned. Explicit successor runs/backfills review historical passes; no silent result or coverage rewrite. |
| Make every detailed spec compact without losing information | Rewrite all ten with shorter bullets/tables and progressive detail; compare with the saved baseline to preserve contracts, examples, numbers, qualifications and sources. |

Passing-review validation needs genuine passing traces, including clean passes, recovered mistakes, partial/late repair, unresolved issues and missing evidence. The two existing failed fixtures are unchanged. No-issue findings remain distinct from partial/inconclusive reviews; new mistakes or recovery labels are never fabricated.

## Follow-up: focused local POC and shared label proposals

| Your request | Captured design |
|---|---|
| Implement a tiny POC for five actual computer-use trajectories | One CLI review batch, with Codex GPT-6 Luna as the default and GPT-6 Sol only if practical within the minimal-spend constraint. Final implementation status and outcome are tracked in `poc/README.md`; no accuracy or cost result is assumed. |
| Show the reviewed batch simply | One read-only batch viewer with a prominent red POC banner. It may display provisional labels and a versioned candidate taxonomy, without implementing production approval or publication. |
| Let parallel reviewers share taxonomy discovery | Every trajectory reviewer reads the approved taxonomy and latest shared proposal pool. New/edited label proposals append immutable, evidence-linked revisions visible to peers; the approved release is unchanged. Conflicting/stale edits stay distinct pending explicit resolution or rebase. |
| Consolidate similar proposals after reviews finish | A separate post-batch agent compares near-duplicate new/edited labels and proposes canonical mappings or aliases with rationale. Preserve raw reviews/proposals and version the candidate; a human must approve the exact candidate, base and evidence before publication. |

This focused POC is distinct from the still-unimplemented full platform. See [Local POC](../README.md#local-poc), [system design](../specs/01-system-design.md) and [data contracts](../specs/02-data-and-contracts.md).

**Implementation outcome:** five reviews and label consolidation completed using the authorized `gpt-5.6-luna` fallback after this account rejected both requested GPT-6 variants. Six proposals became five draft labels, with recovery kept separate. The [experiment report](../poc/RESULTS.md) records usage, the first integration failure and diagnosis limitations; the full platform remains unimplemented.

**Readability and stronger-model follow-up:** replace the tiny-text slider layout with readable fonts and a labeled step sidebar, making onset/recovery/context explicit. GPT-6 Sol remained unavailable; GPT-5.6 Sol medium completed the same five inputs and produced 11 episodes using eight shared draft labels. [Comparison, costs and limits](../poc/RESULTS-SOL.md).
