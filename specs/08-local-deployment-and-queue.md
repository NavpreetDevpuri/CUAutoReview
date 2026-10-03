# 8. Local deployment and the dedicated queue

**Implementation status:** The core local Compose profile is implemented with PostgreSQL, RabbitMQ/Celery and SeaweedFS's S3-compatible endpoint. See [platform status](../platform/README.md), [test results](../platform/TEST-RESULTS.md) and [fresh Docker verification](../platform/docker-quickstart-verification.json) for completed checks and limits. This specification remains the broader design target. Production HA, cloud S3 parity and sustained capacity are unverified; bounded provider checks are recorded separately in [live results](../platform/LIVE-RESULTS.md). Research references below were checked **26 September 2026**.

## Six services

| Service | Responsibility |
|---|---|
| `app` | API/built UI, permissions/evidence proxy; elected outbox/discovery/recovery loop. Production ingress; split the loop when measured load warrants. |
| `worker` | Celery stages, targeted claims, heartbeats/fenced publication; scale fixed-concurrency replicas/pools. |
| `cli-worker` | Separate Celery queue for native Codex/Gemini CLI reviews: read-only filesystem, no capabilities, memory/PID limits and one task at a time. |
| `postgres` | Metadata, permissions, jobs/outbox/attempts/quotas/results; production managed PostgreSQL with pgvector, backups and verified TLS. The local image is plain PostgreSQL 17: embeddings and vector search are not implemented yet. |
| `rabbitmq` | Persistent local broker/quorum queues; production three nodes/queue replicas across failure domains, requiring a majority. |
| `storage` | Single-process SeaweedFS with persistent volume; production Amazon S3. |

- App/worker share one image, different commands. Locally, app startup creates missing tables (`create_all`) and Compose creates the bucket; versioned schema migrations are a production prerequisite that is not implemented yet. Named volumes preserve database/broker/objects; localhost app only, infrastructure internal unless explicitly enabled.
- Health checks, bounded reconnects and graceful shutdown cover startup/recovery. One local broker demonstrates persistence, not HA. No required Redis, Beat, Flower or Celery result backend; PostgreSQL holds progress/results.
- Share stage/live/backfill queues across batches; Celery may add internal topology. Both `failure_analysis` and `pass_recovery` are enabled; unknown/error grades defer. Separate reviewer pools can protect capacity, never starve a route or silently omit passes. Pin each route's prompt/recipe/session/budget.

## Durable delivery and ownership

RabbitMQ/Celery supply transport, ACK/redelivery, routing, worker pools and backpressure. Application code supplies transactional admission, idempotency, shared quotas, scoped pause/cancel, leases and audit.

1. **Admit:** atomically commit membership/input, unique job and `outbox_event` `{job_id, stage, generation, available_at}`. Broker outage does not lose admitted work. Small JSON messages carry IDs, never screenshots/trajectories/credentials; YAML holds review/configuration artifacts.
2. **Dispatch:** lease due outbox rows briefly, publish outside SQL transactions, mark sent only after confirms and successful routing. Use persistent messages/durable quorum queues plus mandatory-return handling: confirms can acknowledge unroutable messages. A confirm-before-record crash permits duplicates.
3. **Claim:** conditionally own the delivered job ID/generation; atomically reserve worker/session capacity and record lease, attempt and new fencing token using database time. Commit before inference; never scan PostgreSQL for general ready work.
   - Completed/cancelled/obsolete messages are no-ops. ACK a duplicate with a live owner; lease recovery redispatches if necessary.
   - Each model/helper call independently enforces relevant provider concurrency/request/token/spend, workspace limits and remaining trajectory cap. One job reservation never authorizes unlimited calls.
4. **Publish:** heartbeat only the matching claim; enforce provider/stage deadlines. Write bulky artifacts to immutable attempt-specific keys. Lock/validate the current unexpired, uncancelled claim; atomically commit results/pointers, dependent jobs/outbox, quota release and completion, **then ACK**. Fence stale success, failure and retry updates.
5. **Recover:** transient failure atomically releases capacity and records retry state/new generation with future `available_at`, then ACKs. Expired leases fence owners/reclaim reservations/redispatch. Reconcile stranded work without changing logical identity. Quota/pause deferrals create one future dispatch without spending analysis attempts or busy requeueing.

- **One scheduler:** outbox `available_at`; no competing Celery `autoretry`, `retry()`, ETA/countdown or Beat. Relay `SKIP LOCKED` reserves dispatch intent, not worker delivery. Index/batch due events and bound connections.
- Queue one logical trajectory review, not a job per step. Persist validated drafts/checkpoints; resume identity/source/recipe/cursor. Checkpoints are not published complete analyses. Bound segments by broker/stage deadlines; resume through an authorized durable continuation or explicitly finalize partial coverage. Steps/helpers still obey retry/quota/spend limits.
- Passing/full-score reviews scan all compact steps, expand unresolved evidence within `pass_recovery`, and verify mistake-to-correction links. Preserve pass grade; no assumed recovery; contribution is `not_applicable`. Zero episodes set `classification_status=not_applicable`, reason `no_episodes`, with no classifier job/assignment; partial/inconclusive/abstained reviews retain their status. Rescoring creates a new evaluation/route; old batches adopt defaults through scoped, budgeted successor runs.
- **At-least-once execution, one authoritative publication.** A crash after inference can repeat billing. Up to four application attempts total (initial attempt plus three retries for retryable failures); honor provider retry hints. The local allowance is per attempt and estimates spending, not a hard provider cap. Per-trajectory spend enforcement and one bounded schema repair remain design targets. [Identity/cancellation/reuse/history](02-data-and-contracts.md).

## Broker settings and limitations

| Requirement | Contract |
|---|---|
| Quorum + confirms | Explicit declarations, Celery/Kombu `confirm_publish`, quorum detection; replication never replaces database idempotency. |
| Late ACK | `task_acks_late=True`, `task_reject_on_worker_lost=True`; commit before return/ACK. Redelivery against a live lease follows ownership/recovery rules. |
| Exception/hard timeout | Retain/reject to DLQ or recover through lease; never silently ACK unfinished work. Test `task_acks_on_failure_or_timeout=False` and actual reject/timeout behavior. Expected retries use the transaction above. |
| Prefetch | Start multiplier 1. Quorum disables global QoS; `--autoscale`/prefetch reduction behave differently. Scale fixed-concurrency replicas. |
| Poison/DLQ | Finite limit; quorum default 20 deliveries differs from four application attempts. Retain/reconcile DLQ; fix/review unchanged poison before redrive. |
| Dead lettering | Opt into `dead-letter-strategy=at-least-once`, `overflow=reject-publish`, configured exchange and durable target. Default is at-most-once. |
| ACK timeout | Default 30 minutes; configure above stage deadline plus margin. DB heartbeats do not extend it; split oversized work. |
| Fairness | Atomic PostgreSQL quotas. Celery limits are per worker; broker priority cannot enforce workspace budgets/live-backfill allocation. |

- Restricted identity/vhost, JSON-only payloads, validated task IDs; no arbitrary serialized code. Pin and test exact configurations.
- Candidates: [RabbitMQ 4.3.6](https://github.com/rabbitmq/rabbitmq-server/releases/tag/v4.3.6), [Celery 5.6.3](https://github.com/celery/celery/releases/tag/v5.6.3). [RabbitMQ image](https://hub.docker.com/v2/repositories/library/rabbitmq/tags/4.3.6-management) offers AMD64/ARM64, not evidence of tested integration.
- Sources: [broker matrix](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html), [RabbitMQ integration](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/rabbitmq.html), [configuration](https://docs.celeryq.dev/en/stable/userguide/configuration.html), [task ACKs](https://docs.celeryq.dev/en/stable/userguide/tasks.html), [quorum](https://github.com/rabbitmq/rabbitmq-website/blob/main/docs/quorum-queues/index.md), [confirms/routing](https://github.com/rabbitmq/rabbitmq-website/blob/main/docs/confirms.md), [consumer timeouts](https://github.com/rabbitmq/rabbitmq-website/blob/main/docs/consumers.md).

## Alternatives and sizing

| Option/license | Reason for decision |
|---|---|
| RabbitMQ [MPL-2.0 core](https://github.com/rabbitmq/rabbitmq-server/blob/main/LICENSE) + Celery [BSD-3-Clause](https://github.com/celery/celery/blob/main/LICENSE) | Maintained Python workers, quorum/ACK/routing/visibility. Selected for isolation/reuse; costs an outbox, one local service and three production broker nodes. |
| NATS JetStream, Apache-2.0 | [JetStream](https://docs.nats.io/nats-concepts/jetstream), not core NATS, supplies durable pull/ACK/replication and replay. No supported Celery transport; more worker integration. `MaxDeliver` leaves data plus advisory; application builds DLQ handling. Revisit for an existing NATS estate. |
| BullMQ, MIT; Redis varies | Jobs/retries/rate limits and [Python binding](https://docs.bullmq.io/python/introduction). No demonstrated advantage here. [Production](https://docs.bullmq.io/guide/going-to-production) needs persistence/`noeviction`; Pro features separate. [Redis 8](https://redis.io/legal/licenses/) offers AGPLv3/RSALv2/SSPLv1. |
| Temporal, MIT server | Python SDK; durable workflows/timers/retries/history. Useful for multi-day waits/branching, but [production operations](https://docs.temporal.io/self-hosted-guide/deployment) and deterministic replay/versioning remain extra responsibilities despite a local dev server. |
| SQS + Celery, managed AWS | Managed supported broker, but different local transport and no Celery event monitoring/remote control. [ElasticMQ](https://github.com/softwaremill/elasticmq), Apache-2.0, is an optionally persistent API subset, not AWS parity. |
| PostgreSQL + Procrastinate, PostgreSQL/MIT | Transactional enqueue, [Python workers](https://github.com/procrastinate-org/procrastinate), [`SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html) queue support. Credible fewer-service alternative; dedicated transport is a preference, not a measured PG bottleneck. |

At **10k attempts/day, 40% failures**: 4k failure + 6k pass reviews. Normalization 10k + review 10k + up to 10k classification gives **up to 30k stage jobs/day, 0.35/s**, before retries/curation/other stages. Zero-episode reviews bypass classification. This supersedes the failure-only 18k/0.21 estimate. Neither average proves scale or a PostgreSQL bottleneck; measure bursts, inference and publication load.

## Storage, configuration and migration

- [`chrislusf/seaweedfs:4.47`](https://hub.docker.com/v2/repositories/chrislusf/seaweedfs/tags/4.47) offers AMD64/ARM64. [Tagged instructions](https://github.com/seaweedfs/seaweedfs/blob/4.47/README.md): `weed mini -dir=/data`, dev credentials/bucket initialization; no separate filer/master/volume containers locally. [MinIO](https://github.com/minio/minio) is archived/unmaintained, not an unpinned default.

| Setting | Local → production |
|---|---|
| `DATABASE_URL` | `postgres` → provisioned PostgreSQL, verified TLS |
| `QUEUE_BACKEND` | `rabbitmq` in both |
| `CELERY_BROKER_URL` | AMQP `rabbitmq` → prepared endpoints/restricted credentials/verified TLS |
| `OBJECT_STORE_BACKEND` | `s3` in both |
| `S3_ENDPOINT_URL` | `http://storage:8333` → unset, AWS SDK regional endpoint |
| `S3_BUCKET`, `AWS_REGION` | Development → provisioned bucket/region |
| Credentials/addressing | Dev keys, `S3_ADDRESSING_STYLE=path` → workload IAM/SDK chain, normally `auto` |
| Models | `fixture`/local endpoint → explicit local/hosted provider/revisions |

- Test put/get/head/list and optional version reads; immutable keys/SHA-256 remain required. API compatibility does not guarantee identical features. App evidence proxy avoids browser resolution of `storage`; never rewrite signed URL hosts. Separate source/artifact credentials; host credentials enable nothing automatically.
- Completed-manifest registration + periodic listing/reconciliation works locally/AWS. SeaweedFS [API matrix](https://github.com/seaweedfs/seaweedfs/wiki/Amazon-S3-API) lacks bucket-notification configuration; notifications only accelerate discovery. Genuine S3/SQS are managed services, not Docker images; emulators are optional adapter tests.
- LocalStack needs separate [account/licensing](https://docs.localstack.cloud/aws/licensing/) and [air-gap](https://docs.localstack.cloud/aws/customization/other-installations/enterprise-image/) evaluation; it is not the offline default.
- Environment settings select prepared resources; deployment still provisions, migrates bytes/schema, applies IAM, coordinates cutover and verifies checksums. Preserve IDs/provenance and verified destination locators. Same code does not mean zero migration work.

## Offline, recovery and growth gates

- **Fixture profile:** the Compose services + examples + labeled deterministic responses; would exercise UI/import/permissions/queue/persistence, not accuracy. **Local real model:** separate text/VLM endpoint with honest identity/capability limits, not Jev equivalence. **Explicit connected mode:** hosted provider/quality experiments send data outside the machine.
  - Prefetch images/dependencies/weights; disable external connectors/hosted calls, including Jev, offline. Test blocked egress; exclude fixtures from quality claims.
- **Required drills:** both example imports; append while processing; permissions/revocation; both scored routes and unknown/error deferral; DB/object/broker persistence and S3 operations; duplicate/obsolete generations; quota deferral/lease expiry/stale success/failure; confirm/commit/ACK crash gaps; poison/DLQ; leader failure/majority loss in a separate multi-node HA profile; immutable reports and batch correction/reuse.
- **Observe:** outbox age/confirms; ready/unacked depth/oldest age; redelivery/DLQ; broker disk/memory/replication; DB latency/connections; stage errors/provider capacity/spend. [Alarms](https://github.com/rabbitmq/rabbitmq-website/blob/main/docs/alarms.md) block publishes; outbox absorbs outage. DB outage stops ownership/publication: stop/defer consumers without ACKing unfinished work, then reconcile.
- **Scale:** fixed-concurrency replicas within provider quotas, then measured stage/workspace shards. Each quorum queue has a leader; more nodes do not infinitely scale it. Preserve live/backfill fairness/age-based admission and both reviewer routes. Split the control loop only when needed. Retain recovery records, archive dispatch/attempts separately from immutable results, test DB/object backups. Broker durability neither removes database writes nor proves throughput.
