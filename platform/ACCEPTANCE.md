# Local platform acceptance

This is the bounded local build gate for `CONTRACT.md`. It checks end-to-end behavior with saved fixtures and the local PostgreSQL, RabbitMQ/Celery and file/S3-compatible adapters. Saved replay must be visibly identified and make no provider calls. Passing this gate does not establish production readiness, reviewer accuracy, provider billing or scale.

## Core scenarios

1. **Signup, grants and revocation.** The first account becomes workspace admin; a later account starts as viewer. The admin creates a team, adds a member and grants batch access. Verify the member's permitted reads and actions, then remove the team membership, revoke the batch grant and deactivate the account in turn. Subsequent API, evidence and export requests must deny access even if the UI is stale. Direct and team-derived access must be reflected consistently.

2. **Import, sync and frozen membership.** Import the retained task fixture and preserve its source IDs, evaluator records, evidence references and checksums. Create fixed and appendable batches from an explicit preset. Preview a new task revision, sync the appendable batch twice and confirm exactly one new member and wave. Repeating the sync creates no duplicate. The fixed batch remains unchanged. Existing members retain their selected input and result revisions.

3. **Outcome routing, saved replay and evidence links.** Search task cards by name, ID and label. Separate evaluator outcome from review availability; show recorded problems, unique explicitly flagged steps, unique recovery steps, problems grouped by label and labeled step links. Missing review data reads `Not recorded`, not zero or no issues. A saved replay must say it is replayed evidence. For a selected failed record, the route is `failure_analysis`; for a passed record, it is `pass_recovery`; unknown/error outcomes wait for resolution. Do not dispatch paid work unless explicitly requested. In the trajectory, every onset, recovery and related link resolves to a recorded step and episode; no interval is invented. Missing referenced artifacts remain missing evidence. Export and feedback enforce the same batch permissions.

4. **Job delivery, pause and unknown usage.** Start a bounded fixture batch, then deliver a duplicate and an obsolete generation for a job. They must not create a second logical result or overwrite the current revision. Pause prevents new dispatch while retaining completed work; resume continues eligible work. Exercise one bounded retry and confirm its attempt, error and cost state are visible. If a backend omits usage or cost, the value is `unknown`, never zero or an assumed configured-model price.

5. **Proposal, stale edit and publication.** Append a label proposal, feedback revision and consolidated candidate. Record the candidate's exact base release, version and hash. Approve that exact candidate and verify an immutable release is created. Change the draft or base and retry with the old approval values; publication must fail as stale. Rejection creates no release. Existing batches remain pinned to their prior release, and raw reviews and proposals remain unchanged.

6. **Artifact boundary.** Request an authorized recorded screenshot and export successfully. Request the same objects as an ungranted user, then try path traversal, an unrecorded path and an unknown evidence reference. Deny unauthorized and unrecorded paths without exposing files or constructing a guessed storage path; unknown evidence stays explicitly missing.

## Production gates, deferred

These are not claims or prerequisites for the bounded local build. Complete and document them before production use:

- **Identity and security:** SSO/MFA or approved enterprise identity, secure session and CSRF review, least-privilege service identities, secret rotation, cross-workspace isolation review and adversarial authorization testing.
- **Durability and recovery:** multi-node RabbitMQ quorum behavior, leader/majority-loss drills, outbox and commit/ACK crash-gap tests, poison/DLQ redrive procedures, PostgreSQL and object-store backup/restore, and checksum-verified migration/cutover.
- **Storage and sources:** real S3 IAM, versioning and lifecycle verification; production source adapters, credential ownership and discovery reconciliation. A local file adapter or S3-compatible endpoint is not proof of cloud S3 behavior.
- **Inference and accounting:** provider-specific auth/capability/terms, per-call limits and budget reservations, billed usage reconciliation, unknown-usage handling, retry spend caps, and any human approval policy for external data. No implicit fallback.
- **Quality and capacity:** independently adjudicated examples for both routes, recovery/localization/coverage thresholds, concurrency and burst tests, fairness and backlog age, latency/SLO and spend budgets. Five saved trajectories and a functional fixture do not establish accuracy or scale.

## Current implementation notes

- This checklist is not itself a report of passing tests. [TEST-RESULTS.md](TEST-RESULTS.md) records the 21 automated tests, 11 real-service scenario checks and 4 broker lifecycle checks, with the covered behavior and remaining limits. Treat any scenario or production gate not established there as pending.
