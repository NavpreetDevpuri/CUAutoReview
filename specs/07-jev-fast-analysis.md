# 7. Jev for fast analysis

**Implementation status:** The optional Jev adapter is present but disabled. A free-credit balance request returned HTTP 403; no Jev inference or spend occurred. It is not a supported route in the local platform. The design below describes a possible future integration, not measured speedup or an active fallback.

**Decision:** evaluate TypeSafe's Jev as optional fast triage/existing-mode matching. The evidence/VLM reviewer supplies explanations.

**Offline:** Jev stays disabled. Labeled fixtures test plumbing; explicitly selected local inference uses a different model, not local Jev. Fallbacks follow the same network policy without silent hosted calls. [Deployment profiles](08-local-deployment-and-queue.md).

## Verified capabilities: 26 September 2026

The [model card](https://docs.typesafe.ai/models) documents hosted, **text-only `jev-1.13.0`**: text/structured JSON accepted; screenshots/video/audio unsupported.

| Interface | Output / limit |
|---|---|
| `Choice` | One predefined option, distribution/confidence; up to **255** options. |
| `Score` | Probability-weighted score over **2–10** ordered rubric levels, with distribution/confidence. |
| `Noul` | “Yes” probability **0–1**, not Boolean or separate confidence. |

- No free-form causal explanations. Confidence is a distribution statistic, not measured diagnostic accuracy.
- Caps: **64k** total request tokens; **32k** for state plus longest question. Normalize/select multi-MB traces first.
- [API](https://docs.typesafe.ai/api): `POST https://api.typesafe.ai/v1/systemone`; bearer auth; `model`, `state`, `questions`; response includes resolved model and token usage. Pin `jev-1.13.0`; `jev-latest`/`jev-preview` can move. Independent questions may share one request/state; their answers cannot depend on each other.
- Official [Python](https://github.com/typesafe-ai/typesafe-sdk-python) `typesafe-sdk` and [JS](https://github.com/typesafe-ai/typesafe-sdk-js) `@typesafe-ai/sdk` are **MIT**. No official weights/self-hosting distribution verified. Benchmark openness does not make this hosted model open-source.

## Routing and boundaries

```text
Normalize + preserve evaluator grade
  → failed: failure_analysis | passed/full-score: pass_recovery
  → optional Jev triage of compact, source-linked evidence
      structured → sequential review
      needs_visual → targeted VLM expansion
      insufficient_evidence → gather/review, retaining uncertainty
  → validated step YAML + reconciled episodes
  → optional Jev existing-mode match → versioned UI result
```

Both review routes are **default**, with separate prompts, agent recipes/sessions and budgets; unknown/error grades defer. Scan all compact steps and expand visuals when needed. Passing proves neither recovery nor an error-free trajectory: require evidence of a mistake and later correction. Keep recovery attributes separate; passing episodes use `outcome_contribution=not_applicable`, outside failed prevalence. Jev is optional on either route, never an automatic grader.

Use deterministic code for missing files, explicit status codes and arithmetic. Jev handles narrow interpretation:

| Use | Decision and boundary |
|---|---|
| Inspection | `structured/needs_visual/insufficient_evidence`; never silently drop an eligible attempt. |
| Priority | Repeated unsuccessful recovery, conflicting evidence or ordinary review; separate from outcome/severity. |
| Window selection | Supplied window IDs only; retain references and audit missed early causes. |
| Existing-mode match | Retrieved definitions, `unclassified` or `ambiguous`, after evidence extraction; no invented label/cause. |

Route enums are workflow controls, not failure modes; Jev's `Score` never replaces OSWorld's score. Keep assignment separate from reviewer/curator. Validate cited episode claims and definition fit/boundaries against an immutable release. Low fit may enqueue another model/harness's curation job. Every taxonomy change, including wording, needs exact-draft human approval; feedback cannot mutate releases or silently retag batches. [Curation contract](01-system-design.md).

Build compact state from task constraints, grade, normalized actions/results, coverage and evidence IDs. Parse validated YAML; render selected intent/action/observed-UI/effect/assessment and independent recovery/contribution fields as untrusted text. Existing accessibility/OCR/VLM observations retain provenance; new visual descriptions cost time and cannot be replaced by intended effects. Jev may route early helper views or match modes after review. It is neither sequential reviewer, compactor, visual verifier nor taxonomy author; recovery is not a new failure category. Its cost excludes the trajectory agent's multi-call work.

## Real example

In the [7 × 5 table attempt](../reference/examples/README.md), step **13** intends `5` in Rows; the screenshot shows **Columns=75, Rows=2**, and later text describes correcting Columns. Jev can flag the textual inconsistency/request inspection, but cannot confirm image values. The VLM/reviewer checks state and later recovery: correcting **75→7** does not complete insertion. Cite final findings; keep routing provisional.

## Speed, price and limits

- TypeSafe [advertises **70–500 ms**](https://typesafe.ai/blog/introducing-system-one-models-and-jev) on particular structured workflows, mostly clients near US West Coast. These are provider results, not India-to-service or complete-trajectory measurements.
- Price: **$0.042/M input tokens; output free**. At **2,000 total input tokens/request**, the retained **4,000 failed-attempt/day cohort** costs **$0.336/day** for one call or **$0.672/day** for two. If enabled for **all 10,000 known-outcome attempts/day**, one/two calls cost **$0.84/day or $1.68/day**. Jev only; exclude normalization, retries, images/OCR, downstream analysis and infrastructure.
- A routing call initially adds work. Savings require avoided downstream work to outweigh it; measure provisional UI route/priority latency separately from final explanation.
- Published limits: **1,200 requests/minute**, **250k tokens/second**, subject to early-access changes. Batch independent questions; share limits across teams. Timeout/**429/529** falls back to the selected review route; record usage, never an agent failure.

## Adoption gates

1. Later add provider adapter/`jev-fast-triage`; freeze version, questions/options, preprocessing, thresholds/fallback. Disabled by default until evaluated.
2. Shadow reviewed, task-separated examples: false negatives/under-escalation, missed episodes, labels and explanation fidelity versus baseline. Current **two Writer fixtures are failures only**, useful for schema/routing checks, not accuracy/generalization. Add genuine passes with/without recovery and unresolved/ambiguous cases; none are claimed locally yet.
3. Measure **P50/P95/P99** request/queue/final latency, downstream VLM calls, throughput and cost per attempt/route in the intended region under realistic concurrency.
4. Require existing quality gates and a predeclared under-escalation tolerance; keep sparse domains conservative, calibrate confidence and retain broader-inspection audits.

Documented [weaknesses](https://docs.typesafe.ai/model-jaggedness/jev-1.13): irrelevant context, multi-hop reasoning, counting/date arithmetic and adversarial state instructions. Provider says requests/responses are not used for training; [zero retention](https://docs.typesafe.ai/legal) requires enterprise arrangements. Apply approved-data/redaction policy; standard requests are not assumed unlogged.

No SDK, weights, credentials or paid inference were installed/used for this research.
