# Milana ERP

Milana ERP is the production system for a garment and textile factory. It
connects the factory's operational lifecycle:

`Sales Order -> Planning -> Cutting -> Bundle QR/barcode -> optional Printing -> Sewing -> Packaging -> Package QR/barcode -> Finished Goods -> Shipment`

The repository also contains workflows for model/PLM management, purchasing,
material and accessory inventory, branded-stock production, Besttex and Eco
Cotton, reservations, waste, payroll, finance and 1C integration, forecasting,
traceability, tasks, notifications, daily sewing reports, role management, an
MCP assistant, and a mobile scanning client.

This is an actively operated business system, not a demo or starter project.
Some security and workflow hardening remains open; consult
[Project Context](docs/PROJECT_CONTEXT.md) before making material changes.

## Technology

- Backend: Python 3.11, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, Pydantic
- Frontend: Next.js 16, React, TypeScript, Tailwind CSS, SWR
- Mobile: Expo and React Native
- AI integration: Python MCP server using the ERP's authenticated API
- Runtime and local development: Docker and Docker Compose

## Repository layout

```text
backend/          FastAPI application, business services, models, migrations, and tests
frontend/         Next.js application and translations
mcp_server/       Authenticated MCP reads and confirmed notification/task writes
mobile/ios-app/   Expo mobile and scanning client
docs/             Architecture, operations, security, and training documentation
scripts/          Operational and monitoring utilities
docker-compose.yml
DEPLOYMENT.md
```

## Local setup with Docker

Prerequisites: Docker Desktop or Docker Engine with the Compose plugin.

1. Create the local backend environment file:

   ```bash
   cp backend/.env.example backend/.env
   ```

2. In `backend/.env`, replace every placeholder credential. At minimum, use
   unique values for `JWT_SECRET`, `FILE_SIGNING_SECRET`,
   `INITIAL_ADMIN_PASSWORD`, and `INTEGRATION_1C_TOKEN`. Keep demo and sample
   data flags disabled unless you intentionally need an isolated test dataset.

3. Build and start the local stack:

   ```bash
   docker compose up --build
   ```

The local services are:

| Service | Address |
| --- | --- |
| Web application | <http://localhost:3000> |
| API and Swagger UI | <http://localhost:8000/docs> |
| API health endpoint | <http://localhost:8000/health> |
| PostgreSQL | `localhost:15432` |

The backend container applies `alembic upgrade head` before startup. The
Compose database credentials are for local development only and must never be
reused in a shared or production environment.

Stop the services with `docker compose down`. Do not add `-v` unless you
deliberately intend to delete the local PostgreSQL volume.

## Local setup without Docker

Prerequisites: Python 3.11, PostgreSQL 16 or a compatible supported version,
and Node.js 20.9 or newer.

### Backend

```bash
cd backend
python -m venv .venv
```

Activate the virtual environment:

```bash
# Linux/macOS
source .venv/bin/activate

# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

Then install, configure, migrate, and run:

```bash
python -m pip install -r requirements-dev.txt
cp .env.example .env
# Set DATABASE_URL for your local PostgreSQL instance and replace all secrets.
python -m alembic -c alembic.ini upgrade head
python -m app.db.seed
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

The seed command creates baseline departments, roles, warehouses, sewing
lines, and an initial administrator only when the required administrator
settings are supplied. Sample business records remain opt-in.

### Frontend

In another terminal:

```bash
cd frontend
npm ci
```

Create `frontend/.env.local` for local development:

```dotenv
NEXT_PUBLIC_API_URL=http://localhost:8000
API_URL=http://localhost:8000
```

Then run:

```bash
npm run dev
```

Do not copy hosted or production endpoints into local configuration unless you
are intentionally performing an authorized read-only check.

## Database migrations

The SQLAlchemy models and Alembic history must stay aligned.

```bash
cd backend
python -m alembic -c alembic.ini current
python -m alembic -c alembic.ini heads
python -m alembic -c alembic.ini upgrade head
```

Create new migrations with Alembic, review the generated SQL and downgrade
path, and test against PostgreSQL. A production migration requires a verified
backup, a clean release build, and the release procedure in
[DEPLOYMENT.md](DEPLOYMENT.md).

## Validation

The following commands mirror the GitHub Actions gates.

### Backend

```bash
cd backend
python -m pip install -r requirements-dev.txt
python -m compileall -q app
python -m pytest --cov=app --cov-report=term-missing --cov-fail-under=50 -q
python -m bandit -r app -x app/tests -q
python -m pip_audit -r requirements.txt --ignore-vuln PYSEC-2026-1325
python -m ruff check app
```

### Frontend

```bash
cd frontend
npm ci
npm audit --omit=dev
npm run lint
npm run typecheck
npm run typecheck:strict
npm run check:i18n
NEXT_PUBLIC_API_URL=https://api.example.invalid npm run build
```

For the final build command in PowerShell:

```powershell
$env:NEXT_PUBLIC_API_URL = "https://api.example.invalid"
npm run build
```

Package-specific checks:

```bash
cd mcp_server
python -m pytest -q

cd ../mobile/ios-app
npm ci
npm run typecheck
```

Dependency audit failures are release blockers unless the risk has been
reviewed and a narrow, documented exception is approved.

`PYSEC-2026-1325` is the sole approved backend exception. `python-jose`
installs ecdsa transitively, no fixed ecdsa release exists, and production
startup rejects every JWT algorithm except HS256 so the vulnerable
elliptic-curve operation is unreachable. Do not broaden this exception or
remove the HS256 enforcement without a new security review.

## Environment and security

- Never commit `.env` files, access tokens, passwords, database dumps, uploaded
  business files, generated exports, or private keys.
- Generate independent, high-entropy signing and authentication secrets for
  every environment. Do not keep example values.
- Keep `JWT_ALGORITHM=HS256`; production startup rejects other algorithms.
- Keep `SEED_DEMO_USERS`, `SEED_SAMPLE_DATA`, insecure login, and demo reset
  options disabled outside isolated development.
- Browser users authenticate through HttpOnly sessions; machine integrations
  use explicitly scoped tokens. Preserve backend authorization even when the
  frontend hides an action.
- Treat uploaded files, scanner input, payroll values, stock movements, package
  state, and shipment state as untrusted until validated server-side.
- Review [Security Runbook](docs/SECURITY_RUNBOOK.md) and the known risks in
  [Project Context](docs/PROJECT_CONTEXT.md) before changing authorization or
  a factory handoff.

## Production

Production releases are immutable, release-tagged builds with an explicit
rollback path. [DEPLOYMENT.md](DEPLOYMENT.md) is the only supported production
deployment procedure.

Do not deploy from an unreviewed local working tree, run production migrations
without a verified backup, or replace the active release before builds and
migrations pass. Vercel, Render, and Hugging Face references in older files or
history are historical and are not supported deployment procedures.

## Documentation

- [Project context and current operational state](docs/PROJECT_CONTEXT.md)
- [Production deployment procedure](DEPLOYMENT.md)
- [Architecture and trust boundaries](docs/ARCHITECTURE.md)
- [Developer guide](docs/DEVELOPER_GUIDE.md)
- [Production readiness checklist](docs/PRODUCTION_READINESS.md)
- [Security runbook](docs/SECURITY_RUNBOOK.md)
- [Disaster recovery plan](docs/DISASTER_RECOVERY.md)
- [Privacy and retention decisions](docs/PRIVACY_RETENTION.md)
- [Code review standard](docs/CODE_REVIEW.md)
- [Employee training guide](docs/EMPLOYEE_TRAINING_GUIDE.md)
- [Department training sources](docs/training/README.md)
- [MCP server guide](mcp_server/README.md)
- [Mobile client guide](mobile/ios-app/README.md)

## Contributing safely

1. Read `AGENTS.md` and the relevant sections of
   `docs/PROJECT_CONTEXT.md`.
2. Reconcile the active production release, `origin/main`, and any local
   changes in an isolated worktree.
3. Make the smallest change that satisfies the business requirement, and
   preserve unrelated work.
4. Do not create or alter production orders, stock, packages, shipments,
   users, payroll, or other business data for testing.
5. Verify both frontend visibility and backend authorization for permission
   changes.
6. Test the complete department handoff affected by a workflow change,
   including scanner, tablet, label, and language behavior where relevant.
7. Run the applicable validation gates and document unresolved risks.
8. Deploy only when explicitly authorized and only through `DEPLOYMENT.md`.
