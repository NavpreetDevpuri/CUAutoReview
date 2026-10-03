# 4. Evaluation and delivery

**Status:** A local Compose platform implements core workspace, import, run, queue, storage, viewer and taxonomy workflows. [Platform status](../../platform/README.md), [test results](../../platform/docs/TEST-RESULTS.md) and [live model evidence](../../platform/docs/LIVE-RESULTS.md) record completed checks and their limits. Production readiness, platform scale and diagnosis accuracy remain unestablished. The separate five-trajectory CLI POC remains complete; [the Luna baseline](../../poc/docs/RESULTS.md) and [Sol rerun](../../poc/docs/RESULTS-SOL.md) record historical usage, label consolidation and diagnosis limitations.

- **Design deliverable:** system-design document/diagram, decisions and tradeoffs, compact README, detailed specs and sourced examples. The narrow local POC is described in [README](../../README.md#local-poc); the implemented local platform is described in [platform/README.md](../../platform/README.md). Repository publication and production deployment remain separate.
- **Experiments later:** answer specific uncertainties; do not make a full platform an accidental submission requirement.

## Evidence for design review

| Assignment criterion | Where the design addresses it |
|---|---|
| Architecture | Complete manifests, RabbitMQ/Celery, outbox/reconciliation, fencing, quotas, staged scaling |
| Analysis | Task/intent/action/effect/grade comparisons, cited intervals, alternatives, evaluator disagreement, abstention, held-out checks |
| Taxonomy | Separate assignment/curation, hierarchy versus facets/severity, feedback, exact-draft approval, immutable merge/split history |
| Data model | Report → selected run → assignment → episode → versioned evidence |
| Tradeoffs | [Decisions](03-decisions-and-tradeoffs.md), measured cost/quality/coverage, review capacity and deferred complexity |

Assignment topics 1–4 map to the main design, 5 to data contracts, 6 to capacity/reliability below.

## Quality benchmark

- **About 300 human-reviewed rollouts:** stratify by domain, agent version, length, outcome, severity and screenshot completeness. Two independent reviewers, adjudication and agreement reporting.
  - Include disputed grades and rare cases; weight oversampling when estimating production prevalence.
  - Passing cases: clean pass, recovered mistake, late/partial repair, unresolved issue despite pass, missing evidence. Failing cases retain contributing and recovered episodes.
- **Split by task and near-duplicate template:** keep all K siblings together; exclude holdouts from taxonomy induction/retrieval. Maintain a frozen benchmark plus later-time drift set; compare terminal-error baseline and previous profile.
- **Report uncertainty:** per-domain confidence intervals with task-level resampling for correlated siblings. Small slices are inconclusive; 300 examples cannot establish rare-event performance. Calibrate numeric gates with reviewers; averages must not hide critical unsupported-claim regressions.

| Check | Provisional gate / measurement |
|---|---|
| Provenance | Every material claim cites valid evidence; zero broken benchmark references |
| Explanation | ≥90% of non-abstained explanations supported and specific in blinded review |
| Localization | ≥80% within adjudicated interval or one adjacent event; separate initiating divergence from terminal manifestation |
| Episodes | ≥80% recall for annotated outcome-contributing episodes; also precision and secondary/recovered recall |
| Step artifact | Exactly one annotation/status per normalized step, preserving source-step references; valid YAML/schema/evidence/episode links. Hidden omissions never count as reviewed |
| Recovery | Status and repair-step localization separate from mode accuracy/contribution; test partial/late repair, residual harm and truncated evidence |
| Abstention | Quality versus coverage; supported diagnosis for ≥70% of failed rollouts meeting predeclared evidence-availability criteria, independent of model confidence |
| Passing review | Separately measure mistake/recovery precision/recall, clean-pass false positives, unresolved cases, coverage, latency and cost; no assumed speed/accuracy gain |
| Taxonomy | Pairwise assignment precision/recall, coherence, boundary confusion, correction rate; calibrate auto-assignment to ≤5% measured error before enabling |
| Novelty | Hold out entire modes; missed new mechanisms, false proposals and review minutes/accepted mode; confirm prospectively |

- **Attribution checks:** wrong plan correctly executed, intent/action mismatch, tool rejection, changed UI, recovered error and evaluator disagreement. Measure confusion and missing-intent abstention; these are test cases, not a fixed taxonomy.
- **Separate stages:** assignment versus diagnosis latency; curator draft acceptance/revision, duplicates, label churn and reviewer minutes. Speed never bypasses taxonomy approval.
- **Backend comparison:** same frozen evidence, prompts, schemas and budgets across API/harness routes; include startup, failed auth, tool restrictions and unknown billing.
- **Agent/helper comparison:** trajectory agent versus fresh agent per step, on short/long traces. Measure all billed context/output, helper calls, wall time, coverage, consistency and recovery accuracy.
  - Compare compact views with originals, including omitted frames/repeated UI elements. Compare lighter passing review with deeper review on held-out passes.
  - Shared context is a hypothesis, not proven savings. Checkpoint restoration must preserve unresolved episodes without duplicate annotations.

## Metrics and denominators

| Metric | Definition and caveat |
|---|---|
| Evaluator failure incidence | Failed / all cohort attempts with known pass/fail, including analysis-pending attempts |
| Outcome-contributing mode share | Distinct analyzed failed attempts with a `contributing` episode assigned M / all analyzed failed attempts, including abstentions. Exclude `noncontributing`; report `uncertain` separately. Multiple modes can sum above 100% |
| Mode observed anywhere | Distinct reviewed attempts containing M / reviewed attempts, separately by outcome and review route. Does not imply final-outcome contribution; disclose abstentions/partial coverage |
| Recovery | Counts/rates for `not_assessed`, `none_observed`, `partial`, `recovered`, `unknown`, within recorded observation boundaries. Show all counts, known-assessment denominators and missingness; report pass/fail separately |
| Task-balanced mode share | Average within-task shares over tasks with analyzed failures; show omitted tasks, coverage and affected-task counts. Larger K increases opportunities to observe a mode |

- A repair attempt is not confirmed recovery; `none_observed` does not mean impossible. A recovered error can still contribute through lost time/irreversible harm. Passed episodes use contribution `not_applicable` and never enter failed-outcome prevalence.
- Compare agent versions on matched task/environment/evaluator cohorts using the same pinned analysis profile and taxonomy within each review route. Show denominators, route/prompt versions, sampling probabilities, pending/incomplete inputs and exclusions.
- Default review covers both outcomes; old failed-only data cannot estimate recovery across all attempts. Partial/inconclusive differs from “no issue observed.” A taxonomy change is not an agent regression.

## Capacity and cost

**Sizing assumptions:** 50k historical attempts; 10k new/day; 40% failed, remaining 60% passed; 5 MB JSON + 20 MB screenshots each. Normalize all; route by the pinned evaluator adapter, never a universal numeric threshold.

| Current policy | Daily volume / storage |
|---|---|
| Historical raw data | 50,000 × 25 MB ≈ **1.25 TB** |
| Raw arrivals | **250 GB/day**, **7.5 TB/30 days**, before retention, replication and derived artifacts |
| Trajectory reviews | **4,000 failure analyses + 6,000 passing recovery reviews = 10,000/day**, before escalation |
| Illustrative stage jobs | 10k normalization + 10k review + up to 10k classification ≈ **up to 30k/day, 0.35/s**; classify where meaningful, exclude retries/curation/other stages |

**Observed inference cost, 27 September 2026:** the [visual check](../../platform/docs/LIVE-RESULTS.md) saved 9 reviews from 11 attempts for **$0.36706550 estimated**, including both unsuccessful attempts. It covers 8 distinct trajectories, with one reviewed by both Gemini and Sol. Provider invoices are unverified.

| Arithmetic | Result and limit |
|---|---|
| Estimated cost / saved review | $0.36706550 ÷ 9 = **$0.040785**; retries included, heterogeneous models/evidence |
| 10,000 saved reviews/day at exactly that sample mix | **$407.85/day inference only**, covering both outcome routes rather than only failures |
| 1,000,000 saved reviews/day at exactly that sample mix | **$40,785.06/day inference only**; 25 TB/day raw under the separate sizing assumption |

These are transparent arithmetic scenarios, **not production forecasts, confidence bounds or capacity evidence**. Eight trajectories cannot represent long traces, route mix, provider failures or future prices. The sample's one-call reviews do not measure the design's multi-call agents, classification, curation or all historical spend. Passing-review speed/cost advantages remain unmeasured.

- **Production budget:** `failure_count × measured_failure_cost + pass_count × measured_pass_cost + classification + curation + retries + infrastructure + human review`. Count retries once; the sample average above already includes its failed attempts.
  - Measure cached/uncached input, output, images/resolution, compaction, checking, rendering, latency and cache hits by stage/route. Session continuity does not make context free. Size workers from full session duration and provider concurrency from active calls.
  - Budget derived YAML/views, retention, bulk discounts, routing and backfills. Benchmark execution/VMs are separate. More workers cannot solve provider or spending limits.
- **Illustrative human capacity, unmeasured:** curator hours/day = deduplicated candidates/day × minutes/candidate ÷ 60. At 20 candidates × 10 minutes, that is **3.3 hours/day**. Independently inspecting 0.5% of 10k reviews at 5 minutes each adds **4.2 hours/day**, before disagreements, second reviewers and administration. Measure actual novelty, deduplication and review time before staffing; price hours at the applicable loaded rate.

<details>
<summary>Historical failed-only calculation, superseded</summary>

One initial call for each failed attempt, then 25% escalation. This excludes passing review and the selected multi-call agent workflow; retain it only to explain earlier estimates.

| Earlier assumption | Arithmetic |
|---|---|
| Initial calls | 4,000/day; 12k input × $1/M + 1k output × $5/M = **$0.017 each; $68/day** |
| Escalation | 1,000/day; 8k input/image-equivalent × $5/M + 1k output × $15/M = **$0.055 each; $55/day** |
| Inference subtotal | **$123/day; $147.60/day** with 20% retry/variance reserve |
| Active model calls | (4,000 × 30 sec + 1,000 × 60 sec) / 86,400 ≈ **2.08** mean; sustained 10× peak ≈ **21 slots** before headroom |

Hypothetical prices/latencies, not vendor quotes. Excludes passing review, summarization, classification, embeddings, verification, taxonomy discovery, storage/compute, humans and taxes. Its earlier 1M/day extrapolation was roughly $14.8k/day with reserve for that limited inference portion. Do not use those costs or 2.08/21 concurrency slots for current capacity planning.

</details>

## Reliability and operations

- **Proposed targets:** ≥99.9% of valid ready manifests registered within 24 hours of manifest publication; P95 live ready-manifest → review and applicable classification within 15 minutes for complete eligible inputs under assumed load/healthy provider. No episodes means classification `not_applicable`; only adequate evidence/coverage supports `no_issue_observed`. Partial/inconclusive/abstained reviews retain those states. Report terminal-processing latency separately from complete-review coverage.
  - Measure each review route separately, plus end-to-end latency including outages/budget deferrals. Backfills receive completion estimates, not the live SLO.
- **Observe:** job/run IDs; outbox age/confirms; broker ready/unacked/redelivery, quorum health; reconciliation gaps; oldest-job age; provider throttling; stage errors; application dead letters/broker DLQ; missing evidence; spend; abstention; novelty/drift; reviewer backlog.
- **Outages:** RabbitMQ failure accumulates durable outbox work. PostgreSQL failure stops ownership/publication; consumers stop/defer rather than ACK unfinished work. After restore, reconcile inputs/stranded dispatches and revalidate ownership. Retain outbox/jobs beyond recovery needs; broker persistence does not replace DB/object backups.

| Failure drill | Required invariant |
|---|---|
| Duplicate/interrupted discovery; reordered notifications | One input revision; reconciliation finds missing ready manifests |
| Missing/corrupt object; interrupted upload | Inspectable quarantine; no unsupported complete-input result |
| Crash after inference/object write/DB commit | Recoverable job, one publication; stale lease cannot win |
| Confirm/result commit before ACK crash | Idempotent duplicate dispatch/redelivery; no lost work |
| Broker leader/node loss, disk pressure, poison limit | Observed quorum/backpressure; no silent loss; DB reconciliation can redrive |
| Retry timing, bursts, quota exhaustion | One outbox scheduler, bounded attempts/fair capacity; no competing Celery clock |
| Provider 429/outage; oversized rollout | Bounded retries/spend; explicit deferral/incompleteness |
| Old recipe completes after profile switch | Correct active profile; frozen report membership |
| Taxonomy merge/split | Deduplicated prevalence; split children unresolved until reclassification |
| Redraft/evidence change/concurrent release | Invalidate approval; re-review exact draft/base/preconditions; old reports unchanged |
| Harness capability/auth/event/tool failure | Visible blocker/partial evidence, bounded retry/cleanup; no invented grade/unintended action |
| YAML duplicates/tags/oversize; missing step/bad link | Safe rejection/bounded repair; no silent loss or unsupported complete review |
| Checkpoint/compaction/omitted frame/late recovery | One final annotation per step; explicit gaps; episodes/recoveries retained and reconciled |
| Restore/access revocation/team removal/cross-batch search | Consistent replayed references; effective scoped grants; no inaccessible evidence/counts |
| Append/duplicate sync/task without rollout | Existing results unchanged; one admission; explicit waiting |
| Preset/rubric edit in active batch | Old runs/new arrivals stay pinned until explicit successor |
| Pass/failed/unknown/error input | Correct separate prompt/configuration; unknown/error await resolution; grade preserved, no forced mistake/recovery |
| Passing rollout with no issue or missing evidence | No-issue differs from partial/inconclusive; neither creates fake labels |
| Old failed-only batch upgraded | Explicit successor/backfill; old passes never silently marked reviewed |
| Partial K/runner dispatch timeout | Reconcile reserved slots; no duplicate attempt/unneeded rerun |
| Shared output locally reviewed/cancelled | Other batches' selections/demands remain intact |
| Imported evaluator differs from preset | Block strict admission; explicit rescore or exploratory cohort |
| Compose restart/worker death/blocked egress | Persistent jobs/artifacts, lease recovery; fixtures need no hosted service |

- **Scale progressively:** fixed-concurrency Celery replicas/pools from oldest-job age/provider capacity; no built-in quorum worker autoscaling. Bound prefetch/connections; index due-outbox/ownership/recovery queries.
- Monitor broker throughput/disk/replication and DB writes/vacuum. Quorum replication is not infinite partitioning; shard stage/workspace queues only after measurement.
- Retain transient delivery/audit rows separately from immutable results; tune indexes/aggregates, then offload long scans/vector work. Broker adoption does not remove DB publication writes. At larger scale, cluster sampled representatives incrementally, not all pairs.

## Delivery sequence

**Submit the design:** decisions/alternatives, diagram, provenance and unmeasured assumptions. The [POC](../../poc/docs/RESULTS-SOL.md) and [live platform checks](../../platform/docs/LIVE-RESULTS.md) include failed and passing examples, but lack independent diagnosis adjudication and establish neither accuracy nor production throughput. [Reuse](09-open-source-reuse.md) and [harness contracts](10-harnesses-and-authentication.md) distinguish documented capabilities from tested integrations.

| Delivery stage, partly implemented locally | Gate |
|---|---|
| 0. Inspect and broaden failed/passing examples | Real tasks/scores/frames/provenance; distinguish machine grade from human cause |
| 1. Compose foundation, fixtures, adapter, scoped API/React-admin, sync/presets | Offline persistence/provenance/access/append/outbox/confirm/ACK/crash checks |
| 2. Both review agents, reviewed benchmark, bounded inference, queryable episodes | Measured fidelity/localization/coverage/recovery/uncertainty and total cost |
| 3. Assignment/discovery/feedback/UI approvals, immutable releases/snapshots | Coherence, stale-draft controls and merge/split history |
| 4. Load/quotas/live-backfill isolation/recovery/lifecycle; optional runners/adapters | Measured SLOs, compatibility and budget adherence |

- Before production resolve manifest control, representative sizes, evaluator reliability, permitted processing/models, retention, latency/budget priorities and reviewer hours. Design defaults do not invent answers.
- Prefer narrow spikes: broker/outbox crash recovery with 1×/10×/100× bursts; API-versus-ACP conformance; blind attribution; passing-recovery detection; taxonomy redraft conflicts; one reusable trajectory/diff screen. Revisit choices using measurements; no throughput claim or experiment is required now.
- **Viewer acceptance:** the header scrolls away; task and step share one collapsible sidebar; text is readable; screenshots fill the content width with explanations below and stay aligned during navigation; definitions are always visible inline; category chips use consistent colors and IDs; numbered problem groups preserve one number across onset, related and recovery views and show independent roles for each linked problem. Version 2 anchors use `first_observed_step_id`; legacy anchors use only the earliest explicit `onset_step_ids` in source order. Summaries and related/recovery groups jump to that exact anchor; **Screen ↑** returns to the selected screenshot. “First flagged here,” “Also flagged here,” “First observed here,” “Also observed here,” “Recovery step” and “Related step” map only to explicit records. Missing evidence stays uncertain, with no inferred intermediate mistake steps. Keep role, failure category and recovery separate, and preserve raw outputs and historical IDs. See [platform UI](05-platform-and-workflows.md) and the [viewer feedback log](../../poc/docs/VIEWER-FEEDBACK.md).
