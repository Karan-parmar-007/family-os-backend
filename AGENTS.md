# Family OS — Backend Agent Context

> **Read this file first** before changing code, adding routes, or answering architecture questions about this repo.

## What this is

**Family OS** is a FastAPI backend for a family management product. It is async-first, uses dependency injection throughout, and talks to three backing stores:

| Store | Role | Client / ORM |
|-------|------|--------------|
| **PostgreSQL** | Relational data (users, structured domain) | SQLAlchemy 2 async + SQLModel 0.0.38 + asyncpg |
| **MongoDB** | Document / flexible data | pymongo async (`AsyncMongoClient`) |
| **Garage** | Object storage | aioboto3 + boto3 (path-style + SigV4) |

There is **no AWS S3** in this project — only **Garage**. All object-storage code lives in `app/db/garage_session.py`. Never use AWS-specific APIs, virtual-hosted bucket URLs, or `list_buckets` for health checks.

## Project layout

```
backend/
├── main.py                      # FastAPI app + lifespan (startup/shutdown)
├── app/
│   ├── config.py                # pydantic-settings: DatabaseSettings, EmailSettings
│   ├── api/
│   │   ├── main_router.py       # Aggregates route modules
│   │   ├── db_dependencies.py   # Request-scoped PG / Mongo / Garage deps
│   │   ├── dependencies.py      # Service factories (e.g. HealthService)
│   │   └── routes/
│   │       ├── health/          # Liveness + readiness probes
│   │       └── user/            # User SQLModel (Postgres)
│   └── db/
│       ├── postgress_session.py # PostgresSession — async engine + sessionmaker
│       ├── mongo_session.py     # MongoSession — connect / get_db / close
│       └── garage_session.py    # GarageSession — aioboto3 client per request
├── requirements.txt
└── .env                         # Secrets — never commit
```

## Startup lifecycle (`main.py`)

1. Create `MongoSession`, `PostgresSession`, `GarageSession` wrappers.
2. `await mongo_session.connect()`
3. Verify Postgres pool with `SELECT 1`
4. Store managers on `app.state.mongo_session`, `app.state.postgres_session`, `app.state.garage_session`
5. On shutdown: close Mongo, dispose Postgres engine (Garage clients are per-request)

## Dependency injection pattern

**DB deps** (`app/api/db_dependencies.py`) pull long-lived managers from `request.app.state` and yield request-scoped handles:

| Dep | Yields | From |
|-----|--------|------|
| `PGSessionDep` | `AsyncSession` | `app.state.postgres_session.get_session()` |
| `MongoDBDep` | `AsyncDatabase` | `app.state.mongo_session.get_db()` |
| `GarageClientDep` | boto client | `app.state.garage_session.get_client()` |

One `_get_*` async generator per dep in `db_dependencies.py` — reads manager from `app.state`, yields the request-scoped handle.

Garage/boto details stay in `app/db/garage_session.py`. Services receive injected deps only — never import boto or read `db_settings` for bucket names directly.

**Service deps** (`app/api/dependencies.py`) compose DB deps into services:

- `HealthServiceDep` → `HealthService`

When adding a new feature: route → service dep → db deps → session managers.

## Health checks

| Endpoint | Purpose | Dependencies |
|----------|---------|--------------|
| `GET /health/live` | Liveness — process is up | None |
| `GET /health/ready` | Readiness — all stores reachable | Postgres, Mongo, Garage |

Readiness runs checks **in parallel** with a **5s timeout** each. Returns **503** when any dependency fails.

Garage check uses `head_bucket` on `GARAGE_BUCKET_NAME` via the injected `GarageClientDep`.

Schemas: `app/api/routes/health/health_schemas.py`.

## Configuration (`.env`)

Loaded via `pydantic-settings` in `app/config.py`:

**Postgres:** `POSTGRES_SERVER`, `POSTGRES_PORT`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`

**Mongo:** `MONGO_URI`, `MONGO_DB_NAME`

**Garage:** `GARAGE_ENDPOINT_URL`, `GARAGE_ACCESS_KEY`, `GARAGE_SECRET_KEY`, `GARAGE_BUCKET_NAME`, `GARAGE_REGION_NAME`

**Email (future):** `SMTP_*` via `EmailSettings`

## Coding conventions

- **Async everywhere** — route handlers and DB access are async.
- **SQLModel 0.0.38** — no `SQLModelConfig` import; use `table=True` and `__tablename__: ClassVar[str]`.
- **Logging over print** — `logging.getLogger(__name__)`.
- **Pydantic response models** — per route module, not raw dicts.
- **UTC timestamps** — `datetime.now(timezone.utc)`.
- **Garage client** — always via `GarageSession.get_client()`; never instantiate boto clients elsewhere.
- **Naming** — use `Garage*` / `garage_*` in our code; never `S3*` / `s3_*`.
- **Minimal diffs** — match existing structure; don't refactor unrelated code.

## Stack versions (requirements.txt)

- fastapi 0.136.3, uvicorn 0.49.0
- pydantic 2.13.4, pydantic-settings 2.14.1
- SQLAlchemy 2.0.50, sqlmodel 0.0.38, asyncpg 0.31.0
- pymongo 4.17.0, aioboto3 15.5.0, boto3 1.43.22
- alembic 1.18.4, uuid6 2025.0.1

## What's not built yet

- User CRUD routes (only `UserBase` model exists)
- Auth / JWT
- Alembic migrations wired up
- Email sending

## graphify (use every session)

If `graphify-out/graph.json` exists:

- **Before** architecture questions: `graphify query "<question>"` or `graphify explain "<concept>"`
- **After** code changes: `graphify update .` (AST-only, no LLM cost)

Read `AGENTS.md` first; graphify supplements it with live dependency paths.

## Common pitfalls

1. Naming things `S3*` — this project uses Garage only.
2. Returning HTTP 200 when readiness checks fail — must be 503.
3. Importing `SQLModelConfig` — not public in sqlmodel 0.0.38.
4. Creating DB clients outside `app.state` managers — breaks lifespan and pooling.
