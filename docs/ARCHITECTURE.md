# Milana ERP Architecture

This document captures the current production shape of the system. Update it whenever deployment topology, authentication, storage, or trust boundaries change.

## System Context

```mermaid
flowchart LR
    user["ERP user"]
    browser["Browser"]
    frontend["Next.js frontend VM · 172.16.10.5"]
    api["FastAPI backend VM · 172.16.10.4"]
    db["PostgreSQL VM · 172.16.10.3"]
    storage["Backend local file storage"]
    email["Email provider or SMTP"]
    onec["1C integration client"]

    user --> browser
    browser --> frontend
    frontend -->|/api, /storage, /health via Nginx Proxy Manager| api
    api --> db
    api --> storage
    api --> email
    onec -->|X-1C-Token| api
```

## Authentication Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant F as Next.js frontend
    participant A as FastAPI backend
    participant D as Database

    B->>F: Submit login form
    F->>A: POST /api/auth/login
    A->>D: Verify user and password hash
    A-->>B: Set HttpOnly SameSite=Lax auth cookie
    B->>F: Open authenticated app route
    F->>A: GET /api/auth/me with cookie
    A->>D: Load user and role permissions
    A-->>F: User profile and permission list
```

Machine clients use `POST /api/auth/token` and send `Authorization: Bearer <token>`. Browser login does not expose the bearer token to JavaScript.

## Request Trust Boundaries

```mermaid
flowchart TB
    internet["Internet"]
    browser["Browser session"]
    proxy["Next.js rewrite proxy"]
    middleware["FastAPI middleware"]
    route["Permissioned route"]
    service["Domain service"]
    database["Database"]

    internet --> browser
    browser --> proxy
    proxy --> middleware
    middleware -->|rate limit, CORS, CSRF origin, headers| route
    route -->|CurrentUser + require_permissions| service
    service --> database
```

## Sensitive File Access

```mermaid
sequenceDiagram
    participant U as Authenticated user
    participant A as API
    participant S as File storage

    U->>A: Upload sales-order printing file
    A->>S: Save file under configured storage root
    A-->>U: Return signed URL with exp and sig
    U->>A: GET signed /storage/sales-order-files/{name}
    A->>A: Verify HMAC and expiry
    A->>S: Read file if path stays under storage root
    A-->>U: File response
```

Model files require an authenticated session. Sales-order printing attachments use short-lived signed URLs because browser image/file rendering cannot attach authorization headers.

## Audit Logging

```mermaid
flowchart LR
    write["Business write"]
    audit["log_action"]
    previous["Previous audit entry hash"]
    hash["SHA-256 current entry hash"]
    row["audit_logs row"]

    write --> audit
    previous --> hash
    audit --> hash
    hash --> row
```

Audit rows store `prev_hash` and `entry_hash`. This provides tamper evidence for changed or deleted historical rows when compared against an exported snapshot or backup.

## Current Runtime Components

- Frontend: Next.js App Router on the production frontend VM.
- Backend: FastAPI, SQLAlchemy, Alembic, deployed as a release-tagged Docker service on the production backend VM.
- The canonical topology and release procedure are defined in `DEPLOYMENT.md`.
- Database: PostgreSQL in production, SQLite only for tests.
- Auth: HttpOnly cookie for browser sessions; bearer token endpoint for machine clients.
- Authorization: role permissions stored as JSON strings with `*` as superadmin wildcard.
- Files: generated barcodes/model files/sales-order attachments in backend storage paths.
- CI: backend tests, Bandit, pip-audit, Ruff, frontend npm audit, lint, typecheck, and build.
