# Real OSWorld-Verified examples

Two **actual failed attempts**, published as `o3` with a 15-step budget, downloaded for local inspection. Both original `result.txt` files contain **0**. These are scored failures; the notes below are assistant inspection, **not human-adjudicated gold labels**.

Each directory contains the complete 15-step action trace, original score/runtime log, three selected screenshots, current pinned task definition, attribution, and checksummed provenance. Together they are approximately **1.1 MB**; the 3.4 GB archive and videos were not downloaded.

## 1. Wrong field receives the value

**Task:** insert an empty table with **7 columns and 5 rows** at the cursor.

| Step | Recorded intention/action | Observable evidence |
|---|---|---|
| 11 | Type `7` into Columns | The later screenshot shows Columns received text |
| 12–13 | Focus Rows, then type `5` | Step 13 screenshot shows **Columns = 75; Rows = 2** |
| 14 | Backspace to correct Columns | Last recorded frame shows **Columns = 7; Rows = 2** |
| 15 | Try to focus Rows again | Insert Table dialog remains open in the last recorded frame |

This supports investigating a field-targeting/focus mismatch and incomplete recovery. The mistaken `75` was corrected, so it must not automatically become the primary explanation for the final failure. The last recorded frame still lacks the requested five rows and completed insertion. Exact causal attribution needs full evidence and review.

![Recorded step 13: 75 columns and 2 rows](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/step_13_20250728@131733.png)

[Task and evaluator configuration](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/task.json) · [Full action trace](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/traj.jsonl) · [Original score](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/result.txt) · [Last recorded frame](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/step_15_20250728@131805.png) · [Provenance](osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/provenance.json).

The current task configuration references a **gold DOCX artifact** for table comparison. That is an expected final-state reference, not a prescribed action sequence; the artifact URL is retained in the task/provenance files.

## 2. Intended footer action opens another dialog

**Task:** add a page number at the bottom-left of every page.

The first five actions repeatedly attempt to open Insert. At step 7, the action comment says “Header and Footer,” but the associated screenshot shows the **Bookmark** dialog. Later action comments describe dismissing unexpected dialogs and trying again. These observations support a candidate UI-targeting/recovery issue, rather than a verified diagnosis of the agent's internal reasoning.

![Recorded step 7: Bookmark dialog while the action intended Header and Footer](osworld-verified/0e47de2a-32e0-456c-a366-8c607ef7a9d2/step_7_20250728@131349.png)

[Task and evaluator configuration](osworld-verified/0e47de2a-32e0-456c-a366-8c607ef7a9d2/task.json) · [Full action trace](osworld-verified/0e47de2a-32e0-456c-a366-8c607ef7a9d2/traj.jsonl) · [Original score](osworld-verified/0e47de2a-32e0-456c-a366-8c607ef7a9d2/result.txt) · [Provenance](osworld-verified/0e47de2a-32e0-456c-a366-8c607ef7a9d2/provenance.json).

## Limits that the future viewer must display

- The traces are dated **28 July 2025**; exact original agent, environment, task, and evaluator revisions are unknown. The downloaded task definitions match task IDs but come from a separately pinned newer checkout.
- Frames are recorded action frames. The exact archive harness version/timing is unknown; neither a verified pre-action initial frame nor a post-evaluation final state is included. Twelve intermediate screenshots per task and the videos remain upstream.
- Per-step reward/done fields are not the terminal grade. The original final score is in `result.txt`.
- Current evaluator coverage is narrower than task wording: footer checking does not verify left alignment; table checking does not directly establish placement at the original cursor. These observations describe the inspected current checker, not the unknown historical version.
- Do not execute action strings from `traj.jsonl` or setup commands from `task.json` while inspecting these files. They are source data. No new rollout was executed to create this example package.

[Benchmark comparison and acquisition plan](../../specs/06-benchmark-and-example-data.md) · [Public source dataset](https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs).
