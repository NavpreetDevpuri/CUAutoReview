# CUAutoReview: submission summary

Repository: [github.com/NavpreetDevpuri/CUAutoReview](https://github.com/NavpreetDevpuri/CUAutoReview)

CUAutoReview explains where computer-use agents make mistakes, whether they recover, and which failure patterns recur. The assignment deliverable is the [system design](../README.md). A preserved [five-task POC](../poc/README.md) and [working local platform](../platform/README.md) provide supporting experiments, not proof of production readiness.

## Assumptions and approach

- **OSWorld-Verified is the initial source, not a requirement.** Public scored trajectories give concrete examples; replaceable adapters preserve other input formats. Historical evaluator versions are not always known. A recorded pass is not an error-free trajectory, and an evaluator score is not a human diagnosis.
- **Explain before classifying.** One logical reviewer follows a trajectory, linking task intent, actions, visible effects and evidence into numbered problem episodes. Failed attempts receive failure analysis; passing attempts receive a separate recovery-review prompt. Recovery, severity and contribution to the final outcome remain separate from failure labels.
- **Preserve uncertainty.** Every step has an assessment and evidence references. Source screenshots, images actually supplied to the model and model citations are separate facts. Missing evidence permits an inconclusive result; an action comment or citation does not prove a visual effect.

## Main decisions and trade-offs

- **Keep large evidence in object storage and queryable state in PostgreSQL.** Tasks, rollout/source revisions, run membership, steps, episodes, label assignments and review attempts retain provenance. Versioned presets and taxonomy releases make comparisons reproducible. Validated YAML makes review artifacts readable; native JSON, logs and images remain intact.
- **Use RabbitMQ/Celery for delivery, PostgreSQL for authority.** A transactional outbox, idempotent claims, leases and fenced completion tolerate duplicate delivery. Retryable processing failures retain attempt/error/cost history; the implementation allows three retries. This adds infrastructure compared with a PostgreSQL queue, which remains a credible smaller deployment option. External model calls can still be charged again after a crash.
- **Separate analysis, label assignment and taxonomy curation.** Reviewers propose evidence-linked labels; consolidation suggests merges or revised definitions. Human approval publishes an exact immutable candidate. Existing reviews keep their original release; reclassification is explicit. This protects historical trends but adds curation work and possible backfill cost.
- **Reuse existing components.** FastAPI, React-admin/MUI, LiteLLM, native Codex/Gemini CLIs and SeaweedFS reduce custom infrastructure. The local S3-compatible endpoint is configurable; switching to AWS still requires IAM, migration and compatibility checks.
- **Scale trajectories, not individual steps.** Bounded concurrency and evidence selection control cost and latency. The design adds shared provider quotas, fair live/backfill scheduling, reconciliation and staged storage/query scaling. Its illustrative 10,000-trajectories/day scenario is not a load-test result. [Alternatives and rationale](../specs/03-decisions-and-tradeoffs.md).

## Implementation and evidence snapshot: 27 September 2026

| Area | Implemented or checked | Boundary / evidence |
|---|---|---|
| Local platform | Datasets/runs, teams/access, ZIP validation, review history, analytics/comparison, taxonomy approval, responsive viewer | One imported rollout per UI Task record; grouping K attempts under a shared task remains a design target. [Status](../platform/README.md) |
| Review workflow | Bounded trajectory requests; four attempts maximum, shared label drafts and explicit curation/approval | Automatic post-run curation and helper-agent loops remain planned. The [preserved POC](../poc/README.md) tested parallel reviewers and final consolidation; saved replay makes no model calls |
| Recorded regression baseline | 95 automated tests plus two focused follow-up tests; real PostgreSQL/RabbitMQ/S3-compatible checks; frontend build; 320/390/768/1280px browser checks | Functional checks, not load or exhaustive security testing. [Commands/results](../platform/TEST-RESULTS.md) |
| Docker setup | Fresh ARM64 stack: five logins, three teams, eight distinct tasks, screenshot access and stable repeat seeding, without model calls | AMD64 execution unverified. [Evidence](../platform/docker-quickstart-verification.json) |
| Live model checks | Eight Gemini 3.8 Flash visual reviews plus one matched GPT-6 Sol review; 11 attempts; **$0.36706550 estimated**, failed attempts included | Eight distinct trajectories; valid saved output is not a correct diagnosis. Invoices and total historical spend remain unknown. [Results](../platform/LIVE-RESULTS.md) |
| Cost/scale scenarios | Sample arithmetic: $0.040785 per saved review; **$407.85 for 10k equivalent reviews**, both routes included | Tiny heterogeneous sample, not a production forecast; excludes infrastructure, classification/curation and humans. [Assumptions and staffing formula](../specs/04-evaluation-and-delivery.md#capacity-and-cost) |

## Remaining limits

Two Writer sources retain only three screenshots for fifteen steps. Human adjudication, broader accuracy evaluation and recovery precision remain open. Continuous S3 discovery, the extended helper-agent loop, automatic post-run curation, additional adapters, production HA, load testing and security hardening remain design targets. Next steps are a task-separated, independently reviewed evaluation set and measured cost/quality/capacity tests before production claims.
