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

## What was built and checked

- The POC tested parallel reviewers, shared draft proposals and final consolidation before platform expansion. The local platform implements datasets/runs, team access, ZIP validation, review history, analytics/comparison, taxonomy approval and a responsive evidence viewer. Saved replay needs no model calls.
- [Validation evidence](../platform/TEST-RESULTS.md): 95 automated tests, two focused follow-up tests, real PostgreSQL/RabbitMQ/S3-compatible checks, frontend builds and browser checks at 320, 390, 768 and 1280px.
- [Docker-only setup](../platform/docker-quickstart-verification.json) passed on a fresh ARM64 stack: five logins, three teams, eight distinct tasks, screenshot access and repeat-seed stability, without model calls.
- [Live checks](../platform/LIVE-RESULTS.md): eight Gemini 3.8 Flash visual reviews plus one matched GPT-6 Sol review completed across eleven attempts. Their token-based cost estimate is **$0.3671**, including failed attempts; invoices are unverified and this is not total historical spend. Completion means a valid review was saved, not a correct diagnosis.

## Remaining limits

Two Writer sources retain only three screenshots for fifteen steps. Human adjudication, broader accuracy evaluation and recovery precision remain open. Continuous S3 discovery, the extended helper-agent loop, automatic post-run curation, additional adapters, production HA, load testing and security hardening remain design targets. Next steps are a task-separated, independently reviewed evaluation set and measured cost/quality/capacity tests before production claims.
