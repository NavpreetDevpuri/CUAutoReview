# 10. APIs, CLI harnesses, authentication and trajectories

**Implementation status:** The bounded LiteLLM model API and native Codex 0.157.0 and Gemini CLI 0.61.0 adapters run in an isolated CLI worker. A loopback fake-provider check, with outbound networking disabled, confirmed that Gemini CLI expands an explicitly named PNG into image bytes and forwards structured JSON settings ([script](../platform/scripts/check_cli_image_transport.py), [captured result](../platform/demo-data/cli-image-transport-verification-20260927.json)). This is transport evidence only, not a live vision review or a quality result. Historical provider reviews remain text-only. Hosted inference is off by default. The current environment has no `ANTHROPIC_API_KEY`, so no Claude review or spend occurred; the Docker image does not include the Claude CLI. ACP is not wired into the local platform. Jev is separately disabled after an HTTP 403 balance check. None of these statements establishes live model quality or billing behavior. The remaining sections describe design targets and adoption checks.

**Research checked 26 September 2026.** Adapter documentation is not integration, login, billing or security validation. Recheck versions, entitlement and terms before broader deployment.

## Reuse three distinct layers

| Layer | Responsibility and boundary |
|---|---|
| Model API | In-process LiteLLM in our bounded review loop; native adapter for unsupported capabilities/Jev. Controller owns context/checkpoints/helpers; neither CLI sessions nor desktop benchmarks. |
| Agent harness | ACP + acpx headless-client candidate, native SDK/CLI fallback. Versioned session/tool-event/permission adapters; capabilities/auth differ by agent. |
| Benchmark runner | Optional Harbor OSWorld/native OSWorld: environment, desktop agent, task/evaluator. Import scored traces first; coding CLIs are not automatically desktop agents. |

- Harbor excludes eight login-dependent tasks by default (**361/369**), requires Linux KVM/nested VM and does not support dropping standard Codex/Claude CLIs into that desktop. macOS Compose can import without running the VM.
- Harbor/ATIF/ACP reduce code, not all conversion losses. [Research/licenses/sources](09-open-source-reuse.md).

## Backend and route contracts

- Pin `backend_kind`, provider/model, binary/SDK/adapter, prompt/schema, capabilities, permissions, credential binding, budgets and fallback.
  - Interface: `preflight → submit → stream/status → cancel → typed result`.
  - Persist session/invocation IDs, raw events, resolved versions, termination, conversion losses, usage/latency. Missing cost/model metadata is `unknown`, never zero or an assumed configured name. Fallback must be versioned, logged and evaluated.

| Stage | Execution rule |
|---|---|
| Discover/normalize | Deterministic schemas/adapters; known formats need no LLM. Mapping assistance requires separate review. |
| Trajectory review/verification | Bounded API or native CLI request with validated step output and selected evidence. Gemini CLI image transport is locally verified; visual interpretation and review quality still require live, human-adjudicated checks. Claude Code remains text-only in this build. |
| Assign modes | Structured API/optional Jev reads pinned released candidates; compare harness startup/tool-loop cost. Zero episodes: `classification_status=not_applicable`, reason `no_episodes`, no classifier job/assignment. Keep partial/inconclusive/abstained review status. |
| Curate/feedback | Separate asynchronous recipe; harness/API drafts definitions/diffs, never approves/publishes. |
| Execute rollout | Compatible external runner/evaluator in a separate sandbox; task tools enabled only here. Both passed/failed results re-enter import/review. |

- **Both routes default on:** `failure_analysis` for failed grades; `pass_recovery` for passed/full-score grades; unknown/error defer. Each pins its own prompt/reviewer recipe/session/budget, using the same sequential agent/helpers/YAML/recovery contract.
  - Pass review scans every compact step for mistakes and evidence-linked corrections, expanding/escalating uncertainty within its route. Preserve pass grade; success alone proves no recovery. Pass contribution is `not_applicable`; failure contribution stays `contributing/noncontributing/uncertain`.
  - Old batches adopt through explicit scoped/budgeted successor runs. Rescoring appends the evaluation and selects its new route, preserving history.
- Review, assignment and curation can share models but have separate jobs/schemas/sessions/budgets. Cross-model checks are optional; agreement is no independent proof; stage support requires a tested capability matrix.
- One logical context spans ordered steps, possibly many calls. API controller retains checkpoints; harness restart restores validated context, not hidden state. Helpers read/render ranges/frames or expand omissions. Bound context and expose partial coverage.
- Every invocation, including resume/output/compaction, needs concurrency/request/token/spend admission against provider, workspace and remaining trajectory limits. Separate failure/pass pools cannot starve either route.
  - A CLI must expose/mediate requests **before dispatch** and account for usage; a final session total cannot enforce per-call quotas. Unsupported control/auth paths use the controlled API backend, never claim opaque sessions have equivalent guarantees.
- Restricted validated YAML holds authored indexes/presets/taxonomy/reviews; preserve native JSON/JSONL and JSON transport. Prefer structured provider output, then validate/serialize; raw YAML has identical safe-parser/schema/repair limits. Trusted serialization writes artifacts, not arbitrary agent filesystem tools. [Exact contracts](02-data-and-contracts.md).

## Authentication and containers

Approved API keys/workload identities are the unattended default; no browser login is needed. Each call receives only its required binding. Eligible subscription login is provider-specific, not generic API credit or unlimited shared capacity.

- **Codex:** `codex exec --json` emits JSONL; `--output-schema` constrains final output. Official TS SDK and Python app-server SDK exist.
  - Use invocation-scoped `CODEX_API_KEY` for exec or documented Platform key login/SDK configuration. OpenAI recommends keys for programmatic use.
  - ChatGPT login/device auth and eligible workspace access tokens exist; managed-account automation has extra restrictions. Verify eligibility and use trusted private runners.
- **Claude Code:** `claude -p`, JSON/stream-json, `--json-schema`; official Agent SDK. Use `ANTHROPIC_API_KEY` or supported cloud credentials.
  - Native CLI supports subscription login/setup-token. Third-party apps/Agent SDK use API/cloud auth; never collect/route Claude.ai subscription tokens through this product.
  - Hosting an unmodified native binary with its user's sign-in is a different integration requiring supported auth. ACP's Claude adapter uses Agent SDK, so native subscription behavior does not transfer. Proprietary binary/service terms can coexist with MIT/Apache adapters.
- **Gemini CLI:** `-p` with `--output-format json` or `stream-json`; `GEMINI_API_KEY` or supported Vertex/Google Cloud identity with explicit project/location.
  - Cached auth is documented, but the dated announcement ended free/Google AI Pro/Ultra service on **18 June 2026**. Paid API-key/eligible enterprise access remains; old “Sign in with Google” instructions are not a guarantee.
- **Raw APIs/local server:** request/response or streaming adapter; provider key, workload identity or explicit local auth. Consumer UI login is not portable API authentication. Record the local model's actual identity/capabilities.
- **Secrets:** Docker secret files/dedicated store; trusted launcher creates invocation-scoped variables only when required. Never place secrets in images, arguments, prompts, jobs, exports or logs; no whole-home/login mount. Containers inherit no host login.
  - Eligible native login uses a restricted credential volume/documented refresh, never product-UI credential collection. Prefer short-lived production workload identities. Credential owner pays API charges.
- **Preflight:** report backend/version/capability, credential owner/scope/auth, entitlement and expiry/refresh health without secrets. An authorized connectivity test can incur a tiny call; none ran here.
  - Revocation/401/403 → `blocked_auth`/`blocked_entitlement` for admin repair. 429 → bounded retry/backpressure. Quotas span keys/sessions/replicas; auth changes do not replay completed work.

## Preserve comparable evidence

Keep original streams and normalize an event envelope, not a universal reasoning format:

| Fields | Preserve |
|---|---|
| Identity | Attempt/event/sequence, source clock/uncertainty, harness/model/task/environment versions, original object/pointer |
| Actor/event | Agent/user/tool/environment/evaluator; observation, visible intent/message, action request/receipt/effect, final claim/grade |
| Action/observation | Exact tool/arguments, status/output, frame and before/after alignment; explicit omissions |
| Context/output | Task constraints, visible rationale, final artifact/checks, termination/usage, partial-stream/conversion-loss flags |

- Compare **task → visible intent → action → effect → grade**, with citations:
  - “I will save” then Cancel: possible intent/action mismatch if timing is sound.
  - “I will delete this needed record” then successful deletion: wrong plan correctly executed.
  - Save plus confirmed server error: possible tool/environment failure.
  - Success claim while required state is absent: possible verification failure.
- Missing frames/intent or ambiguous targets leave mechanisms unresolved; these comparisons are not mandatory taxonomy labels. [Analysis rules](01-system-design.md).
- Use exposed summaries/messages only; never request/reconstruct hidden reasoning. Text does not prove execution; CLI exit does not prove task success. Correct artifact plus failed grade warrants evaluator review. Recovery does not automatically identify final cause. Keep original-agent and reviewer-harness traces separate.

## Isolation and adoption gates

- Controlled directory, approved read-only step/range/frame/render helpers, per-trajectory authorization/size limits. Disable ambient instructions/hooks/plugins/MCP and generic shell/network/write/desktop tools; explicitly configured evidence helpers are the only exception.
  - Enforce through controller/adapter **and** process/container restrictions, not prompts. Claude bare mode can retain built-ins; read-only Codex filesystem mode is insufficient. If unenforceable, use the controlled API agent. Separate trusted credentials/serialization from untrusted parsing/task execution; no Docker socket or whole-home mount.
- Before adoption, test auth/expiry, images, YAML/typed output, partial streams, helper allowlist, checkpoint restoration, cancellation/subprocess cleanup, per-call/session caps, duplicate delivery and provenance. Pin/preinstall dependencies; no runtime `npx latest`.
- Compare whole-trajectory latency, step/recovery quality and total billing across API/harness and both review routes. ACP support alone proves nothing. Offline fixtures cannot call hosted APIs/CLIs; real offline inference needs a compatible local model.

## Checked primary sources

- OpenAI: [auth](https://developers.openai.com/codex/auth), [noninteractive execution](https://developers.openai.com/codex/noninteractive), [SDKs](https://developers.openai.com/codex/sdk).
- Anthropic: [auth](https://code.claude.com/docs/en/authentication), [headless execution](https://code.claude.com/docs/en/headless), [tool controls](https://code.claude.com/docs/en/cli-reference), [license/credential rules](https://code.claude.com/docs/en/legal-and-compliance).
- Google: [auth](https://geminicli.com/docs/get-started/authentication/), [headless events](https://geminicli.com/docs/cli/headless/), [dated consumer transition/API/enterprise announcement](https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli). Auth docs retain older guidance beside a transition banner; the dated announcement governs that limitation.
