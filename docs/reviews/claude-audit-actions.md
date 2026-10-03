# Opus audit: decisions and follow-up

27 September 2026. [Claude's report](claude-opus-5.5-feedback.md) is retained as returned. We checked its recommendations against the repository before applying changes.

| Finding | Decision and change |
|---|---|
| Diagnosis accuracy is unmeasured | Accepted. Start with two independent human assessments of the nine saved visual reviews, covering eight distinct tasks. [Compact validation worksheet](HUMAN-VALIDATION.md). No accuracy or recovery-precision score is claimed. |
| Conflicting implementation facts | Corrected retry wording to four total attempts, updated evidence links, clarified Docker versus host seeding and host audit versus runtime adapter, and added a dated status table to the submission summary. Also clarified that the local Task record represents one rollout; parent-task grouping of K attempts remains planned. |
| Repeated flags imply shared problem identity | Group identical displayed label/relationship rows in the all-review sidebar. Preserve every review-local problem number, run, model and step-specific frame-delivery status. Detailed explanations remain separate. Keep all-review visibility as requested by the user. |
| Cost scenario excludes passing reviews | Replace the old headline with transparent arithmetic from current visual checks, including failed attempts. Identify the mixed-model sample, and separate inference estimates from unmeasured human effort. Tiny samples do not establish production prices or capacity. |
| `reviewed` can be mistaken for visual inspection | Show whether this step's frame was sent, not sent or has unknown delivery, using existing recorded IDs. Citations remain model claims. Preserve historical result schemas; no backfilled claim that a model inspected a frame. |
| Taxonomy evolution needs a fuller exercise | Keep approval tests and POC dedup evidence separate from a future merge/split/reclassification exercise. Do not rename historical labels or publish a new release from an audit recommendation. Test explicit successor-release counts before claiming full evolution coverage. |

Additional UI fixes clarify task selections versus unique tasks, configured runtime settings versus health, per-run review counts, problem episodes versus affected steps, and singular/plural labels. [UX notes](../../platform/docs/UX-FEEDBACK.md) record the reasons.

## Qualifications to the audit

- Four screenshots were supplied, although Claude says five. It saw three UI source files and static screenshots, not backend code or live interactions.
- Source/supplied/cited frame IDs already existed. The gap was their visibility beside each flag, not total absence of evidence provenance. A new `evidence_modalities` result field would duplicate transport metadata and still would not prove visual understanding.
- Compact grouping is a display aid, not semantic deduplication or independent consensus. Repeated reviews of one source are correlated observations.
- The sidebar can already expand. Screenshots of its collapsed state do not establish a hover-only navigation requirement. No navigation rewrite was needed.
- The existing automated taxonomy tests cover exact approval, stale/rejected candidates and bounded curation. They do not establish a live merge/split/reclassification workflow or taxonomy quality.
- The saved final CLI result begins mid-overview after an automatic continuation; its main findings table and recommendations are present. The capture fix was checked locally without another provider call. [Usage and limits](claude-opus-5.5-usage.json).

## Verification

Current checks for these changes are recorded in [test results](../../platform/docs/TEST-RESULTS.md). Earlier backend/Docker/live-model evidence remains dated separately. Human adjudication, a complete taxonomy-evolution exercise and production load testing remain open.
