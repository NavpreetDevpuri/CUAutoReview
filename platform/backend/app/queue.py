"""SQL outbox relay and generation-fenced Celery review worker."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import uuid
from datetime import timedelta

import yaml
from celery import Celery
from kombu import Exchange, Queue
from sqlalchemy import func, select

from .config import settings
from .database import make_engine, make_session_factory
from .models import (
    Batch, BatchMember, Job, JobAttempt, OutboxEvent, PresetRevision,
    ProposalFeedback, ProposalRevision, ReviewResult, StoredArtifact, TaxonomyProposal,
    TaxonomyRelease, TaskRevision, User, as_utc, utcnow,
)
from .storage import create_artifact_store
from .taxonomy_lock import lock_taxonomy_workspace


celery_app = Celery("cuautoreview", broker=settings.celery_broker_url)
review_exchange = Exchange("cuautoreview", type="direct", durable=True)
dead_exchange = Exchange("cuautoreview.dlx", type="direct", durable=True)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_enable_remote_control=False,
    worker_cancel_long_running_tasks_on_connection_loss=True,
    broker_connection_retry_on_startup=True,
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    broker_heartbeat=30,
    broker_transport_options={"confirm_publish": True, "max_retries": 5},
    task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 5, "interval_start": 0, "interval_step": 0.5, "interval_max": 3},
    task_default_delivery_mode="persistent",
    task_default_queue="cuautoreview.reviews",
    task_default_exchange="cuautoreview",
    task_default_exchange_type="direct",
    task_default_routing_key="reviews",
    task_create_missing_queues=False,
    task_queues=(
        Queue("cuautoreview.reviews", exchange=review_exchange, routing_key="reviews", durable=True,
              queue_arguments={"x-queue-type": "quorum", "x-dead-letter-exchange": "cuautoreview.dlx",
                               "x-dead-letter-routing-key": "dead"}),
        Queue("cuautoreview.cli", exchange=review_exchange, routing_key="cli", durable=True,
              queue_arguments={"x-queue-type": "quorum", "x-dead-letter-exchange": "cuautoreview.dlx",
                               "x-dead-letter-routing-key": "dead"}),
        Queue("cuautoreview.dead", exchange=dead_exchange, routing_key="dead", durable=True,
              queue_arguments={"x-queue-type": "quorum"}),
    ),
    task_routes={"app.queue.run_review": {"queue": "cuautoreview.reviews", "routing_key": "reviews"}},
)

_engine = make_engine(settings.database_url)
SessionLocal = make_session_factory(_engine)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _retry_delay(attempt: int) -> timedelta:
    return timedelta(seconds=min(60, 2 ** min(attempt, 6)))


def _retryable_failure(exc: Exception) -> bool:
    """Retry only failures that can plausibly change on another provider invocation."""
    usage = getattr(exc, "usage", None)
    usage = usage if isinstance(usage, dict) else {}
    category = usage.get("review_error_category") or usage.get("cli_diagnostic_category")
    retryable_categories = {
        "model_response_schema_invalid", "model_response_invalid_json", "model_response_missing",
        "cli_output_invalid_json", "cli_timeout", "provider_quota_or_rate_limit",
        "provider_upstream_error", "cli_transport_error", "provider_timeout",
    }
    terminal_categories = {
        "provider_auth_failed", "provider_access_denied", "provider_request_rejected",
        "provider_model_unavailable", "codex_home_unavailable", "gemini_admin_policy_invalid",
        "gemini_settings_not_root_owned", "workspace_not_trusted", "cli_unavailable",
    }
    if category:
        return category in retryable_categories and category not in terminal_categories

    message = str(exc).lower()
    terminal_markers = (
        "authenticationerror", "permissiondeniederror", "invalid api key", "api key not valid",
        "badrequesterror", "invalidrequesterror", "notfounderror", "unsupportedparamserror",
        "contextwindowexceedederror", "contentpolicyviolation",
        "unauthorized", "http 401", "status 401", "permission denied", "http 403", "status 403",
        "not configured", "hosted inference is disabled", "unsupported reviewer backend",
        "unsupported model", "model pricing is unknown", "pinned model", "budget",
        "no retained review", "does not match this evaluator outcome", "exceeds the bounded context",
        "screenshot could not be read", "failed its size or checksum", "no model request was made",
        "invalid configuration", "required for this adapter",
    )
    if any(marker in message for marker in terminal_markers):
        return False
    retry_markers = (
        "timeout", "timed out", "temporar", "connectionerror", "apiconnectionerror",
        "ratelimiterror", "rate limit", "overloaded", "service unavailable", "internal server",
        "servererror", "model api call failed", "invalid json", "structured output",
        "schema validation", "evidence/schema validation", "does not cover each source step",
        "jsondecodeerror", "validationerror", "provider returned invalid",
    )
    return any(marker in message for marker in retry_markers)


def _batch_taxonomy_snapshot(session, batch: Batch):
    release = session.get(TaxonomyRelease, batch.taxonomy_release_id) if batch.taxonomy_release_id else None
    labels = copy.deepcopy((release.content or {}).get("labels", [])) if release else []
    known = {str(item.get("id")) for item in labels if isinstance(item, dict) and item.get("id")}
    proposals = session.scalars(select(TaxonomyProposal).where(
        TaxonomyProposal.workspace_id == batch.workspace_id).order_by(TaxonomyProposal.created_at)).all()
    heads = {}
    for proposal in proposals:
        revision = session.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
        if not revision:
            continue
        heads[proposal.id] = {"revision_id": revision.id, "content_hash": revision.content_hash,
                             "base_release_id": proposal.base_release_id, "base_hash": proposal.base_hash,
                             "kind": proposal.kind, "label_id": proposal.label_id}
        label_id = str(proposal.label_id or f"draft:{proposal.id}")
        if label_id in known:
            continue
        feedback = session.scalars(select(ProposalFeedback.text).where(
            ProposalFeedback.proposal_id == proposal.id).order_by(ProposalFeedback.created_at)).all()
        labels.append({"id": label_id, "name": revision.name, "description": revision.description,
                       "status": "draft", "proposal_id": proposal.id, "proposal_kind": proposal.kind,
                       "evidence_refs": copy.deepcopy(revision.evidence_refs or []),
                       "feedback": list(feedback)})
        known.add(label_id)
    return labels, heads


def _settle_batch_if_terminal(session, batch: Batch):
    # The API session factory disables autoflush. Persist this worker's member and
    # job updates before evaluating aggregate state, then serialize concurrent
    # finalizers on the batch row. The row lock also refreshes a status written by
    # a racing pause or cancellation before this worker can overwrite it.
    session.flush()
    batch = session.scalars(select(Batch).where(Batch.id == batch.id).with_for_update()
                            .execution_options(populate_existing=True)).first()
    if not batch or batch.status != "running":
        return
    active_jobs = session.scalar(select(func.count(Job.id)).where(
        Job.batch_id == batch.id, Job.status.in_(("queued", "running", "retrying")))) or 0
    if active_jobs:
        return
    statuses = session.scalars(select(BatchMember.status).where(BatchMember.batch_id == batch.id)).all()
    if any(status not in ("completed", "failed", "cancelled", "awaiting_review") for status in statuses):
        return
    if any(status == "awaiting_review" for status in statuses):
        batch.status = "awaiting_review"
    else:
        batch.status = "completed"
    batch.updated_at = utcnow()


@celery_app.task(name="app.queue.relay_outbox", ignore_result=True)
def relay_outbox(limit: int = 100):
    """Publish due SQL outbox entries; late duplicate publishes are safe by generation."""
    session = SessionLocal()
    sent = failed = 0
    now = utcnow()
    try:
        events = session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.status == "pending", OutboxEvent.available_at <= now)
            .order_by(OutboxEvent.created_at)
            .limit(min(max(limit, 1), 500))
            .with_for_update(skip_locked=True)
        ).all()
        for event in events:
            job = session.get(Job, event.job_id)
            batch = session.get(Batch, job.batch_id) if job else None
            if not job or not batch or job.generation != event.generation or job.status not in ("queued", "retrying"):
                event.status = "obsolete"
                continue
            # Paused or cancelled batches retain queued work but stop new delivery.
            if batch.status != "running":
                continue
            event.status = "sending"
            event.relay_owner = WORKER_ID
            event.relay_lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
            event.send_attempts += 1
            session.commit()
            try:
                preset = session.get(PresetRevision, job.preset_revision_id)
                queue_name = "cuautoreview.cli" if preset and preset.backend in ("codex", "gemini_cli") else "cuautoreview.reviews"
                run_review.apply_async(args=[job.id, event.generation],
                                       task_id=f"{event.id}:{event.send_attempts}", queue=queue_name)
                event.status = "sent"
                event.sent_at = utcnow()
                event.last_error = None
                sent += 1
            except Exception as exc:  # keep errors visible and use a bounded relay retry
                event.status = "pending"
                event.available_at = utcnow() + _retry_delay(event.send_attempts)
                event.last_error = f"Broker publish failed ({type(exc).__name__})"
                event.relay_owner = None
                event.relay_lease_expires_at = None
                failed += 1
            session.commit()
        # A relay crash after broker publish but before marking sent is an expected duplicate.
        expired = session.scalars(select(OutboxEvent).where(
            OutboxEvent.status == "sending", OutboxEvent.relay_lease_expires_at < now
        ).limit(min(max(limit, 1), 500))).all()
        for event in expired:
            event.status = "pending"
            event.available_at = now
            event.relay_owner = None
            event.relay_lease_expires_at = None
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"sent": sent, "publish_failures": failed}


def _claim(job_id: str, generation: int):
    session = SessionLocal()
    now = utcnow()
    try:
        job = session.scalars(select(Job).where(Job.id == job_id).with_for_update()).first()
        if (not job or job.generation != generation or job.status not in ("queued", "retrying")
                or as_utc(job.available_at) > now):
            return None
        batch = session.get(Batch, job.batch_id)
        if not batch or batch.status != "running":
            return None
        if job.attempt_count >= job.max_attempts:
            job.status = "failed"
            job.error = "Bounded attempt limit has been reached"
            job.updated_at = now
            member = session.get(BatchMember, job.member_id)
            if member:
                member.status = "failed"
            _settle_batch_if_terminal(session, batch)
            session.commit()
            return None
        # Rebuild the draft overlay at claim time so a queued worker sees the latest
        # proposals while retaining the batch's immutable taxonomy release.
        lock_taxonomy_workspace(session, batch.workspace_id)
        shared_labels, proposal_heads = _batch_taxonomy_snapshot(session, batch)
        job.shared_labels_snapshot = copy.deepcopy(shared_labels)
        job.fence_token += 1
        job.attempt_count += 1
        job.status = "running"
        job.lease_owner = WORKER_ID
        job.lease_expires_at = now + timedelta(seconds=settings.job_lease_seconds)
        job.updated_at = now
        member = session.get(BatchMember, job.member_id)
        if member:
            member.status = "running"
        attempt = JobAttempt(job_id=job.id, attempt_number=job.attempt_count,
                             generation=job.generation, fence_token=job.fence_token, status="running")
        session.add(attempt)
        session.commit()
        return {"job_id": job.id, "generation": job.generation, "fence_token": job.fence_token,
                "attempt_id": attempt.id, "attempt_number": job.attempt_count,
                "batch_id": job.batch_id, "member_id": job.member_id,
                "preset_revision_id": job.preset_revision_id, "review_kind": job.review_kind,
                "workspace_id": job.workspace_id,
                "taxonomy_release_id": batch.taxonomy_release_id,
                "taxonomy_proposal_heads": proposal_heads,
                "shared_labels_snapshot": copy.deepcopy(shared_labels)}
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _save_proposals(session, workspace_id: str, user_id: str, proposals: list[dict]):
    from .main import digest
    lock_taxonomy_workspace(session, workspace_id)
    for item in proposals:
        provider_id = str(item.get("id") or "")
        label_id = provider_id or None
        if not item.get("name") or not item.get("description"):
            continue
        proposal = session.scalar(select(TaxonomyProposal).where(
            TaxonomyProposal.workspace_id == workspace_id, TaxonomyProposal.label_id == label_id
        )) if label_id else None
        body = {"name": item["name"], "description": item["description"],
                "evidence_refs": item.get("evidence_refs") or []}
        if proposal:
            previous = session.get(ProposalRevision, proposal.latest_revision_id) if proposal.latest_revision_id else None
            if previous and previous.content_hash == digest(body):
                continue
            number = previous.revision + 1 if previous else 1
            change_type = "edit"
            base_revision_hash = previous.content_hash if previous else None
        else:
            release = session.scalar(select(TaxonomyRelease).where(TaxonomyRelease.workspace_id == workspace_id)
                                     .order_by(TaxonomyRelease.created_at.desc()).limit(1))
            proposal = TaxonomyProposal(workspace_id=workspace_id, kind="label", label_id=label_id,
                                        base_release_id=release.id if release else None,
                                        base_hash=release.content_hash if release else digest({"labels": []}),
                                        created_by=user_id)
            session.add(proposal)
            session.flush()
            number, change_type, base_revision_hash = 1, "create", None
        revision = ProposalRevision(proposal_id=proposal.id, revision=number,
            name=body["name"], description=body["description"], evidence_refs=body["evidence_refs"],
            content_hash=digest(body), base_revision_hash=base_revision_hash,
            change_type=change_type, created_by=user_id)
        session.add(revision)
        session.flush()
        proposal.latest_revision_id = revision.id


@celery_app.task(name="app.queue.run_review", bind=True, ignore_result=True)
def run_review(self, job_id: str, generation: int):
    """Process one review. A duplicate, stale generation, or lost fence is a no-op."""
    claim = _claim(job_id, generation)
    if not claim:
        return {"status": "obsolete_or_not_claimable"}
    usage = {"kind": "unknown", "estimated_usd": None}
    session = SessionLocal()
    try:
        job = session.get(Job, claim["job_id"])
        batch = session.get(Batch, claim["batch_id"])
        member = session.get(BatchMember, claim["member_id"])
        revision = session.get(TaskRevision, member.task_revision_id) if member else None
        preset_model = session.get(PresetRevision, claim["preset_revision_id"])
        creator = session.get(User, batch.created_by) if batch else None
        if not job or not batch or not member or not revision or not preset_model:
            raise RuntimeError("Review job is missing its pinned input records")
        preset = {"id": preset_model.id, "preset_id": preset_model.preset_id,
                  "backend": preset_model.backend, "model": preset_model.model,
                  "reasoning": preset_model.reasoning, "budget_usd": preset_model.budget_usd,
                  "configuration": copy.deepcopy(preset_model.configuration or {})}
        preset["configuration"]["shared_labels"] = copy.deepcopy(claim["shared_labels_snapshot"])
        task_snapshot = copy.deepcopy(revision.content)
        trusted_artifacts = [{"object_key": item.object_key, "relative_path": item.relative_path,
                              "media_type": item.media_type, "sha256": item.sha256}
                             for item in session.scalars(select(StoredArtifact).where(
                                 StoredArtifact.workspace_id == claim["workspace_id"],
                                 StoredArtifact.member_id == member.id,
                                 StoredArtifact.task_revision_id == revision.id,
                                 StoredArtifact.object_key.is_not(None))).all()
                             if item.media_type not in ("application/yaml", "text/yaml")]
        replay = task_snapshot.get("review")
        snapshot_ids = {"generation": claim["generation"], "fence_token": claim["fence_token"],
                        "attempt_id": claim["attempt_id"]}
        # Leave the transaction before any slow external call.
        session.close()
        from .review_backends import execute_review
        output = execute_review(backend=preset["backend"], preset_revision=preset,
            task_snapshot=task_snapshot, review_kind=claim["review_kind"], replay_source=replay,
            trusted_artifacts=trusted_artifacts)
        review = output["review"]
        usage = output.get("usage") if isinstance(output.get("usage"), dict) else {"kind": "unknown", "estimated_usd": None}
        provenance = output.get("provenance") if isinstance(output.get("provenance"), dict) else {}
        data = yaml.safe_dump(review, sort_keys=False, allow_unicode=True).encode("utf-8")
        sha = hashlib.sha256(data).hexdigest()
        key = (f"workspaces/{claim['workspace_id']}/jobs/{job_id}/generation-{generation}/"
               f"attempt-{claim['attempt_id']}/{sha}.yaml")
        object_key = create_artifact_store(settings).put(key, data, "application/yaml")

        session = SessionLocal()
        try:
            current = session.scalars(select(Job).where(Job.id == job_id).with_for_update()).first()
            if (not current or current.generation != claim["generation"] or
                    current.fence_token != claim["fence_token"] or current.status != "running" or
                    current.lease_owner != WORKER_ID or not current.lease_expires_at or
                    as_utc(current.lease_expires_at) < utcnow()):
                # A newer generation owns the member. The immutable object is safe but unreferenced.
                return {"status": "fence_lost"}
            live_batch = session.get(Batch, current.batch_id)
            if not live_batch or live_batch.status == "cancelled":
                return {"status": "batch_cancelled"}
            current_member = session.get(BatchMember, claim["member_id"])
            latest = session.scalar(select(ReviewResult).where(ReviewResult.member_id == claim["member_id"])
                                    .order_by(ReviewResult.revision.desc()).limit(1))
            result_revision = latest.revision + 1 if latest else 1
            review_result = ReviewResult(member_id=claim["member_id"], job_id=job_id,
                revision=result_revision, review_kind=claim["review_kind"],
                schema_version=str(review.get("schema_version")) if review.get("schema_version") is not None else None,
                source_kind="saved_replay" if preset["backend"] == "saved_replay" else "generated",
                backend=preset["backend"], model=preset["model"], review=review,
                artifact_key=object_key, artifact_sha256=sha,
                provenance={**provenance, "usage": usage, "preset_revision_id": preset_model.id,
                            "taxonomy_release_id": claim["taxonomy_release_id"],
                            "taxonomy_proposal_heads": copy.deepcopy(claim["taxonomy_proposal_heads"]),
                            "shared_labels_snapshot": copy.deepcopy(claim["shared_labels_snapshot"]),
                            **snapshot_ids, "new_inference": preset["backend"] != "saved_replay"})
            session.add(review_result)
            session.add(StoredArtifact(workspace_id=claim["workspace_id"],
                task_revision_id=revision.id, member_id=claim["member_id"],
                relative_path=f"reviews/{member.task_id}/review-r{result_revision}.yaml",
                media_type="application/yaml", object_key=object_key, sha256=sha))
            _save_proposals(session, claim["workspace_id"], batch.created_by, output.get("proposals") or [])
            current.status = "completed"
            current.usage = copy.deepcopy(usage)
            value = usage.get("estimated_usd")
            current.cost_usd = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
            current.error = None
            current.lease_owner = None
            current.lease_expires_at = None
            current.updated_at = utcnow()
            current_member.status = "completed"
            attempt = session.get(JobAttempt, claim["attempt_id"])
            if attempt:
                attempt.status = "completed"
                attempt.usage = copy.deepcopy(usage)
                attempt.cost_usd = current.cost_usd
                attempt.finished_at = utcnow()
            # Keep the original cost/usage explicit. Missing provider usage is unknown, never zero.
            current_member_status = current_member.status
            _settle_batch_if_terminal(session, live_batch)
            session.commit()
            return {"status": current_member_status, "review_revision": result_revision,
                    "usage": usage, "artifact_sha256": sha}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception as exc:
        session.rollback()
        session.close()
        failure = SessionLocal()
        retry_scheduled = False
        try:
            current = failure.scalars(select(Job).where(Job.id == job_id).with_for_update()).first()
            failure_now = utcnow()
            if (current and current.generation == claim["generation"] and current.fence_token == claim["fence_token"]
                    and current.status == "running" and current.lease_owner == WORKER_ID
                    and current.lease_expires_at is not None
                    and as_utc(current.lease_expires_at) >= failure_now):
                current.error = f"{type(exc).__name__}: {str(exc)[:1200]}"
                reported_usage = getattr(exc, "usage", None)
                current.usage = copy.deepcopy(reported_usage) if isinstance(reported_usage, dict) else copy.deepcopy(usage)
                amount = current.usage.get("estimated_usd")
                current.cost_usd = amount if isinstance(amount, (int, float)) and not isinstance(amount, bool) else None
                current.lease_owner = None
                current.lease_expires_at = None
                current.updated_at = utcnow()
                attempt = failure.get(JobAttempt, claim["attempt_id"])
                if attempt:
                    attempt.status = "failed"
                    attempt.error = current.error
                    attempt.usage = copy.deepcopy(current.usage)
                    attempt.cost_usd = current.cost_usd
                    attempt.finished_at = utcnow()
                batch = failure.get(Batch, current.batch_id)
                retryable = (_retryable_failure(exc) and current.attempt_count < current.max_attempts
                             and batch is not None and batch.status in ("running", "paused"))
                retry_event = None
                if retryable:
                    retry_event = failure.scalar(select(OutboxEvent).where(
                        OutboxEvent.job_id == current.id,
                        OutboxEvent.generation == current.generation).with_for_update())
                    retryable = retry_event is not None
                member = failure.get(BatchMember, current.member_id)
                if retryable and retry_event:
                    retry_at = failure_now + _retry_delay(current.attempt_count)
                    current.status = "retrying"
                    current.available_at = retry_at
                    retry_event.status = "pending"
                    retry_event.available_at = retry_at
                    retry_event.relay_owner = None
                    retry_event.relay_lease_expires_at = None
                    if member:
                        member.status = "retrying"
                    retry_scheduled = True
                else:
                    current.status = "failed"
                    if member:
                        member.status = "failed"
                if batch:
                    _settle_batch_if_terminal(failure, batch)
                failure.commit()
        except Exception:
            failure.rollback()
            raise
        finally:
            failure.close()
        status = "retrying" if retry_scheduled else "failed"
        return {"status": status, "error": f"{type(exc).__name__}: {str(exc)[:1200]}"}


@celery_app.task(name="app.queue.recover_expired_leases", ignore_result=True)
def recover_expired_leases(limit: int = 100):
    """Fence workers whose lease expired; uncertain provider usage requires explicit review/retry."""
    session = SessionLocal()
    recovered = 0
    try:
        jobs = session.scalars(select(Job).where(Job.status == "running", Job.lease_expires_at < utcnow())
                               .order_by(Job.lease_expires_at).limit(min(max(limit, 1), 500))
                               .with_for_update(skip_locked=True)).all()
        for job in jobs:
            old_fence = job.fence_token
            job.fence_token += 1
            job.status = "failed"
            job.error = "Worker lease expired; provider usage and completion state are unknown. Retry requires an explicit action."
            job.lease_owner = None
            job.lease_expires_at = None
            job.updated_at = utcnow()
            member = session.get(BatchMember, job.member_id)
            if member:
                member.status = "failed"
            attempt = session.scalar(select(JobAttempt).where(JobAttempt.job_id == job.id,
                JobAttempt.generation == job.generation, JobAttempt.fence_token == old_fence).order_by(JobAttempt.attempt_number.desc()))
            if attempt:
                attempt.status = "lease_expired"
                attempt.error = job.error
                attempt.usage = {"kind": "unknown", "estimated_usd": None}
                attempt.finished_at = utcnow()
            job.usage = {"kind": "unknown", "estimated_usd": None}
            job.cost_usd = None
            batch = session.get(Batch, job.batch_id)
            if batch:
                _settle_batch_if_terminal(session, batch)
            recovered += 1
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
    return {"expired_leases": recovered}
