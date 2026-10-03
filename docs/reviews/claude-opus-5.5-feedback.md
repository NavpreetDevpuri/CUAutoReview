# Independent Claude Code review

Capture note from CUAutoReview: the final CLI result starts mid-overview after an automatic continuation. The returned text below is preserved; see [scope and usage](README.md) and [verified follow-up](claude-audit-actions.md).

## Captured response

  - 95 automated tests plus two follow-ups
  - fresh Docker seeding
  - real PostgreSQL/RabbitMQ/SeaweedFS checks
  - browser layouts at 320 to 1280px
  - Gemini image transport against a fake provider
- **Unverified:**
  - diagnosis accuracy and recovery precision
  - taxonomy coherence at scale
  - throughput and cost beyond 9 visual reviews
  - Codex image transport
  - production HA

**Strongest decisions**
- **Explain before classifying.** Per-step records and episodes are saved before labels, so taxonomy changes reuse observations.
- **Separate dimensions.** Recovery, outcome contribution and failure mode are independent. Failure prevalence stays failed-only with explicit denominators.
- **Visual provenance.** Source, supplied, omitted and cited frames are recorded separately, and a citation is treated as a model claim.
- **Taxonomy history.** Releases are immutable and adoption is explicit. Approval binds the exact candidate, base and evidence.
- **PostgreSQL holds authority.** Outbox, leases and fenced publication give one authoritative result, with the repeat-billing risk stated honestly.
- **Honest caveats.** "Completed" is not "correct", and pass is not error-free.

## Prioritized gaps

| # | Severity | Evidence / path | Impact | Smallest useful fix |
|---|---|---|---|---|
| 1 | High | No human adjudication. `platform/LIVE-RESULTS.md` records unsupported recovery and dialog claims. `specs/04` 300-rollout plan not started. The POC Sol run has 48 of 69 steps marked insufficient evidence. | The brief's "defensible explanations" criterion rests on design intent only. | Two people adjudicate the 9 visual reviews step by step. Report supported-claim rate, onset localization and recovery precision. |
| 2 | High | Contradictions across documents:<br>• `specs/04` and `specs/08` say 21 tests; current count is 95.<br>• `specs/02` and `specs/08` say five transient attempts; `CONTRACT.md` says four total.<br>• README says Claude review is blocked by a missing key.<br>• `platform/README.md` both says seed does and does not import the 8 tasks. | Reviewers cannot tell current fact from stale target. | Add one dated status table to `docs/SUBMISSION.md`. Mark the retry count as design 5 versus implemented 4. Delete stale counts. |
| 3 | High | The trajectory and mobile screenshots show identical "Problem 2" cards from Reviews 1, 3 and 4. Problem numbers are review-local but look shared. Text-only and visual reviews are mixed under "All current revision reviews · 4". | Implies consensus and visual grounding that may not exist. The text-only Gemini review inferred clicks with no UI observations. | Group cards by label, for example "Flagged by 3 of 4 reviews". Show run name and a modality badge ("Text only" or "Screenshots supplied"). Default to one review. |
| 4 | Medium | The `specs/04` cost headline ($147.60/day) is a superseded failed-only estimate that excludes 60% passing reviews. The measured sample is $0.028 to $0.035 per task. | The scale/cost answer uses weaker numbers than the repo already has. | Add a row: 10k/day is roughly $280 to $350/day of inference, based on a 9-review sample. Add a curator-hours estimate. |
| 5 | Medium | Every live step reports `reviewed`, including text-only steps (`LIVE-RESULTS.md`). The design requires recording the evidence actually inspected. | Coverage metrics overstate visual review. | Add per-step `evidence_modalities` and count it in `coverage_summary` and in the viewer. |
| 6 | Medium | Evolution is exercised only up to one approved draft; no merge, split or reclassification has run. The live label "Repeated mis-targeted UI activation" breaks the repo's own plain-language naming rule. | The brief's evolution topic is untested beyond approval. | On the 8-task drafts, run one merge and one split end to end. Show counts under both releases, and rename the noun-pile label. |

## UX observations from the screenshots

**Hierarchy and identity**
- The Overview shows 15 datasets, 25 runs and 66 tasks, but the demo is 3 datasets with 8 tasks. It is unclear whether archived fixtures are counted.
- The Runtime card shows "Not Reported" twice, which undercuts the verified-queue claim.
- Recent activity lists only `auth.login` events, which is low-value information.
- Run names are machine timestamps, such as "…remaining 20260927T051345Z". Show model, scope and modality first, with the timestamp secondary.
- "Finished With Errors" uses title case while the docs use sentence case.

**Definitions and readability**
- The dataset card shows "3 problem flags · 11 flagged steps · 2 labels". "Flagged steps" exceeds "problem flags" with no visible definition.
- "2 latest saved assessments" is ambiguous.
- There is a pluralization bug: "1 labels".
- The explicit-definition preference is not met on this card. Add a one-line legend.

**Repetition**
- Step 7 spends about 300px on three near-identical cards.
- On mobile at 390px, Step 2 alone fills about 80% of the viewport with four repeated cards. Grouping, as in gap 3, fixes both.

**Evidence versus model claims**
- Flags do not visibly say "model assessment", even though `UX-FEEDBACK.md` claims they do.
- Beside the screenshot, "Recorded intent" and "Observation" both read "Not recorded", yet model flags assert mis-targeting. Put supplied and cited frame status next to each flag.
- Fine screenshot detail is unreadable at card size. The "Open screenshot at full size" link is good.

**Links and hover**
- Whole-card links cannot be verified from static images.
- The collapsed left rail is icon-only with no visible labels, so its meaning likely depends on hover tooltips. This conflicts with the no-hover preference. Show labels or use an expanded default.
- The theme toggle has an `aria-label`, which is fine.

**Compactness**
- The 14px body and aligned `StepFlag` grid read professionally.
- The `64px` "Problem N" column with raw "Review 1" rows spends space on opaque identifiers.

## Recommended sequence

1. Fix the document contradictions and add the status table (gap 2). This is hours of work.
2. Group viewer cards and add modality badges (gaps 3 and 5).
3. Run human adjudication on the 8 tasks (gap 1). Publish results even if unfavorable.
4. Replace the stale cost headline with the measured sample and curator hours (gap 4).
5. Run one merge/split and reclassification exercise (gap 6).
6. Only then expand features such as discovery, adapters or the helper loop.

## Review limitations

- Most backend code, tests and interactions were not supplied or run. Documented gaps are not proof of runtime bugs.
- UX findings come from five static screenshots and three frontend files. Keyboard focus, whole-card links and dark/light contrast were not exercised.
- Cost and accuracy figures are the repository's own estimates, not invoices or independent measurements.
- This is a separate design audit, not a trajectory review, and Claude is not a platform adapter here.
