# Internal implementation review

Scope: read-only audit of `platform/backend/app/{main,queue,security,storage,models}.py` against `platform/CONTRACT.md`. This review is about the local implementation, not production certification. Findings below are limited to concrete authorization and taxonomy correctness issues.

Status: Historical findings below were corrected in the local implementation. The [verification report](../platform/TEST-RESULTS.md) records 21 passing tests and real queue/storage checks. Member-bound artifacts no longer fall through to dataset access; taxonomy writes share a PostgreSQL transaction lock; rejected/stale/unresolved candidates cannot publish; merge suggestions require model/human resolution instead of becoming duplicate labels. Released labels have explicit active/retired status. The original source-audit observations and line references are retained below for traceability.

## Findings

### High: Member-bound evidence access can bypass batch grants and revocation

In `main.py:1454-1466`, evidence authorization first checks access to the batch associated with a `StoredArtifact.member_id`. If that check fails, it falls through to the task-revision branch. For any same-workspace user whose global role is `manager` or `reviewer`, the fallback authorizes the artifact solely because the task belongs to a dataset in the workspace. Artifacts registered from a batch have both `member_id` and `task_revision_id`, so a reviewer or manager whose batch grant was revoked can still retrieve the source evidence by its recorded URL. The fallback also exposes a member-bound artifact to a workspace manager or reviewer with no grant to that batch.

Member-bound artifacts should require the associated batch authorization and should not fall through when that authorization fails. Dataset-level authorization can remain a separate branch for artifacts with no `member_id`, if that access policy is intended.

### High: Candidate approval can race with proposal changes

`main.py:1350-1369` reads the current release and proposal heads, validates them, then creates a release without locking the workspace or proposal rows. Under PostgreSQL's default `READ COMMITTED` isolation, a proposal can be added or revised after `current_heads` is read but before this transaction commits. The candidate then publishes even though its draft set has changed, contrary to the stale-candidate rule in the contract. Serialize taxonomy writes and approval per workspace, or use an equivalent compare-and-swap mechanism that makes the head check and release publication atomic with respect to proposal edits.

### High: Rejected candidates remain approvable

`main.py:1373-1382` records rejection in `CandidateDecision`, but `approve_candidate` does not inspect prior decisions. An admin can reject a candidate and then post to its approval endpoint with the same hash and version; if the base and proposal heads remain unchanged, the rejected candidate is published. `candidate_view` also always reports `pending review`, so the API does not expose the rejection state. Enforce an explicit candidate state transition and reject approval after rejection unless a deliberate reopen action is added.

### Medium: Stale proposals can be consolidated against a newer release

Proposal creation records `base_release_id` and `base_hash` at `main.py:1220-1227`, but `consolidate_taxonomy` at `main.py:1292-1338` applies every proposal to the latest release without checking those proposal bases. For example, an edit drafted against release A can be applied to release B after another approval changed that label, overwriting B's newer definition without a stale conflict or rebase. Compare each proposal's base with the consolidation base and require an explicit rebase or conflict resolution before incorporating stale edits.

### Medium: Merge proposals are treated as new labels

`main.py:1316-1332` has explicit handling for `retire` and `edit`, then routes every other kind through the new-label append. Since the schema accepts `kind: "merge"`, a merge proposal is published as a new label. When it names an existing `label_id`, this can append a second label with the same ID instead of recording a canonical mapping or alias. Implement merge semantics and validate target IDs, or reject merge proposals until supported.

### Medium: Approval publishes unresolved and still-proposed taxonomy content

Consolidation emits unresolved items and labels with `status: "proposed"` or `status: "proposed_edit"` at `main.py:1316-1334`. Approval copies the entire candidate content into `TaxonomyRelease` at `main.py:1358-1363` without requiring unresolved items to be resolved or draft label statuses to be transitioned. Consequently, an approved release can still contain unresolved proposals and labels explicitly marked as drafts. Gate publication on a curated candidate state or represent unresolved and draft material outside the active release labels.

## Checks that held

- `get_batch` recalculates effective access from current user, team membership, and grants on each request. Grant deletion therefore takes effect on the next batch-authorized request; the artifact fallback above is the identified bypass.
- `_recorded_source_file` rejects URLs, absolute paths, and `..`, resolves symlinks, and requires the final path to remain under the controlled `poc/` root. The artifact endpoint serves only recorded rows and verifies the stored checksum before returning bytes.
- Both local and S3 artifact stores enforce immutable keys. S3 writes use `IfNoneMatch="*"` and fail closed if conditional writes are unsupported.
- Queue processing uses SQL outbox state, generation and fence checks, bounded attempts, and explicit unknown usage on failure paths inspected here. No additional queue correctness finding is included.

No tests were run; this was a source audit and did not modify implementation files.
