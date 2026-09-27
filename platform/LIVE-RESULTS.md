# Live model checks

Local checks on 27 September 2026. These are new provider calls, separate from saved replay and the original POC.

## Current visual results

- **Completed:** 8/8 distinct Gemini 3.8 Flash tasks, plus one matched GPT-6 Sol review. All three new runs are completed with zero terminal errors.
- **Evidence:** Gemini received all **84 retained screenshots across 108 source steps**. Two Writer sources retain only 3 screenshots each; missing frames were not fabricated. Codex received all nine frames for the matched task.
- **Meaning:** completed means a valid review was saved. It does not change the OSWorld score or prove the model’s diagnosis. Both models report two problems on the matched task; agreement still needs human adjudication.
- **Retries:** the Do Not Track review first cited unavailable evidence, was rejected, then passed validation on its second attempt. A canary storage failure was separately repaired and explicitly retried; its incurred cost and failed attempt remain in history.

| New visual scope | Saved reviews | Attempts | Estimated cost |
|---|---:|---:|---:|
| Gemini canary, including storage recovery | 1 | 2 | $0.04714725 |
| Remaining Gemini tasks, including one automatic retry | 7 | 8 | $0.23332425 |
| Matched GPT-6 Sol | 1 | 1 | $0.08659400 |
| **This visual check** | **9** | **11** | **$0.36706550** |

- Successful Gemini reviews alone average **$0.02787/task** in this small sample; including both unsuccessful attempts gives **$0.03506/task**. These are measured-sample projections, not general pricing guarantees. Storage, hosting and human review are excluded.
- Each job has a **$0.10 per-attempt planning allowance**, up to four total attempts. Combined planned allowance was $3.60. CLI billing is not a hard spending cap.
- Adding the earlier $0.157843 text-only check gives **$0.52490850 in accounted estimates**. Earlier setup costs remain unknown; actual invoices are unverified.
- Docker exhausted its local disk during the first canary save. Unused build cache was cleared, service volumes were preserved, and an S3 write/read check passed before retrying. The failed attempt’s $0.02373675 estimate was reconciled from its worker log with an audit event; its output-token count remains unknown.
- **Quality follow-up:** an earlier automated, text/record-based spot-check reviewed JSON review text, action records and image provenance; it did not inspect screenshot pixels. It flagged the page-number review’s inferred recovery at step 6 and dialog claims at steps 11–12, 14 and 15. In a later limited visual inspection, the step 7 frame visibly shows the Bookmark dialog. The step 15 frame shows no dialog, only the upper portion of page 1, with the status bar at page 1 of 10; that frame cannot establish whether page numbers appear elsewhere or in the footer. The step 11–12 and step 14 dialog claims remain for human adjudication. The recorded review and outcome were preserved.
- A review may analyze a text-only step without confirming its visual effect. All new step statuses happen to say `reviewed`; this must not be interpreted as complete visual coverage or calibrated confidence.

[Per-task and job evidence](demo-data/visual-review-summary-20260927.json) · [Recovered canary](demo-data/recovered-canary-b24950d9-20260927.json) · [Seven-task report](demo-data/visual-review-remaining-20260927T051345Z.json) · [Codex report](demo-data/visual-review-codex-20260927T051346Z.json) · [Writer visual-QA clarification](demo-data/writer-visual-qa-clarification-20260927.json).

[Open visual comparison](http://127.0.0.1:8000/#/compare?left=21b286f9-3761-4d8f-b6c4-d79de4918065&right=b4fbf973-64ec-4c14-9e9c-71a91b4973f4) · [Open completed seven-task run](http://127.0.0.1:8000/#/runs/06556e1b-ed9b-445c-9f01-ca35e7380c37).

## Earlier text-only matched comparison

- **Source:** one nine-step OSWorld Chrome attempt, source revision 1. Request: restore the last closed tab.
- **Execution:** Gemini CLI 0.61.0 with `gemini-3.8-flash`; Codex 0.157.0 with `gpt-6-sol`. Low reasoning, one application invocation per task, 120-second timeout, no application retry.
- **Result:** both jobs completed and produced valid nine-step reviews. Gemini identified two problem episodes; Codex identified one.
- **Evidence limit:** these historical CLI runs received text only. Screenshots remain available in the human viewer. Neither review establishes visual correctness or overall model accuracy.

| Model | Input tokens | Output tokens | Token-based estimate |
|---|---:|---:|---:|
| Gemini 3.8 Flash | 8,731 | 1,878 | $0.01359075 |
| GPT-6 Sol | 11,361 | 1,147 | $0.03419200 |
| Successful pair | 20,092 | 3,025 | $0.04778275 |

- Tokens are provider-reported. Dollar amounts are estimates, not verified invoice charges. The calculation prices all input tokens at the uncached rate.
- Gemini's estimate uses $0.75/M input and $3.75/M output, consistent with the [Google pricing page](https://ai.google.dev/gemini-api/docs/pricing) at verification time. Codex's estimate uses the installed LiteLLM price table.
- A CLI budget is a planning allowance, not a hard billing cap. The application makes one invocation; a CLI may reconnect internally. Codex does not enforce the configured output-token estimate in this adapter.
- Failed setup attempts are excluded from the successful-pair total. Their cost is unknown, so this is **not** the total spend for the session.

[Open comparison](http://127.0.0.1:8000/#/compare?left=f2203913-b98c-48ca-9782-19a8b0f369f6&right=b19750b6-d08e-4fce-a211-04d2bb35662c) · [Raw result and usage evidence](demo-data/cli-model-comparison-20260927T043214Z.json).

## Earlier text-only eight-task coverage

The matched pair was followed by one Gemini-only run covering the other seven tasks across Office, Web browsing and Image editing.

| Scope | Valid reviews | Failed jobs | Input / output tokens | Estimate |
|---|---:|---:|---:|---:|
| Seven additional Gemini tasks | 5 | 2 | 66,712 / 16,007 | $0.11006025 |
| All eight distinct Gemini tasks | 6 | 2 | 75,443 / 17,885 | $0.12365100 |
| These eight Gemini calls + matched Codex call | 7 | 2 | 86,804 / 19,032 | $0.15784300 |

- Every task was attempted once, including the passing GIMP task through the recovery-review route. No task was retried automatically.
- Two responses were malformed JSON: Writer `66399b0d…` and Chrome `368d9ba4…`. The parser errors occur before the response ends, so EOF truncation is not established. They retain usage and diagnostics, with no fabricated review. The bulk run correctly shows **Finished with errors** at 100% processing completion.
- The seven-task run used a **$0.10/task planning allowance**, $0.70 total. The estimate includes its failed responses; actual invoice charges and earlier setup-attempt costs remain unverified.
- This small text-only sample does not establish accuracy or production reliability. Failures and evidence gaps stay visible in analytics.

[Open bulk run](http://127.0.0.1:8000/#/runs/f955f0b2-b9ac-4066-83c2-dd4c66093ca3) · [Per-task evidence](demo-data/gemini-3.8-flash-multidataset-20260927T043506Z.json).

## What the comparison taught us

- Both models identified repeated restore shortcuts beyond the one-tab request.
- Gemini also inferred mis-targeted clicks and recovery after `Ctrl+1`, despite having no UI observations. Codex kept those effects unverified.
- A disagreement note is saved on both reviews for human investigation. No review was rewritten and no taxonomy label was approved.
- Shared draft labels help reuse names; they must not become evidence that a mistake or recovery occurred. A change of action alone does not prove recovery.
- The visual successor uses a versioned prompt and new matched reviews. The remaining quality gate is image-grounded human adjudication. Nine differing step fields measure output differences, not nine proven errors.

## Retained setup failures

- Earlier attempts exposed CLI argument/configuration issues, structured-output parsing and an API key requiring OpenAI's US endpoint. Their reports remain under `demo-data/cli-model-comparison-*.json`.
- An older failed Gemini report recorded 8,693 input tokens but incomplete output accounting. Its zero output field is not proof of zero output or zero charge.
- Docker disk exhaustion was resolved by clearing unused build cache and restarting RabbitMQ with its existing volume. Database, broker queues and stored evidence were preserved.
- Six failed setup runs are soft-archived and remain under **Show archived**. Ready Gemini/Codex execution presets were saved without starting any extra calls.
- The final successful pair used the exact requested model IDs. No substitute model was silently selected.
