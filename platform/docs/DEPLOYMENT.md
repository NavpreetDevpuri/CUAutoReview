# Production deployment

This guide covers running the platform outside the local demo. It uses the same image, with `ENVIRONMENT=production`, behind an HTTPS reverse proxy. [`platform/compose.prod.yaml`](../compose.prod.yaml) implements it for a single host. The same environment variables and the same migrate step apply on any orchestrator.

## Topology

```text
browser ──HTTPS──> reverse proxy (TLS, HSTS) ──HTTP, 127.0.0.1:8000──> app (uvicorn, N workers)
                                                                     │  ├─ PostgreSQL (state, outbox, results)
migrate job (one-shot, before app) ──────────────────────────────────┘  ├─ RabbitMQ (delivery only)
worker / cli-worker (Celery) <── RabbitMQ                                └─ S3 or SeaweedFS (artifacts)
```

- **app**:
  - Serves the API and the built UI.
  - Relays the outbox to RabbitMQ.
  - Prunes expired sessions every five minutes.
  - Several uvicorn workers or replicas are safe: the outbox relay and lease recovery claim rows with `SKIP LOCKED`, and sign-up and migrations take PostgreSQL advisory locks.
- **worker** and **cli-worker** run reviews. They read the same database and object store and write only through fenced commits.
- **migrate** applies schema migrations and exits. In production the API never migrates. It checks that the database is at the release's head revision and refuses to start if it is not.

## Single-host quick start

1. Copy `platform/.env.example` to `platform/.env` and fill in every production value (see the table below). Use long random secrets, and never reuse the committed `local_*` values: the app refuses to start with them.
2. Create a SeaweedFS identity file holding the same keys as `CUAUTOREVIEW_S3_ACCESS_KEY` and `CUAUTOREVIEW_S3_SECRET_KEY`, and point `CUAUTOREVIEW_S3_IDENTITIES` at it. Make it readable only by the deploy user:
   ```json
   {"identities":[{"name":"platform","credentials":[{"accessKey":"<key>","secretKey":"<secret>"}],"actions":["Read","Write","List","Tagging"]}]}
   ```
3. Start the stack:
   ```sh
   docker compose --env-file platform/.env -f platform/compose.yaml -f platform/compose.prod.yaml up -d --build
   ```
   Compose stops with a clear message if a required variable is missing. The `migrate` service runs first. The API reports healthy only when `/api/ready` passes.
4. Point the reverse proxy at `127.0.0.1:8000` (see [TLS and proxy](#tls-and-proxy)).
5. Open the site and create the first account. In an empty workspace this account becomes the administrator, even with sign-up disabled. Everyone else is added by that administrator:
   ```sh
   curl -X POST https://review.example.com/api/users -H 'Origin: https://review.example.com' \
     -H 'Content-Type: application/json' -b 'cuautoreview_session=<admin session cookie>' \
     -d '{"name":"Ada","email":"ada@example.com","password":"<initial password>","role":"reviewer"}'
   ```
   Roles are `admin`, `manager`, `reviewer` and `viewer`. Share the initial password out of band. The UI has no account-creation screen yet.

## Environment variables

Container variables are what the image reads. In Compose, set the `CUAUTOREVIEW_*` variable shown in brackets.

| Variable | Purpose | Example | Required in production |
|---|---|---|---|
| `ENVIRONMENT` | `development` (default) or `production`; production enables the checks below and stricter defaults | `production` | Set by the override |
| `DATABASE_URL` (`CUAUTOREVIEW_DATABASE_URL`) | PostgreSQL connection | `postgresql+psycopg://review:…@db:5432/review` | Yes; SQLite and the local password are refused |
| `CELERY_BROKER_URL` (`CUAUTOREVIEW_BROKER_URL`) | RabbitMQ connection | `amqp://review:…@mq:5672/review` | Yes; `guest` and `local_broker` are refused |
| `OBJECT_STORE_BACKEND` | `s3` or `local` | `s3` | Must be `s3` |
| `S3_ENDPOINT_URL` (`CUAUTOREVIEW_S3_ENDPOINT`) | S3-compatible endpoint; empty means the bundled SeaweedFS in the override | `https://s3.eu-west-1.amazonaws.com` | For managed S3 |
| `S3_BUCKET`, `AWS_REGION` | Bucket and region | `cuautoreview-prod` | Bucket: yes |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (`CUAUTOREVIEW_S3_ACCESS_KEY` / `_SECRET_KEY`) | Object-store credentials | — | Yes; local defaults are refused |
| `PUBLIC_ORIGIN` (`CUAUTOREVIEW_PUBLIC_ORIGIN`) | Comma-separated `https://` origins users open; cookie-authenticated writes are accepted only from these | `https://review.example.com` | Yes |
| `SECURE_COOKIES` | Session cookie `Secure` flag; also enables HSTS | `true` | Must be `true` |
| `SEED_POC` | Import the bundled POC examples into a new workspace | `false` | Must be `false` |
| `AUTO_MIGRATE` | Migrate at API startup (default `true` in development, `false` in production) | `false` | — |
| `ALLOW_SIGNUP` (`CUAUTOREVIEW_ALLOW_SIGNUP`) | Self-service sign-up after the first account (default `false` in production) | `false` | — |
| `EXPOSE_API_DOCS` | Serve `/docs`, `/redoc` and `/openapi.json` (default `false` in production) | `false` | — |
| `LOG_FORMAT`, `LOG_LEVEL` (`CUAUTOREVIEW_LOG_LEVEL`) | `json` or `text` (default `json` in production); level | `json`, `INFO` | — |
| `LOGIN_MAX_FAILURES`, `LOGIN_IP_MAX_FAILURES`, `LOGIN_WINDOW_SECONDS` | Throttle limits per email+client and per client address | `5`, `50`, `900` | — |
| `SESSION_TTL_HOURS` | Session lifetime | `336` | — |
| `CUAUTOREVIEW_POSTGRES_PASSWORD`, `CUAUTOREVIEW_RABBITMQ_PASSWORD`, `CUAUTOREVIEW_S3_IDENTITIES` | Credentials for the bundled PostgreSQL, RabbitMQ and SeaweedFS (Compose override only) | — | With the override |
| `CUAUTOREVIEW_WEB_WORKERS`, `CUAUTOREVIEW_FORWARDED_ALLOW_IPS` | uvicorn workers; addresses whose `X-Forwarded-*` headers are trusted | `2`, `*` | — |
| Provider keys (`OPENAI_API_KEY`, `GEMINI_API_KEY`, …) and `ALLOW_HOSTED_INFERENCE` | Hosted model reviews, off by default | — | Only for hosted inference |

With unsafe values the API and the migrate job both exit and list every problem at once.

## Migrations

- **Running them:**
  - Migrations live in `platform/backend/app/migrations` (Alembic).
  - `python -m app.core.migrate` upgrades to head. It is safe to repeat and to run concurrently, because a PostgreSQL advisory lock serializes runs.
  - `--check` only verifies that the database is at head.
- **Older databases:** a database created by earlier releases, which had no migration history, is adopted. Its tables and columns are checked against the matching revision and stamped, not recreated. A database that matches no revision is refused.
- **Upgrade order:**
  1. Back up PostgreSQL.
  2. Run the migrate job of the new image.
  3. Roll out the API and workers.
  4. Migrations are forward-only. To roll back, restore the backup taken before the upgrade and redeploy the previous image.
- **Adding a migration:** change `app/models.py`, then from `platform/backend` run `alembic revision --autogenerate -m "describe change"`. Review the generated file. `tests/test_migrations.py` fails if migrations and models drift apart.

## TLS and proxy

Terminate TLS at the proxy and forward to `127.0.0.1:8000`. The override trusts `X-Forwarded-For` and `X-Forwarded-Proto` from any peer because the API port is published on loopback only. Login throttling keys on the client address, so the proxy must overwrite `X-Forwarded-For` rather than append to it:

```nginx
server {
    listen 443 ssl;
    server_name review.example.com;
    client_max_body_size 45m;            # ZIP imports allow up to 32 MB; the API caps bodies at 40 MB
    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Request-ID $request_id;
        proxy_read_timeout 120s;
    }
}
```

If the API port is reachable from anywhere other than the proxy, set `CUAUTOREVIEW_FORWARDED_ALLOW_IPS` to the proxy's address.

## Scaling

- **API:** raise `CUAUTOREVIEW_WEB_WORKERS`, or run more app replicas behind the proxy. Each replica relays the outbox safely.
- **Reviews:** scale `worker` replicas and Celery `--concurrency`. Keep `cli-worker` at one task per container.
- **Real limits:** provider rate and spend limits usually bind before infrastructure does. PostgreSQL is the next constraint; see the scale table in the [system design](../../docs/DESIGN.md#8-scale-reliability-and-cost).

## Backups and restore

- **PostgreSQL:** use managed point-in-time recovery, or a scheduled `pg_dump --format=custom` copied off the host. Test a restore regularly.
- **Objects:** enable bucket versioning, plus replication for S3. For the bundled SeaweedFS, snapshot the `storage-data` volume.
- **Why the order matters:** artifacts use immutable keys referenced from the database. An object-store copy at least as new as the database backup restores consistently.
- **Restore steps:**
  1. Stop app and workers.
  2. Restore PostgreSQL, then the objects.
  3. Run `migrate --check`; run `migrate` if the image is newer.
  4. Start the stack.

## Observability

- **Logs:**
  - One JSON object per line on stdout, with `ts`, `level`, `logger`, `message` and `request_id`.
  - Access lines (`cuautoreview.access`) add method, path, status, duration, user id and client address.
  - Cookies, passwords, tokens and request bodies are never logged. Worker logs use the same format.
- **Request ids:** the API accepts `X-Request-ID` from the proxy, or generates one. It returns the id on every response and adds it to every log line from that request.
- **Probes:**
  - `GET /api/health` is liveness and checks no dependencies.
  - `GET /api/ready` is readiness: database reachable, schema at head, object store reachable. It returns 503 and a per-component status word on failure.
- **Alert on:**
  - readiness failures
  - failed or retrying jobs
  - outbox events waiting longer than a few minutes
  - bursts of 429 responses on `/api/auth/login`
  - disk use on the database and object store

## Security checklist

- Production checks pass: the API starts. Secrets come from a secret store, and `platform/.env` is never committed.
- TLS is enforced at the proxy, `PUBLIC_ORIGIN` is set and `SECURE_COOKIES=true`, which also sends HSTS.
- Self-service sign-up is off, and accounts are created by an administrator.
- Login throttling is active, and the proxy overwrites `X-Forwarded-For`.
- `EXPOSE_API_DOCS=false`, and only the API port is published, on loopback.
- Database and bucket backups are tested. Provider keys are present only if hosted inference is enabled.
- Every response carries a strict Content-Security-Policy, `X-Frame-Options: DENY`, `nosniff`, a referrer policy and `Cache-Control: no-store` for API responses.

## Not covered yet

- Single sign-on (OIDC/SAML).
- Account-creation and password-reset screens in the UI, and multi-factor authentication.
- High availability for RabbitMQ and PostgreSQL. Use a three-node quorum broker and managed PostgreSQL.
- Autoscaling, and metrics/tracing export (for example OpenTelemetry).
- Load and failover testing. Throughput and cost at scale remain unmeasured.
