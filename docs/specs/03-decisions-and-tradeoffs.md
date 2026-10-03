# 3. Decisions and tradeoffs

Our choices, their costs and when to reconsider them. The assignment asks for a design. A core local platform now exists alongside the focused local CLI POC; this document still includes design targets beyond that implementation. See [platform status](../../platform/README.md) and [test results](../../platform/docs/TEST-RESULTS.md).

## Evidence and review

| Choice | Why and limits | Alternative / revisit when |
|---|---|---|
| **OSWorld-Verified first** | Our source assumption, not an assignment requirement. Public tasks, checkers and scored desktop traces; historical evaluator versions may be unknown. | Replace the adapter; consider OSWorld 2.1 for long cases or BrowserGym/AgentLab for browser tasks. [Evidence](06-benchmark-and-example-data.md). |
| **YAML inputs and review artifacts** | Human-, model- and code-readable indexes, presets, taxonomy/proposals and step reviews. Validate a restricted safe subset; hash logical content separately from bytes. | Keep native JSON/JSONL/images, JSON APIs and authoritative PostgreSQL state. YAML is not necessarily token-cheaper. [Contracts](02-data-and-contracts.md). |
| **Separate failure and passing-review agents** | `failure_analysis` explains failed outcomes; default `pass_recovery` finds mistakes/recovery despite a passing grade. Separate versioned prompts/configurations; lighter passing review adds coverage and cost. | Benchmark speed, false positives and missed recoveries. Expand uncertain evidence or return partial coverage; never silently skip passes, rescore outcomes or alter old presets. |
| **One logical agent per trajectory** | Sequential shared context links causes and later recovery. Parallelize trajectories; bound long traces with windows/checkpoints. | Compare with fresh agents per step. Multiple calls may resend/bill context; session continuity does not guarantee savings. |
| **Shared deterministic compact/render helpers** | Agent and UI inspect the same indexed text, frames and crops. Omission maps and expandable originals preserve provenance. | Test against full evidence: compaction can hide causes. Helpers remain allowlisted/read-only, without shell or desktop access. |
| **Every step annotated; images selected** | Record intent/action/UI/effect, source links and reviewed/not-reviewed/insufficient-evidence states. Selected full-resolution frames bound cost. | Measure broader inspection and cross-step recall. Compact text cannot establish unseen visual facts; publish partial coverage honestly. |
| **Task → intent → action → effect → outcome** | Distinguishes wrong planning, intent/action mismatch and tool/environment failure. Visible intent, action descriptions and exit codes do not prove execution. | Missing intent stays uncertain; never infer hidden reasoning. Causal confirmation requires replay/intervention beyond observation. |
| **Multiple episodes; optional primary cause** | Preserves independent, linked and recovered mistakes. Deduplicate aggregates. | A single label is useful as a display summary, but loses causal chains and uncertainty. |
| **Recovery independent of taxonomy/contribution** | Track restoration, repair steps and evidence without recovered/unrecovered duplicate labels. A repaired error can still waste budget or leave damage. | Failed-outcome contribution controls failure prevalence; passed episodes use `not_applicable`. A pass does not prove every mistake recovered. |

## Taxonomy, history and product

| Choice | Why and limits | Alternative / revisit when |
|---|---|---|
| **Extract evidence before classifying** | Taxonomy changes reuse expensive observations and episodes. Version relationships require discipline. | Re-extract when new distinctions need missing context; old summaries are not complete evidence. |
| **Mechanism modes; context as facets** | A shallow hierarchy transfers across domains without a label per application/error string. Reviewed examples define boundaries. | Add domain-specific children only for distinct mechanisms/remedies that survive held-out review. |
| **Analysis → assignment → shared proposals → consolidation** | Save explanations before labels. Parallel trajectory reviewers read the approved release and latest shared append-only proposal pool; a separate post-batch agent proposes canonical mappings for near-duplicates. Raw reviews/proposals remain intact. | Conflicts/stale bases require explicit resolution or rebase. Every published name/definition/structure change needs human approval of the exact candidate/base/evidence; assignment reads only a pinned release. |
| **Immutable releases and query profiles** | Reproducible trends/rollback; explicit adoption and successor runs preserve older results. Reclassification costs money and may leave unresolved history. | “Always latest” hides whether trends reflect behavior or analyzer changes. Backfill old passing attempts explicitly. |
| **Dataset → batches → sync waves** | Teams/experiments share a source catalog while arrival history and completed work survive appends. Task-only inputs await an imported or newly executed rollout. | Fixed batches suit one-off experiments; support fixed and appendable modes. |
| **Approved plugins and pinned presets** | Formats, models and workflows evolve independently; new arrivals inherit exact settings. Conformance/compatibility checks add work. | Add workflow-builder flexibility only for demonstrated needs. |
| **Reuse UI/admin components** | A maintained framework supplies tables, forms, filters and auth integration; specialize trajectory alignment, evidence and taxonomy diffs. | Specify UI now. Build a narrow prototype only to answer a measured design question. |

## Infrastructure and execution

| Choice | Why and limits | Alternative / revisit when |
|---|---|---|
| **RabbitMQ quorum/Celery + PostgreSQL state/outbox** | Isolates delivery/backpressure and reuses worker tooling. Transactional admission/outbox plus idempotent completion tolerate duplicates. One local broker; three nodes for production HA. | PostgreSQL queues remain credible at 10k/day. NATS needs worker integration; SQS reduces operations but weakens local parity; Temporal suits complex workflows. [Comparison](08-local-deployment-and-queue.md). |
| **SeaweedFS locally; AWS S3 by configuration** | Same object client in the local Compose stack; persistent volumes, immutable keys/checksums. | Verify API compatibility locally, IAM/notifications/scale in cloud. Provisioning/data migration remain explicit. [Deployment](08-local-deployment-and-queue.md). |
| **Ready manifest + registration/reconciliation** | Declares complete multi-object input; registration is prompt, listing catches missed/external arrivals without local notifications. | Add AWS notifications to reduce polling cost/latency; retain reconciliation. |
| **Leases, fencing, at-least-once execution** | Unique keys and fenced completion prevent duplicate authoritative results. Crashed calls can still repeat provider charges. | Cross-service “exactly once” adds complexity without removing external inference side effects. |
| **LiteLLM / ACP-acpx / Harbor** | Separate API, CLI-review and benchmark layers; capability-check each stage. API keys/workload credentials suit unattended containers. | ACP does not guarantee image/tool/auth parity; retain native SDK/CLI fallback. Harbor OSWorld needs a desktop agent, not an arbitrary coding CLI. [Reuse](09-open-source-reuse.md) · [auth](10-harnesses-and-authentication.md). |
| **PostgreSQL/pgvector first** | Transactions, joins, metadata and moderate vector retrieval share one service; scans can compete with ingestion. | Tune indexes/aggregates first; export partitioned Parquet to S3/Athena or add warehouse/search when measured SLOs require it. |

## Operating boundaries

- **Durability and fairness:** retain backlog through outages; centrally bound concurrent calls, requests/minute, tokens/minute and daily spend. More workers cannot bypass quotas.
  - Start with 80% live capacity, 20% backfills; borrow idle capacity and monitor oldest-job age per queue, including both review routes.
- **Cost versus quality:** validate cheaper models on held-out tasks; escalate uncertain/high-impact cases. At budget limits, defer or mark inconclusive. Never silently weaken a recipe. Provider choice remains empirical.
- **Untrusted evidence:** screenshots, logs, YAML and visible reasoning are data, not instructions. Allow only scoped read/render helpers through controlled API/harness adapters.
  - Disable arbitrary shell, desktop actions, unrestricted network/writes, ambient hooks/MCP/project instructions. Explicit approved helpers are the exception.
  - A trusted validator/serializer saves YAML. Enforce file/decompression/parser limits. Credentials stay in invocation/auth layers, outside evidence/context. Benchmark execution uses a separate sandbox/tools.
- **Privacy and access:** encrypt storage, scope service roles and restrict raw evidence more than aggregates. Redact secrets/PII before external inference/indexing; record redaction version and lost-evidence warnings.
  - Necessary context removed or approved processing unavailable: restricted review or abstention, never weaker policy for higher confidence.
- **Retention:** configure by data class. Deletion obligations override immutable history and propagate to artifacts, indexes and caches; tombstones disclose reduced reproducibility. Test backup recovery/access before sensitive data.
