# Third-party notices

Bundled benchmark evidence is attributed separately from CUAutoReview code and generated reviews. These notices cover the material in `reference/examples/`, `poc/data/`, `platform/demo-data/`, and benchmark content visible in viewer screenshots. Dependencies installed through Python, npm and Docker retain their respective licenses.

## OSWorld-Verified recorded trajectories

- **Source:** [XLANG's OSWorld-Verified trajectory dataset](https://huggingface.co/datasets/xlangai/ubuntu_osworld_verified_trajs), pinned to commit `5473c39e42a538a187a9b2c2b499db59d560fd8c`; selected members of `o3_15steps.zip`.
- **Declared license:** the pinned dataset card says `license: mit`. A [byte-preserved card](poc/data/source/osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/dataset-card.md) is included. The inspected dataset root had no separate LICENSE file; this declaration does not establish licenses for every third-party item visible in a screenshot or referenced document.
- **Attribution:** Tianbao Xie et al., [Introducing OSWorld-Verified](https://xlang.ai/blog/osworld-verified), July 2025. The retained dataset card supplies the full citation and marks training use as not recommended.
- **Included evidence:** selected screenshots, actions, runtime logs and recorded scores. Task folders retain source URLs, archive member names and checksums in `provenance.json`. The complete archive and videos were not downloaded; the complete archive checksum was not independently verified locally.
- **Derived files:** normalized JSON task records, demo import ZIPs, model reviews and viewer screenshots were created for this project. Normalization does not turn recorded scores into rerun evaluations or model diagnoses into human-adjudicated labels.

## OSWorld task definitions

- **Source:** [XLANG's OSWorld repository](https://github.com/xlang-ai/OSWorld), pinned to commit `b138d348256078fa634fc3b73567a7337c793e6b`.
- **License:** Apache License 2.0. The retained license states **Copyright 2024 XLANG NLP Lab**. The complete [upstream license text](poc/data/source/osworld-verified/66399b0d-8fda-4618-95c4-bfc6191617e9/LICENSE-task-source.txt) is included and applies to the copied task-source material, including the three additional task definitions under `platform/demo-data/source/`.
- Original `task.json` files are retained as downloaded; normalized task manifests are derived representations. The pinned definitions match task IDs but are not proven to be the exact evaluator versions used for the historical trajectories.

## Scope limits

- Upstream dataset metadata does not individually itemize rights for third-party web content, documents, images or application interfaces visible in the evidence. This project does not claim broader rights over that content.
- Recorded trajectories, model outputs and screenshots are evidence for inspecting this demonstration. They are not independently verified gold diagnoses or proof of general review accuracy.
- Source-specific details and hashes remain in the bundled provenance files. [Benchmark selection and evidence limits](specs/06-benchmark-and-example-data.md) provide further context.
