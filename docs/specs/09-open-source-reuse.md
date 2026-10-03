# 9. Open-source reuse

**Primary-source review: 26 September 2026. Design only.** Repositories, docs, licenses and deployment examples were inspected; nothing was installed, executed, benchmarked or integrated. “Adopt” means a recommendation subject to the gates below. Moving-branch sources describe the inspected state; implementation must pin tested releases/image digests.

The assignment requires a design document/diagram. A full UI, benchmark farm, identity server or observability platform is unnecessary for submission; useful projects need not become mandatory services.

## Selected combination

- **React-admin MIT core:** forms, tables, routing, data/auth adapters; custom evidence timeline.
- **LiteLLM SDK in-process:** supported model APIs. **acpx/ACP:** first CLI-session candidate, with native adapters where needed.
- **Harbor:** optional execution/import, existing OSWorld adapter and ATIF; retain original scored-trace imports.
- **OpenTelemetry:** portable instrumentation; add a trace backend only when inspection value justifies its footprint.
- **Five always-on services:** app, worker, PostgreSQL, object storage, RabbitMQ. Celery runs in workers; other tools are libraries/optional profiles. PostgreSQL owns state/publication.

No candidate combines our evidence-linked diagnosis, mode discovery/review, versioned assignment, scoped batch membership, reproducible reports and quality evaluation.

## Model calls, sessions and benchmarks

| Choice | Reuse, dependencies and limits |
|---|---|
| **LiteLLM SDK: adopt** | Normalizes supported APIs, routing, usage/cost, fallbacks/errors without another gateway. Python/provider credentials required. Core outside `enterprise/`: **MIT**; enterprise terms differ. CLI sessions are not interchangeable API calls; no subscription entitlement or identical structured-output guarantee. Validate capabilities/output; Jev needs its own adapter until support is verified. |
| **acpx + ACP: gated adoption** | Headless command shape, one-shot/persistent sessions, NDJSON events, permissions/cancellation. Built-ins map Codex/Claude to ACP adapters; Gemini to `gemini --acp`. acpx: **MIT**, **Node 22.13+**, **pre-1.0**. ACP/inspected Codex/Claude adapters: **Apache-2.0**. Pin client/adapters/agents; no unpinned runtime `npx` fetch. Auth, modalities, tools and provider limits still differ. |
| **ACP registry: optional discovery** | Implementation/distribution/auth metadata; validates advertised auth methods. **Apache-2.0**, individual agent terms remain. Automatically updated: import an approved pinned subset, never an executable live catalog. Protocol/capability negotiation is separate from package versions. |
| **Harbor: optional runner; adopt ATIF import** | Agent adapters, task/environment/verifier structure, local Docker/remote backends, trial artifacts, trajectory validation/local viewer. Installed-agent code includes Codex, Claude Code, Gemini CLI. **Apache-2.0**, **Python 3.12+**, Docker/configured environment provider; model charges separate. Import run/trial IDs, resolved config, scores/artifact refs. Celery remains scheduling/retry authority. |

- LiteLLM calls models; ACP controls agent sessions; Harbor runs trials. ACP means Agent **Client** Protocol, not A2A or a benchmark format.
- **ATIF-v1.7** records messages, tool calls/results, observations and optional metrics/subagents. Preserve native logs and screenshot alignment/provenance that conversion may omit. Writing ATIF and loading it into an agent are separate capabilities; it does not replace our evidence/taxonomy schema.
- Claude's ACP adapter uses **Claude Agent SDK**. A permissive adapter license changes neither Claude Code's non-open-source status nor Anthropic auth/subscription restrictions. Native CLI login and SDK integration have distinct supported auth paths. Gemini eligibility is changing; consult current rules, not old free-login examples. [Harness/auth details](10-harnesses-and-authentication.md); never collect provider login tokens just because an adapter exposes auth.

**Harbor OSWorld-Verified:** default **361 Ubuntu tasks**, excluding eight external-login/Google Drive tasks; full selection **369**. Docker/QEMU guest needs **Linux `/dev/kvm` for practical runtime**. Custom `OSWorldAgent` matches upstream desktop actions/observations; ordinary Codex/Claude CLI agents explicitly cannot drive the nested VM. Supporting CLIs does not make them desktop agents.

Its comparison reports one full-suite run per side, differing scored-result counts and missing results scored zero. This is upstream evidence, not our reproduction or multi-run parity. Generated oracles are incomplete/partly model-farmed, not human truth. Mac import/review requires neither KVM nor a full benchmark run.

Imported/Harbor-returned known failures default to `failure_analysis`; passes/full scores default to separate `pass_recovery` prompts, agent recipes/sessions and budgets. Unknown/error grades defer. Compact all-step review and optional visual expansion must evidence errors/correction; passing proves neither recovery nor no issues. Preserve grades/recovery attributes; passing contribution is `not_applicable`, outside failed prevalence.

Sources: [LiteLLM](https://github.com/BerriAI/litellm), [license](https://github.com/BerriAI/litellm/blob/main/LICENSE); [acpx](https://github.com/openclaw/acpx), [agent mappings](https://github.com/openclaw/acpx/blob/main/docs/agents.md), [installation](https://github.com/openclaw/acpx/blob/main/docs/install.md); [ACP](https://github.com/agentclientprotocol/agent-client-protocol), [registry](https://github.com/agentclientprotocol/registry), [Codex](https://github.com/agentclientprotocol/codex-acp)/[Claude](https://github.com/agentclientprotocol/claude-agent-acp) adapters; [Harbor](https://github.com/harbor-framework/harbor), [ATIF](https://github.com/harbor-framework/harbor/blob/main/docs-mintlify/core-concepts/agents/atif.mdx), [OSWorld adapter](https://github.com/harbor-framework/harbor/tree/main/adapters/osworld).

## UI and identity

| Choice | Reuse and remaining work |
|---|---|
| **React-admin core: adopt** | **MIT**, React/Material UI CRUD tables/forms, filters, routing, data providers and authentication/authorization hooks; fits users/teams/datasets/batches/presets/review queues. Custom API provider, progress and evidence view. Core `authProvider.canAccess` follows server-authoritative decisions; advanced `ra-rbac` is **Enterprise**, not an included MIT permission backend. UI checks never replace scoped API authorization. |
| **Refine Core: alternative** | **MIT** headless React CRUD/auth/access/routing, custom UI integration. More presentation assembly; select only if a prototype exposes React-admin viewer constraints. Do not maintain both. Fit judgment, not measured productivity. |
| **shadcn/ui + TanStack Table: optional** | Both **MIT**. Editable component source plus headless sorting/filtering/grouping/selection/server-friendly table logic. No complete admin backend, permissions or evidence viewer; copied code needs maintenance, headless tables need rendering/accessibility. Add another stack only for a concrete viewer gap. |
| **Harbor viewer: reference/components** | Trial/trajectory, reward, timing, artifact/config inspection; React, Radix, TanStack. Local job browser, not scoped multi-team platform. Needs API/data adaptation and dependency/license review; run-launch/artifact endpoints cannot bypass authorization. |
| **Keycloak: optional multi-user OIDC** | **Apache-2.0** login, lifecycle, federation, strong auth/organization integration. Adds server/realm/upgrades and production database/TLS setup; a separate database may share PostgreSQL. CUAutoReview retains batch grants/immediate revocation; stale token roles cannot authorize reads. `start-dev` is development-only. |

React-admin fits predominantly administrative/review screens; invest custom work in synchronized evidence inspection. Loopback fixture identity supports demos only. Shared deployments require real identity before exposing data.

Sources: [React-admin](https://github.com/marmelab/react-admin), [Enterprise RBAC](https://marmelab.com/react-admin/AuthRBAC.html); [Refine Core](https://github.com/refinedev/refine/blob/main/packages/core/README.md); [shadcn/ui](https://github.com/shadcn-ui/ui), [TanStack Table](https://github.com/TanStack/table); [Harbor viewer](https://github.com/harbor-framework/harbor/blob/main/docs-mintlify/core-concepts/results/view-job-results.mdx); [Keycloak](https://github.com/keycloak/keycloak), [production containers](https://www.keycloak.org/server/containers).

## Observability, annotation and taxonomy

| Choice | Capability, license and limits |
|---|---|
| **OpenTelemetry: adopt** | **Apache-2.0** SDKs: portable batch/job/stage/invocation/publication traces/metrics. Start with local export; collector/backend optional, no mandatory service. Redact/retain payloads appropriately. Sampled/dropped telemetry cannot replace authoritative DB outcomes/costs. |
| **Langfuse: optional** | Calls, prompts, evaluation datasets/feedback. Core **MIT**; designated enterprise directories differ. Current **v4** Compose: web, worker, ClickHouse, Redis, PostgreSQL, S3 storage. Existing DB/storage may be reused after isolation/compatibility checks; ClickHouse/Redis/processes remain. Do not mandate this stack. |
| **Phoenix: reject as default permissive OSS** | Local/self-hosted tracing/evaluations/datasets, OpenTelemetry/OpenInference. Server: **Elastic License 2.0**, restricting hosted/managed provision of substantial functionality. Source availability is not permissive OSS. Internal experiments require intended-use checks; do not promise a rehosted UI. |
| **Label Studio: optional isolated gold-set tool** | **Apache-2.0** Community image/text labeling, preannotations/import/export; Docker/SQLite locally, PostgreSQL at scale. Official comparison excludes workspace/project RBAC and role-based review. A shared Community instance is not our security boundary. Export approved cohorts; import reviewer/schema/source IDs. Adjudication/taxonomy publication remain ours. |
| **Argilla: defer pending feedback volume** | **Apache-2.0** questions/responses, human-feedback datasets/model-output review. Official Compose adds server, worker, PostgreSQL, Elasticsearch, Redis. Useful curated feedback; duplicate dataset/permission/search infrastructure is costly initially. Requires access-safe export, revision mapping/adjudication. |
| **SKOS: adopt concepts; optional export** | W3C concepts, preferred/alternative labels, definitions/examples, broader/narrower relations/mappings. Standard, not taxonomy service; relational storage needs no RDF DB. Custom release history, merge/split lineage, evidence, approval/reassignment. `exactMatch` cannot represent every merge/split. |

Export minimal trace metadata/evidence references, not repeated private screenshots/prompts. External prompt versions resolve to immutable recipes; updates cannot alter running batches. Annotation judgments are neither automatically verified truth nor published taxonomy releases.

Sources: [OpenTelemetry Python](https://github.com/open-telemetry/opentelemetry-python); [Langfuse](https://github.com/langfuse/langfuse), [license](https://github.com/langfuse/langfuse/blob/main/LICENSE), [Compose](https://github.com/langfuse/langfuse/blob/main/docker-compose.yml); [Phoenix license](https://github.com/Arize-ai/phoenix/blob/main/LICENSE); [Label Studio](https://github.com/HumanSignal/label-studio), [edition limits](https://labelstud.io/guide/label_studio_compare); [Argilla](https://github.com/argilla-io/argilla), [Compose](https://github.com/argilla-io/argilla/blob/main/examples/deployments/docker/docker-compose.yaml); [SKOS](https://www.w3.org/TR/skos-reference/).

## Execution boundaries

| Choice | Fit and limits |
|---|---|
| **Existing runtime: adopt packaging/development** | Moby engine **Apache-2.0**; Docker Desktop/product terms separate. Per-job workspaces, bounded CPU/memory/time, minimal mounts, restricted credentials/network. No app DB credentials/Docker socket for coding agents. Shared-kernel containers do not establish hostile-workload isolation. |
| **gVisor: optional Linux pool** | **Apache-2.0** `runsc`, OCI/Docker/Kubernetes integration, reduced host-kernel exposure. Test actual toolchain compatibility/performance; syscall support is incomplete. Neither nested OSWorld KVM compatibility nor native macOS support is assumed. |
| **Firecracker: defer/reject initially** | **Apache-2.0** Linux/KVM microVMs; needs host hardening, guest images, networking, storage/lifecycle orchestration. Not a drop-in desktop VM/Mac Compose service; revisit for substantial untrusted multi-tenant execution. |

LiteLLM agent loops and ACP/native review sessions share approved read-only step/frame/render helpers. Deny desktop actions, arbitrary shell/network/write tools and ambient hooks; trusted serializers validate/persist YAML. Benchmark execution has separate task tools/sandbox. ACP permissions, `--cwd` and wrappers are not OS boundaries. Offline use requires prefetched images/models and blocked egress; local clients of hosted models still use networks.

Sources: [Moby license](https://github.com/moby/moby/blob/master/LICENSE); [gVisor](https://github.com/google/gvisor), [compatibility](https://gvisor.dev/docs/user_guide/compatibility/); [Firecracker](https://github.com/firecracker-microvm/firecracker), [host requirements](https://github.com/firecracker-microvm/firecracker/blob/main/docs/prod-host-setup.md).

## Integration gates and custom responsibilities

Before adoption, verify:

1. License/transitive dependencies; reproducibly pinned installation.
2. Supported offline/auth paths without borrowed user tokens.
3. Artifact/event/score fidelity against fixtures.
4. Cancellation, restart, quota/retry interaction.
5. Batch access/redaction.
6. Measured resource cost/usefulness. No integration/speed claim has passed these gates.

Celery/RabbitMQ use the application's retry/quota ledger. acpx queuing, Harbor concurrency and LiteLLM retries/fallbacks cannot multiply attempts or bypass spend limits. Persist actual component/provider versions, routes, usage availability, errors/provenance; missing CLI tokens/cost is **unknown**, not zero.

Custom work: source adapters; shared deterministic compact/render/expand helpers; bounded sessions/checkpoints; validated YAML; batch admission/version selection; scoped API grants; evidence/recovery validation; taxonomy discovery/review; audit/query contracts; synchronized timeline; human benchmark. Reuse YAML parsing/schema libraries; evidence schemas, permission checks and no-loss compaction remain ours.
