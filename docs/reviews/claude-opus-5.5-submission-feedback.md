# Independent Claude Code review

# Second review: docs/SUBMISSION.md

## 1. Verdict

The summary is factually aligned with the specifications and unusually honest about limits. It covers the right material: YAML rationale, pinned evaluators, separate failure and pass-recovery routes, a shared proposal pool with human approval, an outbox with fencing, and cost arithmetic with caveats. Two things weaken it. Heavy slash compression and technology lists hide the reasoning, and a few phrases blur what is designed versus what is built. It needs sharper wording, not more content.

## 2. Prioritized improvements

**1. The diagram skips the states it claims to explain.** The diagram has no registration or durable-state node, no routing by outcome, and no assignment step. Its label `F -->|explicit assignment| C` also misstates the behavior: a release is adopted by a successor run, which then reassigns episodes.

Replacement nodes: `S3 + ready manifest` → `Register in PostgreSQL + outbox` → `Route by pinned evaluator outcome` → `Trajectory review (failure or pass-recovery)` → `Episodes + evidence` → `Assign to pinned release`. Relabel the final edge `adopted by successor run`.

**2. "Workspace/review features above" imports target features into the built column.** The text "above" refers to target architecture. Replace it with:

> "Imports, runs, saved replay, the trajectory viewer, analytics, shared drafts and explicit curation. The local reviewer makes one bounded call per trajectory with at most five screenshots, not the multi-step helper-agent session described above."

This keeps the measured evidence interpretable.

**3. The taxonomy bullet omits how episodes are assigned and how splits preserve history.** Both are core assignment asks. Add after "Let taxonomy emerge.":

> "A separate assignment step matches each episode to the pinned release and records assigned, ambiguous, unclassified or insufficient evidence. Similarity alone never assigns. A split leaves old episodes unresolved until they are reclassified, rather than guessing their redistribution."

**4. Slash chains and tool lists obscure the reasons behind them.** Examples:

- "task/rollout/source revisions"
- "new/rename/merge/split/deprecate"
- "Reuse FastAPI, React-admin/MUI, LiteLLM, native Codex/Gemini CLIs and SeaweedFS"

Rewrite the reuse bullet as:

> "Reuse standard web, admin, model-gateway and S3-compatible storage components so custom code goes only where no product fits: aligned steps and screenshots, numbered problems, inline definitions and approval diffs."

For the queue bullet, state why a broker was chosen:

> "A broker isolates delivery and backpressure from the database, while PostgreSQL stays the source of truth."

Keep the product names in the linked reuse spec.

**5. The scale bullet mixes throughput with reporting and never names the bottleneck.** Replace "Scale trajectories, not individual steps." with:

> "The expected bottleneck is provider rate and spend limits, not worker count. Central quotas and fair live and backfill scheduling therefore gate throughput."

Move the reporting sentence, "Separate failure prevalence...task-balanced counts", into the "Separate evidence, state and delivery" bullet, next to the trace-to-evidence claim, and state the chain there:

> "report → run → assignment → episode → step evidence"

**6. Unexplained evidence shorthand.** A technical manager cannot decode three phrases:

- "95 tests + 2 follow-ups"
- "3 grouping/evidence tests"
- "two Writer sources retain 3 screenshots/15 steps each"

Suggested replacements:

- "95 automated tests, plus two follow-up checks recorded in Verification". Name the follow-up checks if they are known.
- "3 frontend tests for problem grouping and evidence display"
- "Two Writer tasks have only 3 screenshots for 15 steps, so visual claims there stay limited."

The platform README reports five real-service ZIP checks and four batch-completion checks. Confirm that the summary's counts match.

## 3. What must stay, and limitations

**Keep these verbatim or near-verbatim:**

- "grades are not diagnoses"
- "Passing does not mean mistake-free"
- "Valid saved output is not diagnosis accuracy"
- "token savings are not assumed"
- "not measured throughput"
- "Crashes can repeat inference charges"
- "Tiny mixed sample, not a forecast/load test"
- The exact cost figures ($0.36706550, $0.040785, $407.85) with failed attempts included
- The "unverified" status of AMD64
- The Boundaries paragraph, including one rollout per Task record, `trajectory_review@1` only, and snapshotted drafts
- The overview-to-detail order, which avoids rubric headings

The OSWorld-first disclaimer and the separation of source, supplied and cited screenshots are strong. They should keep their meaning even if the slashes are expanded.

**Limitations of this review:**

- I checked the summary only against the supplied specs, contract and platform README.
- I did not inspect runtime code, TEST-RESULTS, LIVE-RESULTS or the verification JSON.
- The test counts in item 6 and the live-review figures are consistent with the README but not independently verified.
- The word counts and readability judgments are editorial, not measured.
