# Graph Report - backend  (2026-06-20)

## Corpus Check
- 50 files · ~13,457 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 380 nodes · 893 edges · 38 communities (33 shown, 5 thin omitted)
- Extraction: 73% EXTRACTED · 27% INFERRED · 0% AMBIGUOUS · INFERRED: 240 edges (avg confidence: 0.52)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `e8d03a48`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

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
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 36|Community 36]]

## God Nodes (most connected - your core abstractions)
1. `AuthService` - 38 edges
2. `MessageResponse` - 22 edges
3. `HealthService` - 22 edges
4. `ChangePasswordRequest` - 20 edges
5. `RefreshToken` - 18 edges
6. `UserMeUpdate` - 18 edges
7. `UserService` - 18 edges
8. `UUID` - 16 edges
9. `FamilyService` - 16 edges
10. `FastAPI` - 14 edges

## Surprising Connections (you probably didn't know these)
- `FastAPI` --uses--> `CSRFMiddleware`  [INFERRED]
  main.py → app/api/middlewares/csrf.py
- `EmailSettings` --conceptually_related_to--> `app`  [AMBIGUOUS]
  app/config.py → main.py
- `FastAPI` --uses--> `MongoSession`  [INFERRED]
  main.py → app/db/mongo_session.py
- `FastAPI` --uses--> `PostgresSession`  [INFERRED]
  main.py → app/db/postgress_session.py
- `lifespan()` --calls--> `get_session`  [EXTRACTED]
  main.py → app/db/postgress_session.py

## Import Cycles
- 1-file cycle: `main.py -> main.py`
- 1-file cycle: `app/api/routes/health/health_routes.py -> app/api/routes/health/health_routes.py`
- 1-file cycle: `app/api/routes/auth/auth_service.py -> app/api/routes/auth/auth_service.py`
- 1-file cycle: `app/api/routes/user/user_service.py -> app/api/routes/user/user_service.py`

## Hyperedges (group relationships)
- **Multi-Store Health Check Flow** — health_routes_health_check_with_db, dependencies_healthservicedep, health_service_healthservice, health_service_check_postgres, health_service_check_mongodb, health_service_check_s3 [EXTRACTED 1.00]
- **Application Lifespan Startup and Teardown** — main_lifespan, mongo_session_mongosession, postgress_session_postgressession, s3_session_s3session [EXTRACTED 1.00]
- **FastAPI Dependency Injection Chain** — db_dependencies_pgsessiondep, db_dependencies_mongodbdep, db_dependencies_s3clientdep, dependencies_get_health_service, dependencies_healthservicedep [INFERRED 0.85]

## Communities (38 total, 5 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.11
Nodes (29): get_auth_service(), get_current_user(), get_family_service(), get_health_service(), get_user_service(), Validate access token from HttpOnly cookie or Authorization header., Request, UserBase (+21 more)

### Community 1 - "Community 1"
Cohesion: 0.20
Nodes (7): AsyncDatabase, db_settings, MongoSession, Establishes a connection to the MongoDB database., Provides an asynchronous generator for the MongoDB database instance., Closes the MongoDB client connection., Manages the MongoDB database connection and sessions.

### Community 2 - "Community 2"
Cohesion: 0.25
Nodes (4): AsyncSession, PostgresSession, Manages the PostgreSQL database connection and sessions., Verify the connection pool works at startup.

### Community 3 - "Community 3"
Cohesion: 0.15
Nodes (10): AuthSettings, DatabaseSettings, EmailSettings, Construct the PostgreSQL connection URL., CSRF signing secret — falls back to SECRET_KEY when unset., BaseSettings, POSTGRES_URL, router (+2 more)

### Community 4 - "Community 4"
Cohesion: 0.32
Nodes (7): _get_garage_client(), _get_mongo_db(), _get_pg_session(), AsyncDatabase, AsyncSession, BaseClient, Request

### Community 5 - "Community 5"
Cohesion: 0.38
Nodes (7): get_health_service, HealthServiceDep, health_check, health_check_with_db, check_mongodb, check_postgres, check_s3

### Community 6 - "Community 6"
Cohesion: 0.36
Nodes (5): GarageSession, Manages async Garage object-storage connections (path-style, SigV4)., FastAPI, lifespan(), connect

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (37): AsyncDatabase, AsyncSession, ChangePasswordRequest, UserBase, UUID, AuthService, EmailChangeToken, EmailVerificationToken (+29 more)

### Community 8 - "Community 8"
Cohesion: 0.31
Nodes (15): datetime, Enum, liveness_check(), Kubernetes-style liveness probe — no external dependencies., Kubernetes-style readiness probe — verifies Postgres, MongoDB, and Garage., readiness_check(), _utc_now(), DependencyStatus (+7 more)

### Community 9 - "Community 9"
Cohesion: 0.15
Nodes (12): Coding conventions, Common pitfalls, Configuration (`.env`), Dependency injection pattern, Family OS — Backend Agent Context, graphify (use every session), Health checks, Project layout (+4 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (60): Document, ExcludeFromFamilyAssets, ExcludeFromFamilyDebts, ExcludeFromFamilyExpenseLogs, ExcludeFromFamilyExpenses, ExcludeFromFamilyGoals, ExcludeFromFamilyIncomeLogs, ExcludeFromFamilyInsurances (+52 more)

### Community 11 - "Community 11"
Cohesion: 0.24
Nodes (29): clear_auth_cookies(), Shared auth cookie helpers for routes and CSRF middleware., Set access, refresh, and CSRF cookies. Returns the CSRF token used., Expire all auth-related cookies on the client., set_auth_cookies(), Response, AuthServiceDep, MessageResponse (+21 more)

### Community 21 - "Community 21"
Cohesion: 0.25
Nodes (22): AuthServiceDep, ChangePasswordRequest, MessageResponse, UserMeUpdate, UserBase, UserMeUpdate, UUID, ChangePasswordRequest (+14 more)

### Community 22 - "Community 22"
Cohesion: 0.22
Nodes (13): Request, Response, BaseHTTPMiddleware, _csrf_valid(), CSRFMiddleware, _force_logout_response(), _is_exempt(), CSRF protection middleware (double-submit cookie pattern).  Validates that state (+5 more)

### Community 23 - "Community 23"
Cohesion: 0.24
Nodes (6): MIMEMultipart, EmailService, Send emails via SMTP., Send email verification link., Send password reset link., Send email change OTP to the new address.

### Community 24 - "Community 24"
Cohesion: 0.25
Nodes (8): _get_mongo_db, _get_pg_session, _get_s3_client, MongoDBDep, PGSessionDep, S3ClientDep, get_db, get_session

## Ambiguous Edges - Review These
- `EmailSettings` → `app`  [AMBIGUOUS]
  app/config.py · relation: conceptually_related_to

## Knowledge Gaps
- **34 isolated node(s):** `@kilocode/plugin`, `AsyncSession`, `AsyncDatabase`, `BaseClient`, `AsyncSession` (+29 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **5 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **What is the exact relationship between `EmailSettings` and `app`?**
  _Edge tagged AMBIGUOUS (relation: conceptually_related_to) - confidence is low._
- **Why does `FastAPI` connect `Community 6` to `Community 0`, `Community 1`, `Community 2`, `Community 4`, `Community 8`, `Community 11`, `Community 21`, `Community 22`?**
  _High betweenness centrality (0.160) - this node is a cross-community bridge._
- **Why does `UserBase` connect `Community 10` to `Community 0`, `Community 2`, `Community 21`, `Community 7`?**
  _High betweenness centrality (0.100) - this node is a cross-community bridge._
- **Why does `AuthService` connect `Community 7` to `Community 0`, `Community 21`?**
  _High betweenness centrality (0.096) - this node is a cross-community bridge._
- **Are the 17 inferred relationships involving `AuthService` (e.g. with `Request` and `UserBase`) actually correct?**
  _`AuthService` has 17 INFERRED edges - model-reasoned connections that need verification._
- **Are the 18 inferred relationships involving `MessageResponse` (e.g. with `AuthServiceDep` and `MessageResponse`) actually correct?**
  _`MessageResponse` has 18 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `HealthService` (e.g. with `Request` and `UserBase`) actually correct?**
  _`HealthService` has 12 INFERRED edges - model-reasoned connections that need verification._