# Sol rerun and clearer step labels

**All five tasks completed with GPT-5.6 Sol.** The viewer now has task and step selection in a minimizable sidebar, full-width screenshots with explanations below, and direct step links. [Earlier Luna results](RESULTS.md) remain intact.

## Run and comparison

| Measure | Luna baseline | Sol rerun |
|---|---:|---:|
| Run | `20260926-224411-20aa4` | [20260926-225934-c522c](../runs/20260926-225934-c522c/run.json) |
| Model / reasoning | GPT-5.6 Luna / low | GPT-5.6 Sol / medium |
| Completed reviews / actions | 5 / 69 | 5 / 69 |
| Supplied screenshots | 15 | 15 |
| Step status: reviewed / insufficient evidence | 15 / 54 | 21 / 48 |
| Proposals / canonical draft labels | 6 / 5 | 8 / 8 |
| Wall time | 113.4 seconds | 211.7 seconds |
| Input tokens, including cached | 376,576 | 460,025 |
| Cached input subset | 259,072 | 340,608 |
| Output tokens | 9,455 | 18,500 |
| API-equivalent cost | $0.040028 | $0.983911 |

- Run artifacts record byte-identical task inputs, matching prompt hashes and image selection; model **and reasoning effort** changed. Session limits changed from 180 to 300 seconds, though actual reviews took 50 to 111 seconds. This is an exploratory comparison, not a controlled quality benchmark.
- Current prompt files include later naming guidance. Each historical run retains its own prompt copies and hash manifest, so the Luna/Sol outputs and recorded hashes are unchanged.
- Sol identifies 11 episodes. Reviewers reuse two shared labels across multiple tasks; eight distinct proposals remain after consolidation. The consolidator explicitly preserves uncertain distinctions instead of forcing a merge.
- Candidate `0.1.0-draft` belongs to this run, remains pending human review and does not replace the earlier candidate or publish a release.

## What changed in the diagnoses

- **GIMP:** recovery now includes steps **7, 8 and 9**, capturing the keyboard shortcut omitted from Luna's recovery list. Final layer visibility supports success; the shortcut's immediate effect is still unobserved.
- **Writer table:** Sol distinguishes early menu targeting, numeric entry into the wrong field, and the final unconfirmed dialog.
  - It records **75 → 7** as recovery from the column error, while rows remaining at 2 and missing confirmation form a separate unresolved episode.
  - This avoids Luna's incorrect “75 from an existing 2” description. The exact focus cause remains an inference.
- **Chrome:** separates visible network blockage, malformed command entry and the final mismatch between displayed weather and a monthly forecast. Attribution to final failure remains uncertain.
- **Writer footer:** separates menu targeting from selecting unrelated commands; dialog dismissal is partial recovery, not proof of page-number insertion.
- These distinctions are more explicit, but are **not independently adjudicated**. All six additional steps marked reviewed are in the Writer table task, reflecting a different interpretation of sparse evidence. This does not establish better accuracy. Forty-eight steps still lack sufficient evidence.

## Cost and availability

- A new GPT-6 Sol probe again returned “not supported when using Codex with a ChatGPT account.” GPT-5.6 Sol passed a small preflight and completed six sessions, including consolidation. No automatic retry was used.
- [Official API rates](https://developers.openai.com/api/docs/pricing), checked 26 September 2026: GPT-5.6 Sol **$4 input, $0.40 cached input, $20 output per million tokens**. Successful preflight adds **$0.016308**, making this follow-up **$1.000219 API-equivalent**.
- Estimated run usage: **24.59778 Codex credits**, at [100 / 10 / 500 credits per million tokens](https://learn.chatgpt.com/docs/pricing#token-rates). Actual ChatGPT allowance/charges are unavailable. API comparisons exclude unreported cache-write charges; rejected probes have no usage report.
- The successful five-task Sol run alone is $0.983911 API-equivalent: $0.924195 across five reviewer sessions and $0.059716 for the separate final consolidator. Its average is $0.196782 per task after spreading that one consolidation across five tasks. Formula: `((input_tokens - cached_input_tokens) × $4 + cached_input_tokens × $0.40 + output_tokens × $20) / 1,000,000`. Cached tokens are a subset of input tokens.
- The 1,000- and 10,000-task scenarios in the [POC README](../README.md#measured-cost-and-scaling-scenarios) multiply the measured five-task average while retaining its workload, cache share and one consolidation per five tasks. These are simple planning extrapolations, not a guaranteed upper bound, capacity or accuracy forecast. Five sparse tasks, including only one pass, do not show that passing review is cheaper. Infrastructure, human review, retries, unreported cache-write charges, provider changes and larger-context effects are excluded.
- Compared with the sparse Luna baseline, Sol costs more and provides finer distinctions in these examples. The next quality gain may require additional screenshots and human adjudication, not only a different model.
- All five outputs pass the same schema/reference checks. The 18 reviewer helper calls were ten label reads and eight proposals; no shell, browser, computer or checker execution appears in the logs.

## Reading labels in the viewer

- Numbered problems keep the same task-local number across onset, related and recovery groups. Version 2 uses explicit `first_observed_step_id` and the labels **First observed here** / **Also observed here**; legacy runs use the earliest explicit `onset_step_ids` in source order and **First flagged here** / **Also flagged here**. The first-anchor link is shown on every related/recovery group, with no inferred interval.
- The selected step shows its mechanism, recovery rationale, uncertainty and jump links. Unlinked or insufficient-evidence steps are not described as failure-free. Step role, failure category and recovery remain separate.
- Task selection shares a minimizable sidebar with step selection. Headings scroll away; the screenshot uses the full content width and its explanations appear below.
- Display names simplify recorded taxonomy names; definitions retain the pinned taxonomy text. Definitions are always visible inline, with consistently colored category chips and IDs. A **Recorded label** disclosure preserves the original name and ID. The earlier hover/focus tooltip treatment was a prototype and is superseded by this inline-only requirement.
- Multiple problems on one step are grouped and numbered, with independent step roles and counts based on linked problems. Compact summaries jump to separate episode cards. Existing onset, recovery and `step.episode_refs` links remain explicit; intermediate mistake steps are not inferred.
- Usage details can be expanded separately; source/model outputs from earlier runs remain unchanged.
- Latest browser checks: Chrome step 15 shows two distinct problem groups in the sidebar, summary and explanation cards; the explanation jump focuses the right card; no label-popup elements remain; next/previous preserves alignment; no horizontal overflow or console errors were recorded. The Problem 2 summary jumps from step 15 to its first flag at step 10; repeated flags keep that number. The “Screen ↑” shortcut returns from Problem 3’s explanation to the unchanged selected step. The feedback document returns HTTP 200. Version 2 contract tests pass, including related links alongside another problem’s onset and all ten saved Luna/Sol reviews. Version 2 has not been exercised in a new hosted review; this UX update reused saved outputs without a reviewer rerun.

See the [viewer feedback log](VIEWER-FEEDBACK.md) for the suggestions and reasons behind these changes. Historical run outputs and hashes remain unchanged.

Local files only; no Git commit, PR or deployment. Source/model outputs from earlier runs are preserved.
