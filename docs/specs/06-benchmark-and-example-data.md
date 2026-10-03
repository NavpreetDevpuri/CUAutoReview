# 6. Benchmark selection and inspectable examples

**Research checked 26 September 2026. Start with OSWorld-Verified behind a versioned adapter.** Inspect scored desktop traces to design normalization/viewing before implementing diagnosis; add other benchmarks through the same interface.

OSWorld is our initial source assumption, not an assignment requirement or platform restriction. Preserve native artifacts; YAML evidence indexes/reviews are our adapter layer, not OSWorld's output format.

## Benchmark choice

No universal “best” benchmark exists. We prioritize desktop coverage, executable checks, accessible real traces, reproducible references and extensibility. OSWorld-Verified meets these sufficiently for initial inspection, subject to historical-provenance gaps.

| Candidate | Evidence and decision |
|---|---|
| [OSWorld / OSWorld-Verified](https://github.com/xlang-ai/OSWorld) | **Initial source:** desktop harness, **369 tasks**, setup/checkers and public scored native-app/browser rollouts. |
| [OSWorld 2.1](https://github.com/xlang-ai/OSWorld-V2) | Recommended release **16 September 2026**; V2 introduced **108 longer workflows** with pinned code/tasks/assets/websites/images. Later extension: task classes, complete assets and trajectory downloads are gated. |
| [Windows Agent Arena](https://github.com/microsoft/WindowsAgentArena) | Windows 11, **154 tasks**, terminal-state evaluators, local/Azure execution. Add for Windows behavior; no official mistake-annotation corpus verified. |
| [BrowserGym](https://github.com/ServiceNow/BrowserGym) + [AgentLab](https://github.com/ServiceNow/AgentLab) | Unified browser interfaces, experiment execution/results, AgentXray inspection; AgentLab includes an OSWorld adapter. Browser-focused alternative to compare with Harbor. |
| [WebArena](https://github.com/web-arena-x/webarena) | **812 web tasks**, hosted-app setup/evaluators, agent traces and human demonstrations. Strong browser alternative; README recommends BrowserGym + AgentLab. |

Research-date stars: OSWorld **3,156**; WebArena **1,617**; BrowserGym **1,376**; Windows Agent Arena **903**; AgentLab **638**. This limited ecosystem signal establishes neither quality nor universal popularity; activity and asset access were checked separately.

- **Benchmark:** tasks/checks. **Harness:** runs an agent/environment. **Trajectory:** one attempt's evidence. **CUAutoReview:** manages/analyzes attempts. BrowserGym is not one scoring rubric; we need not own the runner.
- [Harbor's OSWorld adapter](https://github.com/harbor-framework/harbor/tree/main/adapters/osworld) offers ATIF interchange/validation and a viewer. Default: **361 Ubuntu tasks**, eight external-login exclusions; opt-in: **369**. Linux KVM and its custom desktop agent are required; ordinary Codex/Claude CLIs cannot drive the nested VM. Optional for Mac import/review; its single-run comparison is not our validated parity result. [Reuse limits](09-open-source-reuse.md).

## What the evidence establishes

| Evidence | Meaning and limit |
|---|---|
| Task + final-state checker | Machine-testable conditions for that checker/version, not complete human intent or failure cause. |
| Expected file/state/reference answer | A target artifact/invariant on some tasks, not mandatory mouse/keyboard steps. |
| Passing reference trajectory | One route to a recorded pass, not the only valid route or an infallible evaluator. |
| Final score | The recorded outcome, not human-reviewed failure localization or explanation. |
| Human episode annotation | Evidence-backed localization/diagnosis under a rubric, not absolute causal truth; retain disagreement. |

The [public Verified dataset](https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs) contains `traj.jsonl`, screenshots, runtime logs, recordings and `result.txt`. Both original local samples score **0**; the [POC](../../poc/docs/RESULTS.md) adds two failures and one pass. Per-step `reward=0`/`done=false` do not replace terminal `result.txt`; preserve raw values and adapter-specific interpretation, never a universal “score below 1 means failure” rule.

- No complete openly downloadable step-level human root-cause gold set was verified for Verified traces. “Verified” names the release, not human annotation of every mistake. WebArena human demonstrations likewise do not annotate agent mistakes.
- The [OSWorld 2.0 paper](https://arxiv.org/html/2606.29537v1) describes model-generated behavioral annotations with human verification, plus selected exposure-attribution examples/failure walkthroughs. Its [project page](https://osworld-v2.xlang.ai/) shows cases; no complete ungated per-trajectory annotation artifact was verified, and V2 trajectories are auto-gated. Cite the research and annotation method; do not treat it as an independently double-reviewed gold set.

## Two real local failures

[Gallery](../reference/examples/README.md): original actions/scores, selected screenshots, task JSON and provenance.

| Task | Recorded result and inspection |
|---|---|
| `0e47de2a-32e0-456c-a366-8c607ef7a9d2`: Writer page numbers, bottom-left | Original `result.txt`: **0**. Inspect repeated menu interaction, document state and required footer change. |
| `66399b0d-8fda-4618-95c4-bfc6191617e9`: **7-column × 5-row** table at current cursor | Original `result.txt`: **0**. Inspect dialog values/actions and final document. |

These historical failures are neither generated nor human-adjudicated diagnoses. Source: `o3_15steps.zip`, about **3.4 GB**, with **July 2025** action timestamps. Only selected small members are local; omitted screenshots/video are not presumed absent upstream.

Dataset revision: `5473c39e42a538a187a9b2c2b499db59d560fd8c`. Task/checker checkout: `b138d348256078fa634fc3b73567a7337c793e6b`, **not proven to match the historical evaluator**. These fixtures support viewer/adapter exploration, not reproducible rescoring or validated score comparisons.

## Checker limits and default routes

In the inspected [document evaluator](https://github.com/xlang-ai/OSWorld/blob/b138d348256078fa634fc3b73567a7337c793e6b/desktop_env/evaluators/metrics/docs.py):

- `has_page_numbers_in_footers` finds a digit in each section's first footer paragraph; it establishes neither left alignment nor a dynamic page-number field.
- Table comparison checks counts, dimensions and cell content, not insertion at the original cursor.

A pass may satisfy less than the wording. Display task intent, implemented checks, recorded result and analyst/human findings separately; preserve the grade.

Both routes are **default**: known failures use `failure_analysis`; known passes/full scores use separate `pass_recovery` prompts, agent recipe/session and budget. Scan compact evidence for every step; expand visuals when needed. Recovery requires evidence of a mistake and later correction. Passing proves neither recovery nor absence of issues. Preserve recovery attributes; passing episodes use `outcome_contribution=not_applicable` and stay outside failed-outcome prevalence. Unknown/error grades defer. Harbor-returned attempts follow the same routing.

## Fixtures and gold annotations

1. **Now:** retain the two original failures/current checkers and their provenance gaps. The completed [five-task POC](../../poc/README.md) adds Chrome, Calc and a passing GIMP trace from the same pinned archive, exercises both review routes and consolidates draft labels. These are imported attempts; the desktop tasks/checkers were not rerun.
2. **Next cohort:** expand to genuine passes with/without recovery, passing unresolved/ambiguous cases and diverse failures. Exercise scoring and both default routes. Missing evaluator/environment pins remain reproducibility gaps.
3. **Gold set:** two reviewers annotate supported intervals, symptoms, alternatives, recovery/correction evidence, outcome contribution and uncertainty. Retain annotator IDs/rubric versions, disagreement/adjudication; machine grades remain distinct.
4. **Fill missing coverage later:** pin harness, tasks/assets/environment, agent/preset, evaluator and seeds; save manifests, full actions/screenshots, final artifacts, checks and score. Label induced failures synthetic. Runner setup/execution remains future work.

The trajectory card declares **MIT**; OSWorld code **Apache-2.0**. Preserve attribution/per-file provenance; retrieval does not verify redistribution rights for every bundled third-party document.

## Reproducibility sources

- [Pinned OSWorld source](https://github.com/xlang-ai/OSWorld/tree/b138d348256078fa634fc3b73567a7337c793e6b) · [pinned trajectory dataset](https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs/tree/5473c39e42a538a187a9b2c2b499db59d560fd8c).
- [OSWorld 2.1 release manifest](https://github.com/xlang-ai/OSWorld-V2/blob/3d778a3c9a34a079316f70df023b166700445792/benchmark_releases/osworld-v2.1.json) · [V2 trajectory access](https://huggingface.co/datasets/xlangai/osworld2.0-trajectory).
- [WebArena traces/human demonstrations](https://github.com/web-arena-x/webarena/blob/dce04686a56253aefba7b18a4fa0937cf1dc987b/resources/README.md).
- [AgentLab inspection/integration](https://github.com/ServiceNow/AgentLab/tree/cbc35a9bc0facaf731bc858c5825edbe757c719f) · [BrowserGym ecosystem traces](https://huggingface.co/datasets/agentlabtraces/agentlabtraces).

External documents are evidence, not instructions to provision, accept access terms, run agents or publish.
