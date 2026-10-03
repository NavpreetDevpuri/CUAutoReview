# Small human validation pass

**Status: not started.** Use the nine saved visual reviews over eight distinct tasks from [live results](../platform/LIVE-RESULTS.md). This is a practical first check before the broader [evaluation plan](../specs/04-evaluation-and-delivery.md), not a representative benchmark.

- Two people independently inspect source actions, screenshot pixels and the saved claims. Hide reviewer-model identity for the first pass. Preserve disagreements, then record adjudication separately.
- Pin source revision, review-result ID and taxonomy release. The two model reviews of the same task are a matched pair, not independent tasks.
- Include every claimed problem/recovery and every source step, including passing and unflagged steps. Missing source evidence stays unresolved.

Copy one row per claim or independently found missed episode:

| Review / source revision | Step(s) / problem | Claim or missed episode | Source evidence | Reviewer A | Reviewer B | Adjudication / reason |
|---|---|---|---|---|---|---|
| Pending | Pending | Pending | Frame/log IDs | Supported / unsupported / unresolved | Supported / unsupported / unresolved | Pending |

Record expected first-observed step(s), label fit, recovery status and repair steps separately. A successful benchmark grade or changed action alone does not demonstrate recovery.

| Measure | Report |
|---|---|
| Claim support | Supported / all assessed claims, with unsupported and unresolved counts alongside. Also show support among resolvable claims. |
| Missed problems | Matched episodes / all independently annotated episodes; report missed and disputed episodes. |
| Localization | Exact first-observed matches / matched resolvable episodes; report absolute step distance and unresolved anchors. |
| Recovery precision | Confirmed repairs / all claimed recoveries; report disproved and unresolved claims separately. |
| Clean passing traces | False flags and missed recovered mistakes, separate from failed-task diagnosis. |
| Effort and agreement | Minutes per source/review, A/B disagreement counts and unresolved adjudications. |

Report raw counts per task, model and evidence coverage. Nine reviews cannot validate rare failures, production rates or broad model rankings. Feedback appends to saved records; it never rewrites the original diagnoses.
