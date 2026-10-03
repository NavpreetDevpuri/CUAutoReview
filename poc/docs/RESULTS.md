# Five-task experiment

**Luna baseline.** The [newer Sol rerun and viewer changes](RESULTS-SOL.md) are reported separately; this original experiment is preserved.

**The review, shared-label and consolidation flow ran successfully. Diagnostic accuracy remains unmeasured.** This is a small feasibility check on recorded desktop attempts, not a benchmark of reviewer quality.

## Successful run

- [Run `20260926-224411-20aa4`](../runs/20260926-224411-20aa4/run.json), 26 September 2026, 22:44:11 to 22:46:04 IST: **113.4 seconds**.
- Five distinct OSWorld-Verified tasks: four recorded failures and one pass; **69 actions** and 45 locally available screenshots. Only three frames per task were supplied to reviewers, 15 total.
- Five independent Codex `gpt-5.6-luna` sessions, up to three concurrent; one final consolidation session using the same model.
- All five review outputs and the final taxonomy candidate pass schema/reference checks. Every action has an annotation: **15 steps marked reviewed, 54 marked insufficient evidence**. The sparse image budget limits diagnosis coverage substantially.

| Task | Source score | Reviewer finding | Recovery finding |
|---|---:|---|---|
| Chrome monthly forecast, `368d9ba4` | 0 | Proxy error, then an alternative terminal retrieval path with no proof of the requested monthly result | Partial alternative output; browser restoration not observed |
| GIMP Square layer, `b148e375` | 1 | Apparent control-targeting misses before keyboard shortcut and naming | Recovered; final layer is visible. Contribution to failed outcome is `not_applicable` |
| Calc decimal formatting, `6e99a1ad` | 0 | Function Wizard remains visible; requested formatting is not evidenced | None observed |
| Writer page numbers, `0e47de2a` | 0 | Unrelated dialogs instead of the requested footer configuration | None observed |
| Writer 7 by 5 table, `66399b0d` | 0 | Incorrect numeric entry; insertion not evidenced | Columns partially corrected; rows remain 2 |

These are model findings, not verified human causes. A failed recorded score alone does not establish why an attempt failed.

## Shared labels and consolidation

- Six proposals became **five canonical draft labels** in [candidate YAML](../runs/20260926-224411-20aa4/taxonomy-candidate.yaml).
  - `p004` GIMP targeting misses and `p005` Writer menu targeting were mapped to `c02`, **off-target UI targeting**.
  - Dialog dismissal, retrieval-path deviation, proxy access and numeric-field append were kept separate.
  - Recovery and outcome contribution remain episode attributes, not taxonomy categories.
- Actual `list_labels` calls demonstrate shared visibility:

| Reviewer | First pool read | Final pool read |
|---|---|---|
| Chrome | v0 | v3 |
| GIMP | v0 | v4 |
| Calc | v0 | v3 |
| Writer footer | v4 | v5 |
| Writer table | v5 | v6 |

- Three proposals recorded `stale_base` after concurrent writers advanced the pool. Their content was preserved for reconciliation.
- The pool is append-only; no reviewer overwrote another review or approved a release. Candidate `0.1.0-draft` remains **pending human review**.
- This run exercises new proposals and a merge. Update proposals, human approval, clean no-issue passes and large-scale contention remain untested by inference.

## Costs and model availability

| Work | Input tokens | Cached subset | Output tokens | API-equivalent USD |
|---|---:|---:|---:|---:|
| Successful five-task run, including consolidation | 376,576 | 259,072 | 9,455 | $0.040028 |
| First integration run, before helper fix | 484,358 | 368,384 | 9,741 | $0.042252 |
| Successful small model preflight | 2,581 | 0 | 15 | $0.000534 |
| **Known total** | **863,515** | **627,456** | **19,211** | **$0.082814** |

- Standard short-context GPT-5.6 Luna API comparison per million tokens: **$0.20 uncached input, $0.02 cached input, $1.20 output**, checked 26 September 2026. Formula: `((input - cached) × 0.20 + cached × 0.02 + output × 1.20) / 1,000,000`.
- Successful-run estimated Codex usage: **1.000706 credits**, using rates 5 / 0.5 / 30 per million tokens. **Actual ChatGPT included allowance, billed credits and dollar invoice are unavailable.** API comparison excludes any unreported cache-write charges. Unsupported-model probes have no reported usage, so their billed cost is unknown.
- These are whole-session totals, including repeated/cached context; the passing review was not separately proven cheaper than failure analysis. Different caching, evidence or model behavior can change costs.
- Requested `gpt-6-luna` and `gpt-6-sol` preflights both returned “not supported when using Codex with a ChatGPT account.” `gpt-5.6-luna` worked. No unsupported-model cost or quality comparison is claimed.
- Sources: [OpenAI API pricing](https://developers.openai.com/api/docs/pricing), [Codex pricing](https://learn.chatgpt.com/docs/pricing#token-rates), [model details](https://developers.openai.com/api/docs/models/gpt-5.6-luna). Raw evidence lives in `runs/preflight*` and the two run folders.

## What failed or remains uncertain

- **Integration failure retained:** [first run](../runs/20260926-224125-3a464/run.json) produced reviews, but every label proposal failed because the helper schema left `type` ambiguous. Models supplied mechanism names instead of `new`/`update`; consolidation was skipped.
  - Fixed the schema with an enum and explicit operation wording, added a regression test, then reran the five tasks once.
  - Its original `completed` status is misleading for the end-to-end experiment. Treat that run as incomplete integration evidence; raw artifacts are preserved. The controller now marks unclassified episodes as a partial run.
- **GIMP localization:** the model identifies recovery and the final Square layer is visible, but recovery IDs start at step 8, omitting the shortcut at step 7. Individual intermediate click effects remain uncertain.
- **Writer factual slip:** proposal `p006` and its consolidation rationale incorrectly say 75 arose from an existing 2. The visible column sequence is 7 → 75 → 7; rows remain 2. The episode correctly records partial correction, but the proposal also understates that correction. Raw outputs remain unchanged for review.
- **Causality:** a proxy error supports an access problem, not proof that it explains every later action. An alternative retrieval strategy is not inherently a mistake; its appropriateness depends on the task/checker. Sparse screenshots do not establish exact focus or targeting causes.
- **Evidence provenance:** public [OSWorld trajectory dataset](https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs), revision `5473c39e42a538a187a9b2c2b499db59d560fd8c`; task definitions from `b138d348256078fa634fc3b73567a7337c793e6b` are not proven historical evaluator matches. Frame timing relative to an action must be interpreted from the source, not assumed to be post-action.
- **Importer metadata fix:** normalized string/integer step IDs in screenshot coverage. Corrected the three added provenance files' derived missing-frame lists; source hashes and saved model runs were unchanged.

## Validation and next decision

- Nine contract tests pass, covering ordered coverage, evidence references, outcome/recovery separation, recovery chronology, complete dedup mappings, concurrent/stale/idempotent proposals and the MCP enum bug. Browser checks cover task/step navigation, review notes, traces, raw artifacts and shared labels.
- All 85 checked local artifact URLs load. Viewer screenshots: [trajectory review](screenshots/trajectory-review.png), [shared labels](screenshots/shared-labels.png).
- All 16 reviewer helper calls were label reads/proposals; no shell, browser, search or computer calls appear in the agent logs. Source checker commands remained inert metadata.
- **Proceed with the idea, retain human review.** The run demonstrates the orchestration and inspectable artifacts; observed diagnosis inconsistencies show why automatic publication would be premature.
- Before platform implementation: independently adjudicate these five tasks, tighten recovery localization and contradictory-proposal checks, then compare sparse/richer screenshots on a broader set with clean passes and multiple recovery types. Measure evidence support and localization separately from label deduplication.
