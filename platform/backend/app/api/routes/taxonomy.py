"""Taxonomy proposals, feedback, consolidation and candidate approval."""

from __future__ import annotations

import copy

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_user, require_role
from app.core.database import get_db
from app.models import (
    CandidateDecision,
    ProposalFeedback,
    ProposalRevision,
    TaxonomyCandidate,
    TaxonomyProposal,
    TaxonomyRelease,
    User,
    uid,
)
from app.schemas import (
    CandidateApproval,
    CandidateRejection,
    TaxonomyConsolidate,
    TaxonomyProposalCreate,
)
from app.schemas import (
    ProposalFeedback as ProposalFeedbackIn,
)
from app.services.audit import activity
from app.services.records import digest, record
from app.services.taxonomy import candidate_view, curate_taxonomy, current_release, proposal_view
from app.services.taxonomy_lock import lock_taxonomy_workspace

router = APIRouter()


@router.get("/api/taxonomy")
def taxonomy(db: Session = Depends(get_db), user: User = Depends(get_user)):
    releases = db.scalars(
        select(TaxonomyRelease)
        .where(TaxonomyRelease.workspace_id == user.workspace_id)
        .order_by(TaxonomyRelease.created_at.desc())
    ).all()
    proposals = db.scalars(
        select(TaxonomyProposal)
        .where(TaxonomyProposal.workspace_id == user.workspace_id)
        .order_by(TaxonomyProposal.created_at.desc())
    ).all()
    candidates = db.scalars(
        select(TaxonomyCandidate)
        .where(TaxonomyCandidate.workspace_id == user.workspace_id)
        .order_by(TaxonomyCandidate.created_at.desc())
    ).all()
    latest = releases[0].content if releases else {"labels": []}
    return {
        "releases": [{**record(r), "labels": (r.content or {}).get("labels", [])} for r in releases],
        "proposals": [proposal_view(db, p) for p in proposals],
        "candidates": [candidate_view(c) for c in candidates],
        "labels": latest.get("labels", []),
    }


@router.post("/api/taxonomy/proposals")
def create_proposal(
    body: TaxonomyProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager", "reviewer")),
):
    lock_taxonomy_workspace(db, user.workspace_id)
    release = (
        db.get(TaxonomyRelease, body.base_release_id)
        if body.base_release_id
        else current_release(db, user.workspace_id)
    )
    if (body.base_release_id and not release) or (release and release.workspace_id != user.workspace_id):
        raise HTTPException(404, "Base release not found")
    base_hash = release.content_hash if release else digest({"labels": []})
    if body.label_id and db.scalar(
        select(TaxonomyProposal.id).where(
            TaxonomyProposal.workspace_id == user.workspace_id, TaxonomyProposal.label_id == body.label_id
        )
    ):
        raise HTTPException(409, "A draft already exists for this label; append a revision to that proposal")
    kind = {"new_label": "label", "edit_label": "edit", "retire_label": "retire"}.get(body.kind, body.kind)
    proposal = TaxonomyProposal(
        workspace_id=user.workspace_id,
        kind=kind,
        label_id=body.label_id,
        base_release_id=release.id if release else None,
        base_hash=base_hash,
        created_by=user.id,
    )
    db.add(proposal)
    db.flush()
    content = {"name": body.name.strip(), "description": body.description.strip(), "evidence_refs": body.evidence_refs}
    rev = ProposalRevision(
        proposal_id=proposal.id,
        revision=1,
        name=content["name"],
        description=content["description"],
        evidence_refs=content["evidence_refs"],
        content_hash=digest(content),
        base_revision_hash=None,
        change_type="create",
        created_by=user.id,
    )
    db.add(rev)
    db.flush()
    proposal.latest_revision_id = rev.id
    activity(db, user, "taxonomy.proposal_created", "taxonomy_proposal", proposal.id, kind=body.kind)
    db.commit()
    return proposal_view(db, proposal)


@router.patch("/api/taxonomy/proposals/{proposal_id}")
def edit_proposal(
    proposal_id: str,
    body: TaxonomyProposalCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager", "reviewer")),
):
    lock_taxonomy_workspace(db, user.workspace_id)
    proposal = db.get(TaxonomyProposal, proposal_id)
    if not proposal or proposal.workspace_id != user.workspace_id:
        raise HTTPException(404, "Proposal not found")
    previous = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
    release = (
        db.get(TaxonomyRelease, body.base_release_id)
        if body.base_release_id
        else current_release(db, user.workspace_id)
    )
    if (body.base_release_id and not release) or (release and release.workspace_id != user.workspace_id):
        raise HTTPException(404, "Base release not found")
    if body.label_id and db.scalar(
        select(TaxonomyProposal.id).where(
            TaxonomyProposal.workspace_id == user.workspace_id,
            TaxonomyProposal.label_id == body.label_id,
            TaxonomyProposal.id != proposal.id,
        )
    ):
        raise HTTPException(409, "A draft already exists for this label; append a revision to that proposal")
    content = {"name": body.name.strip(), "description": body.description.strip(), "evidence_refs": body.evidence_refs}
    revision = ProposalRevision(
        proposal_id=proposal.id,
        revision=(previous.revision + 1 if previous else 1),
        name=content["name"],
        description=content["description"],
        evidence_refs=content["evidence_refs"],
        content_hash=digest(content),
        base_revision_hash=previous.content_hash if previous else None,
        change_type="edit",
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    proposal.latest_revision_id = revision.id
    proposal.kind = {"new_label": "label", "edit_label": "edit", "retire_label": "retire"}.get(body.kind, body.kind)
    proposal.label_id = body.label_id
    proposal.base_release_id = release.id if release else None
    proposal.base_hash = release.content_hash if release else digest({"labels": []})
    activity(db, user, "taxonomy.proposal_edited", "taxonomy_proposal", proposal.id, revision=revision.revision)
    db.commit()
    return proposal_view(db, proposal)


@router.post("/api/taxonomy/proposals/{proposal_id}/feedback")
def proposal_feedback(
    proposal_id: str,
    body: ProposalFeedbackIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager", "reviewer")),
):
    lock_taxonomy_workspace(db, user.workspace_id)
    proposal = db.get(TaxonomyProposal, proposal_id)
    if not proposal or proposal.workspace_id != user.workspace_id:
        raise HTTPException(404, "Proposal not found")
    if not proposal.latest_revision_id:
        raise HTTPException(409, "Proposal has no revision")
    feedback = ProposalFeedback(
        proposal_id=proposal.id,
        proposal_revision_id=proposal.latest_revision_id,
        text=body.text.strip(),
        created_by=user.id,
    )
    db.add(feedback)
    # Feedback appends a proposal content revision, preserving previous revisions exactly.
    previous = db.get(ProposalRevision, proposal.latest_revision_id)
    content = {
        "name": previous.name,
        "description": previous.description,
        "evidence_refs": previous.evidence_refs,
        "feedback": body.text.strip(),
    }
    revision = ProposalRevision(
        proposal_id=proposal.id,
        revision=previous.revision + 1,
        name=previous.name,
        description=previous.description,
        evidence_refs=previous.evidence_refs,
        content_hash=digest(content),
        base_revision_hash=previous.content_hash,
        change_type="feedback",
        created_by=user.id,
    )
    db.add(revision)
    db.flush()
    proposal.latest_revision_id = revision.id
    db.flush()
    feedback.proposal_revision_id = revision.id
    activity(db, user, "taxonomy.feedback_added", "taxonomy_proposal", proposal.id)
    db.commit()
    return proposal_view(db, proposal)


@router.post("/api/taxonomy/consolidate")
def consolidate_taxonomy(
    body: TaxonomyConsolidate | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "manager")),
):
    body = body or TaxonomyConsolidate()
    if body.preset_revision_id:
        return curate_taxonomy(db, user, body)
    if body.confirm_budget or body.expected_budget_usd is not None:
        raise HTTPException(422, "A preset revision is required for budget confirmation")
    lock_taxonomy_workspace(db, user.workspace_id)
    release = current_release(db, user.workspace_id)
    base_content = copy.deepcopy(release.content if release else {"labels": []})
    base_hash = release.content_hash if release else digest(base_content)
    proposals = db.scalars(
        select(TaxonomyProposal)
        .where(TaxonomyProposal.workspace_id == user.workspace_id)
        .order_by(TaxonomyProposal.created_at)
    ).all()
    heads: dict[str, str] = {}
    entries = []
    for proposal in proposals:
        rev = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if rev:
            head = {
                "revision_hash": rev.content_hash,
                "base_hash": proposal.base_hash,
                "base_release_id": proposal.base_release_id,
                "kind": proposal.kind,
                "label_id": proposal.label_id,
            }
            heads[proposal.id] = digest(head)
            entries.append(
                {
                    "proposal_id": proposal.id,
                    "kind": proposal.kind,
                    "label_id": proposal.label_id,
                    "name": rev.name,
                    "description": rev.description,
                    "evidence_refs": rev.evidence_refs,
                    "base_hash": proposal.base_hash,
                    "base_release_id": proposal.base_release_id,
                }
            )
    labels = copy.deepcopy(base_content.get("labels", []))
    mappings = []
    unresolved = []
    for entry in entries:
        kind = entry["kind"]
        proposal_id = entry["proposal_id"]
        label_id = entry["label_id"]
        target_id = label_id or proposal_id
        position = next((i for i, label in enumerate(labels) if str(label.get("id")) == str(target_id)), None)
        if kind in ("edit", "retire", "merge") and entry["base_hash"] != base_hash:
            unresolved.append(
                {
                    "proposal_id": proposal_id,
                    "reason": "Proposal base changed. Rebase and revise it before consolidation.",
                }
            )
            continue
        if kind in ("edit", "retire") and position is None:
            unresolved.append({"proposal_id": proposal_id, "reason": "Target label does not exist in base release."})
            continue
        if kind == "retire":
            labels[position] = {**labels[position], "status": "retired"}
            mappings.append(
                {
                    "proposal_id": proposal_id,
                    "canonical_label_id": target_id,
                    "rationale": "Direct retirement proposal targeted this existing label.",
                }
            )
        elif kind == "edit":
            labels[position] = {
                **labels[position],
                "name": entry["name"],
                "description": entry["description"],
                "status": "proposed_edit",
            }
            mappings.append(
                {
                    "proposal_id": proposal_id,
                    "canonical_label_id": target_id,
                    "rationale": "Direct edit proposal targeted this existing label.",
                }
            )
        elif kind == "merge":
            if position is None:
                unresolved.append({"proposal_id": proposal_id, "reason": "Merge requires an existing target label ID."})
                continue
            mappings.append(
                {
                    "proposal_id": proposal_id,
                    "canonical_label_id": target_id,
                    "rationale": "Draft proposal explicitly maps to the selected existing label.",
                }
            )
        else:
            labels.append(
                {
                    "id": target_id,
                    "name": entry["name"],
                    "description": entry["description"],
                    "status": "proposed",
                    "evidence_refs": entry["evidence_refs"],
                }
            )
            mappings.append(
                {
                    "proposal_id": proposal_id,
                    "canonical_label_id": target_id,
                    "rationale": "Draft proposal retained as its own label pending human approval.",
                }
            )
    content = {
        **base_content,
        "labels": labels,
        "mappings": mappings,
        "unresolved": unresolved,
        "draft_proposals": entries,
    }
    version_num = (
        len(db.scalars(select(TaxonomyCandidate).where(TaxonomyCandidate.workspace_id == user.workspace_id)).all()) + 1
    )
    candidate = TaxonomyCandidate(
        id=uid(),
        workspace_id=user.workspace_id,
        version=f"candidate-{version_num}",
        base_release_id=release.id if release else None,
        base_hash=base_hash,
        proposal_heads=heads,
        content=content,
        content_hash=digest(content),
        created_by=user.id,
    )
    db.add(candidate)
    activity(db, user, "taxonomy.consolidated", "taxonomy_candidate", candidate.id, version=candidate.version)
    db.commit()
    return candidate_view(candidate)


@router.post("/api/taxonomy/candidates/{candidate_id}/approve")
def approve_candidate(
    candidate_id: str,
    body: CandidateApproval,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    lock_taxonomy_workspace(db, user.workspace_id)
    candidate = db.get(TaxonomyCandidate, candidate_id)
    if not candidate or candidate.workspace_id != user.workspace_id:
        raise HTTPException(404, "Candidate not found")
    decisions = db.scalars(select(CandidateDecision).where(CandidateDecision.candidate_id == candidate.id)).all()
    if any(item.action == "reject" for item in decisions):
        raise HTTPException(409, "A rejected candidate cannot be approved")
    if any(item.action == "approve" for item in decisions):
        raise HTTPException(409, "This candidate was already approved")
    latest = current_release(db, user.workspace_id)
    latest_hash = latest.content_hash if latest else digest({"labels": []})
    current_heads = {
        p.id: digest(
            {
                "revision_hash": db.get(ProposalRevision, p.latest_revision_id).content_hash,
                "base_hash": p.base_hash,
                "base_release_id": p.base_release_id,
                "kind": p.kind,
                "label_id": p.label_id,
            }
        )
        for p in db.scalars(select(TaxonomyProposal).where(TaxonomyProposal.workspace_id == user.workspace_id)).all()
        if p.latest_revision_id and db.get(ProposalRevision, p.latest_revision_id)
    }
    if (
        candidate.content_hash != body.expected_hash
        or candidate.version != body.version
        or candidate.base_hash != latest_hash
        or candidate.proposal_heads != current_heads
    ):
        raise HTTPException(409, "Candidate is stale: its hash, base release, or proposal revisions changed")
    content = candidate.content or {}
    unresolved = content.get("unresolved") or []
    if unresolved:
        raise HTTPException(409, "Candidate has unresolved proposal targets and cannot be published")
    # Only publish canonical labels supplied by an exact candidate.
    # A draft proposal collection is not itself a label release.
    labels = copy.deepcopy((candidate.content or {}).get("labels", []))
    label_ids = [str(label.get("id") or "") for label in labels if isinstance(label, dict)]
    if (
        len(label_ids) != len(labels)
        or any(not label_id for label_id in label_ids)
        or len(set(label_ids)) != len(label_ids)
    ):
        raise HTTPException(409, "Candidate contains missing or duplicate label IDs")
    for label in labels:
        label["status"] = "retired" if label.get("status") == "retired" else "active"
    release_content = {key: copy.deepcopy(value) for key, value in (candidate.content or {}).items()}
    existing_releases = db.scalars(
        select(TaxonomyRelease).where(TaxonomyRelease.workspace_id == user.workspace_id)
    ).all()
    version = f"{len(existing_releases) + 1}.0.0"
    release = TaxonomyRelease(
        id=uid(),
        workspace_id=user.workspace_id,
        version=version,
        content=release_content,
        content_hash=digest(release_content),
        created_by=user.id,
    )
    db.add(release)
    db.add(
        CandidateDecision(
            candidate_id=candidate.id, action="approve", expected_hash=body.expected_hash, created_by=user.id
        )
    )
    activity(
        db,
        user,
        "taxonomy.approved",
        "taxonomy_release",
        release.id,
        candidate_id=candidate.id,
        candidate_hash=candidate.content_hash,
    )
    db.commit()
    return {**record(release), "labels": labels}


@router.post("/api/taxonomy/candidates/{candidate_id}/reject")
def reject_candidate(
    candidate_id: str,
    body: CandidateRejection,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    lock_taxonomy_workspace(db, user.workspace_id)
    candidate = db.get(TaxonomyCandidate, candidate_id)
    if not candidate or candidate.workspace_id != user.workspace_id:
        raise HTTPException(404, "Candidate not found")
    db.add(
        CandidateDecision(
            candidate_id=candidate.id,
            action="reject",
            expected_hash=candidate.content_hash,
            reason=body.reason.strip(),
            created_by=user.id,
        )
    )
    activity(db, user, "taxonomy.rejected", "taxonomy_candidate", candidate.id, reason=body.reason.strip())
    db.commit()
    return {"candidate_id": candidate.id, "action": "reject"}
