# Graph Report - backend  (2026-06-09)

## Corpus Check
- 24 files · ~1,793 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 140 nodes · 183 edges · 24 communities (20 shown, 4 thin omitted)
- Extraction: 81% EXTRACTED · 19% INFERRED · 1% AMBIGUOUS · INFERRED: 34 edges (avg confidence: 0.6)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 19|Community 19]]

## God Nodes (most connected - your core abstractions)
1. `HealthService` - 14 edges
2. `Family OS — Backend Agent Context` - 12 edges
3. `MongoSession` - 9 edges
4. `lifespan()` - 9 edges
5. `FastAPI` - 9 edges
6. `datetime` - 8 edges
7. `HealthStatus` - 8 edges
8. `DependencyStatus` - 8 edges
9. `PostgresSession` - 8 edges
10. `LivenessResponse` - 7 edges

## Surprising Connections (you probably didn't know these)
- `FastAPI` --uses--> `MongoSession`  [INFERRED]
  main.py → app/db/mongo_session.py
- `lifespan()` --calls--> `get_session`  [EXTRACTED]
  main.py → app/db/postgress_session.py
- `EmailSettings` --conceptually_related_to--> `app`  [AMBIGUOUS]
  app/config.py → main.py
- `FastAPI` --uses--> `GarageSession`  [INFERRED]
  main.py → app/db/garage_session.py
- `lifespan()` --calls--> `MongoSession`  [EXTRACTED]
  main.py → app/db/mongo_session.py

## Import Cycles
- 1-file cycle: `main.py -> main.py`
- 1-file cycle: `app/api/routes/health/health_routes.py -> app/api/routes/health/health_routes.py`

## Hyperedges (group relationships)
- **Multi-Store Health Check Flow** — health_routes_health_check_with_db, dependencies_healthservicedep, health_service_healthservice, health_service_check_postgres, health_service_check_mongodb, health_service_check_s3 [EXTRACTED 1.00]
- **Application Lifespan Startup and Teardown** — main_lifespan, mongo_session_mongosession, postgress_session_postgressession, s3_session_s3session [EXTRACTED 1.00]
- **FastAPI Dependency Injection Chain** — db_dependencies_pgsessiondep, db_dependencies_mongodbdep, db_dependencies_s3clientdep, dependencies_get_health_service, dependencies_healthservicedep [INFERRED 0.85]

## Communities (24 total, 4 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.17
Nodes (11): Any, get_health_service(), AsyncDatabase, AsyncSession, check_connectivity(), Verify bucket access using an injected request-scoped client., GarageClientDep, HealthService (+3 more)

### Community 1 - "Community 1"
Cohesion: 0.14
Nodes (15): DatabaseSettings, db_settings, POSTGRES_URL, _get_mongo_db, _get_pg_session, _get_s3_client, MongoDBDep, PGSessionDep (+7 more)

### Community 2 - "Community 2"
Cohesion: 0.13
Nodes (12): BaseClient, AsyncSession, GarageSession, Manages async Garage object-storage connections (path-style, SigV4)., Yields a request-scoped Garage client.         Injected via FastAPI Depends() —, PostgresSession, Provides an asynchronous session generator for database operations., Disposes of the database engine and releases all connections. (+4 more)

### Community 3 - "Community 3"
Cohesion: 0.25
Nodes (4): DatabaseSettings, EmailSettings, Construct the PostgreSQL connection URL., BaseSettings

### Community 4 - "Community 4"
Cohesion: 0.32
Nodes (7): _get_garage_client(), _get_mongo_db(), _get_pg_session(), AsyncDatabase, AsyncSession, BaseClient, Request

### Community 5 - "Community 5"
Cohesion: 0.32
Nodes (8): get_health_service, HealthServiceDep, health_check, health_check_with_db, check_mongodb, check_postgres, check_s3, HealthService

### Community 6 - "Community 6"
Cohesion: 0.22
Nodes (6): AsyncDatabase, MongoSession, Establishes a connection to the MongoDB database., Provides an asynchronous generator for the MongoDB database instance., Closes the MongoDB client connection., Manages the MongoDB database connection and sessions.

### Community 7 - "Community 7"
Cohesion: 0.50
Nodes (4): EmailSettings, router, app, main_router

### Community 8 - "Community 8"
Cohesion: 0.29
Nodes (16): BaseModel, datetime, Enum, liveness_check(), Kubernetes-style liveness probe — no external dependencies., Kubernetes-style readiness probe — verifies Postgres, MongoDB, and Garage., readiness_check(), _utc_now() (+8 more)

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (12): Coding conventions, Common pitfalls, Configuration (`.env`), Dependency injection pattern, Family OS — Backend Agent Context, graphify (use every session), Health checks, Project layout (+4 more)

## Ambiguous Edges - Review These
- `EmailSettings` → `app`  [AMBIGUOUS]
  app/config.py · relation: conceptually_related_to

## Knowledge Gaps
- **35 isolated node(s):** `python-envs.defaultEnvManager`, `python-envs.defaultPackageManager`, `AsyncSession`, `AsyncDatabase`, `BaseClient` (+30 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `EmailSettings` and `app`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `FastAPI` connect `Community 2` to `Community 0`, `Community 8`, `Community 4`, `Community 6`?**
  _High betweenness centrality (0.269) - this node is a cross-community bridge._
- **Why does `lifespan()` connect `Community 2` to `Community 1`, `Community 6`?**
  _High betweenness centrality (0.149) - this node is a cross-community bridge._
- **Why does `HealthService` connect `Community 0` to `Community 8`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Are the 5 inferred relationships involving `HealthService` (e.g. with `GarageClientDep` and `HealthService`) actually correct?**
  _`HealthService` has 5 INFERRED edges - model-reasoned connections that need verification._
- **Are the 3 inferred relationships involving `FastAPI` (e.g. with `GarageSession` and `MongoSession`) actually correct?**
  _`FastAPI` has 3 INFERRED edges - model-reasoned connections that need verification._
- **What connects `python-envs.defaultEnvManager`, `python-envs.defaultPackageManager`, `AsyncSession` to the rest of the system?**
  _48 weakly-connected nodes found - possible documentation gaps or missing edges._