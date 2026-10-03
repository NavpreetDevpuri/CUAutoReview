"""Taxonomy releases, proposal and candidate views, and bounded curation runs."""

from __future__ import annotations

import copy
import os
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from app.models import (
    CandidateDecision,
    Preset,
    PresetRevision,
    ProposalFeedback,
    ProposalRevision,
    TaxonomyCandidate,
    TaxonomyProposal,
    TaxonomyRelease,
    User,
    uid,
)
from app.schemas import TaxonomyConsolidate
from app.services.audit import activity
from app.services.records import digest, record
from app.services.taxonomy_lock import lock_taxonomy_workspace


def current_release(db: Session, workspace_id: str) -> TaxonomyRelease | None:
    return db.scalar(
        select(TaxonomyRelease)
        .where(TaxonomyRelease.workspace_id == workspace_id)
        .order_by(TaxonomyRelease.created_at.desc())
        .limit(1)
    )


def proposal_view(db: Session, proposal: TaxonomyProposal) -> dict[str, Any]:
    item = record(proposal)
    revision = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
    revisions = db.scalars(
        select(ProposalRevision).where(ProposalRevision.proposal_id == proposal.id).order_by(ProposalRevision.revision)
    ).all()
    item["revisions"] = [record(r) for r in revisions]
    item["latest_revision"] = record(revision) if revision else None
    if revision:
        item.update(
            {
                "name": revision.name,
                "description": revision.description,
                "evidence_refs": revision.evidence_refs,
                "revision": revision.revision,
                "status": "draft",
            }
        )
    item["feedback"] = [
        record(f)
        for f in db.scalars(
            select(ProposalFeedback)
            .where(ProposalFeedback.proposal_id == proposal.id)
            .order_by(ProposalFeedback.created_at)
        ).all()
    ]
    return item


def candidate_view(candidate: TaxonomyCandidate) -> dict[str, Any]:
    item = record(candidate)
    content = candidate.content or {}
    item["hash"] = candidate.content_hash
    item["labels"] = copy.deepcopy(content.get("labels", []))
    item["mappings"] = copy.deepcopy(content.get("mappings", []))
    item["unresolved"] = copy.deepcopy(content.get("unresolved", []))
    item["curation"] = copy.deepcopy(content.get("curation"))
    item["status"] = "pending review"
    db = object_session(candidate)
    if db:
        decisions = db.scalars(select(CandidateDecision).where(CandidateDecision.candidate_id == candidate.id)).all()
        item["decisions"] = [record(decision) for decision in decisions]
        if any(decision.action == "approve" for decision in decisions):
            item["status"] = "approved"
        elif any(decision.action == "reject" for decision in decisions):
            item["status"] = "rejected"
        else:
            latest = current_release(db, candidate.workspace_id)
            heads, _ = _taxonomy_proposal_snapshot(db, candidate.workspace_id)
            item["stale"] = (
                candidate.base_hash != (latest.content_hash if latest else digest({"labels": []}))
                or candidate.proposal_heads != heads
            )
            if item["stale"]:
                item["status"] = "stale"
    return item


def _taxonomy_proposal_snapshot(db: Session, workspace_id: str):
    heads: dict[str, str] = {}
    entries = []
    proposals = db.scalars(
        select(TaxonomyProposal)
        .where(TaxonomyProposal.workspace_id == workspace_id)
        .order_by(TaxonomyProposal.created_at)
    ).all()
    for proposal in proposals:
        rev = db.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if not rev:
            continue
        head = {
            "revision_hash": rev.content_hash,
            "base_hash": proposal.base_hash,
            "base_release_id": proposal.base_release_id,
            "kind": proposal.kind,
            "label_id": proposal.label_id,
        }
        heads[proposal.id] = digest(head)
        feedback = db.scalars(
            select(ProposalFeedback)
            .where(ProposalFeedback.proposal_id == proposal.id)
            .order_by(ProposalFeedback.created_at)
        ).all()
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
                "feedback": [item.text for item in feedback],
            }
        )
    return heads, entries


def curate_taxonomy(db: Session, user: User, body: TaxonomyConsolidate):
    if not body.confirm_budget or body.expected_budget_usd is None:
        raise HTTPException(409, "Confirm the pinned taxonomy curation budget before starting")
    preset_revision = db.get(PresetRevision, body.preset_revision_id)
    preset = db.get(Preset, preset_revision.preset_id) if preset_revision else None
    if not preset_revision or not preset or preset.workspace_id != user.workspace_id:
        raise HTTPException(404, "Taxonomy curation preset revision not found")
    if body.expected_budget_usd != preset_revision.budget_usd:
        raise HTTPException(409, "Confirmed budget does not match the pinned curation preset")
    if os.getenv("ALLOW_HOSTED_INFERENCE", "false").lower() != "true":
        raise HTTPException(409, "Hosted inference is disabled. Set ALLOW_HOSTED_INFERENCE=true to opt in.")

    lock_taxonomy_workspace(db, user.workspace_id)
    release = current_release(db, user.workspace_id)
    base_content = copy.deepcopy(release.content if release else {"labels": []})
    base_hash = release.content_hash if release else digest(base_content)
    base_release_id = release.id if release else None
    heads, proposals = _taxonomy_proposal_snapshot(db, user.workspace_id)
    if not proposals:
        raise HTTPException(409, "Add at least one taxonomy proposal before paid curation")
    preset_record = record(preset_revision)
    # Release the workspace advisory transaction lock before any provider request.
    db.commit()

    from app.worker.review_backends import ReviewBackendError
    from app.worker.taxonomy_backend import consolidate_drafts

    try:
        result = consolidate_drafts(preset_revision=preset_record, base_content=base_content, proposals=proposals)
    except ReviewBackendError as exc:
        usage = copy.deepcopy(exc.usage) if isinstance(exc.usage, dict) else {"kind": "unknown", "estimated_usd": None}
        activity(
            db, user, "taxonomy.curation_failed", "taxonomy", None, preset_revision_id=preset_revision.id, usage=usage
        )
        db.commit()
        raise HTTPException(422, str(exc)) from None

    # The provider call ran outside the database transaction's lock. Discard its result if
    # either the immutable release or any draft head moved while it was in flight.
    lock_taxonomy_workspace(db, user.workspace_id)
    db.expire_all()
    latest = current_release(db, user.workspace_id)
    latest_hash = latest.content_hash if latest else digest({"labels": []})
    latest_heads, _ = _taxonomy_proposal_snapshot(db, user.workspace_id)
    usage = result.get("usage") if isinstance(result.get("usage"), dict) else {"kind": "unknown", "estimated_usd": None}
    if (latest.id if latest else None) != base_release_id or latest_hash != base_hash or latest_heads != heads:
        activity(
            db,
            user,
            "taxonomy.curation_discarded_stale",
            "taxonomy",
            None,
            preset_revision_id=preset_revision.id,
            usage=usage,
        )
        db.commit()
        raise HTTPException(409, "Taxonomy changed during curation; the paid draft was discarded")

    content = result.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("labels"), list):
        raise HTTPException(422, "Taxonomy curation returned an invalid candidate")
    content = copy.deepcopy(content)
    content["curation"] = {
        "preset_revision_id": preset_revision.id,
        "usage": copy.deepcopy(usage),
        "provenance": copy.deepcopy(result.get("provenance") or {}),
    }
    version_num = (
        db.scalar(select(func.count(TaxonomyCandidate.id)).where(TaxonomyCandidate.workspace_id == user.workspace_id))
        or 0
    ) + 1
    candidate = TaxonomyCandidate(
        id=uid(),
        workspace_id=user.workspace_id,
        version=f"candidate-{version_num}",
        base_release_id=base_release_id,
        base_hash=base_hash,
        proposal_heads=heads,
        content=content,
        content_hash=digest(content),
        created_by=user.id,
    )
    db.add(candidate)
    activity(
        db,
        user,
        "taxonomy.curated",
        "taxonomy_candidate",
        candidate.id,
        version=candidate.version,
        preset_revision_id=preset_revision.id,
        usage=usage,
    )
    db.commit()
    return candidate_view(candidate)
