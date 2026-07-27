# Milana ERP Developer Guide

This guide explains how the codebase is organized, how data flows, and where to make changes safely.
It is written for engineers who are new to the project and need to ship changes quickly.

## 1. System Overview

Milana ERP is a two-part app:

1. `backend/` (FastAPI + SQLAlchemy): API, domain rules, DB writes, permissions.
2. `frontend/` (Next.js App Router): UI, page routing, API calls, language switching.

Core flow:

1. User logs in (`/api/auth/login`) and the backend sets an HttpOnly auth cookie.
2. Browser requests use `credentials: "same-origin"` through the Next.js proxy.
3. Machine/API clients may use `/api/auth/token` and send `Authorization: Bearer <token>`.
4. Backend checks the cookie or bearer token and then enforces permissions (`core/deps.py`).
5. Route handlers call models/services, commit DB, return JSON.
6. SWR refreshes UI data.

## 2. Repo Map (What each folder does)

### Backend

- `backend/app/main.py`: FastAPI app bootstrap, CORS, startup schema + seed run.
- `backend/app/api/router.py`: central API router registration.
- `backend/app/api/routes/*.py`: HTTP endpoints grouped by domain.
- `backend/app/models/*.py`: SQLAlchemy tables and relations.
- `backend/app/schemas/*.py`: request/response models (Pydantic).
- `backend/app/services/*.py`: reusable business logic (planning, production, barcodes, notifications, finance sync).
- `backend/app/core/*.py`: config, auth/security, dependency helpers, permissions.
- `backend/app/db/*.py`: DB base/session/seed/reset/hotfix utilities.
- `backend/app/tests/*.py`: pytest coverage for main flows.

### Frontend

- `frontend/src/app/login/page.tsx`: login screen.
- `frontend/src/app/(app)/layout.tsx`: authenticated shell (`Sidebar`, `Topbar`, `TasksDrawer`).
- `frontend/src/app/(app)/**/page.tsx`: feature pages.
- `frontend/src/components/*.tsx`: shared UI and navigation.
- `frontend/src/lib/api.ts`: API wrapper, cookie-backed requests, timeout handling.
- `frontend/src/lib/auth.ts`: current user hook + permission checks.
- `frontend/src/lib/i18n.tsx`: EN/RU/UZ translations.

## 3. Backend Route Guide (Where features live)

- `auth.py`: login/me.
- `admin.py`: users, roles, departments, audit logs, reset-test-data.
- `partners.py`: customers, suppliers.
- `catalog.py`: brands, collections, models, model details, approve model, model BOM/colors/sizes/images.
- `inventory.py`: items, stock, receiving, transfers, batches, warehouses.
- `sales.py`: sales orders, details, status flow, stock reserve for branded sales.
- `planning.py`: material requirements and production order creation.
- `production.py`: production orders + work orders + execution records.
- `production_extra.py`: extra production workflow helpers/assignment endpoints.
- `sewing_flows.py`: sewing line/flow management and workload visibility.
- `bundles.py`: bundle lifecycle, scan transitions, bundle label/history.
- `packages.py`: package lifecycle, scan transitions, package label/history.
- `finished_goods.py`: finished goods stock and reservation operations.
- `shipments.py`: shipment creation + package shipping/delivery flow.
- `waste.py`: waste receiving/selling/disposal workflow.
- `finance.py`: finance dashboard, invoices, payments, profitability.
- `dashboards.py`: management/planning/production/finance/waste/inventory summaries.
- `tasks.py`: task drawer CRUD, reassignment, manager broadcast mode.
- `notifications.py`: notification list/read/unread counters.
- `process_tracking.py`: unified process tracking screen data.
- `barcode.py`: barcode rendering endpoints.

## 4. Backend Data Rules

### Authentication and permissions

- Token decoding and user retrieval: `backend/app/core/deps.py`.
- Permission gate factory: `require_permissions(...)`.
- Admin wildcard: `*`.
- Sidebar and backend should stay aligned on permissions.

### Startup behavior

On backend startup (`main.py`):

1. `Base.metadata.create_all(...)` for missing tables.
2. `schema_hotfix.run(...)` for missing columns.
3. `seed()` only when `RUN_SEED_ON_STARTUP=true`.

Note: `seed()` must stay idempotent. Never write seed logic that duplicates rows each restart.

### Audit and notifications

- Use `services/audit.py` for meaningful writes and state changes.
- Use `services/notifications.py` when a workflow affects another user.

## 5. Frontend Feature Guide

### App shell

- `Sidebar.tsx`: left navigation and permission-based visibility.
- `Topbar.tsx`: global search, language, notifications, logout.
- `TasksDrawer.tsx`: personal/manager task panel.

### Search behavior

- Top search is context-aware (uses current route module).
- Pages read `?q=` and filter server-side or client-side depending on endpoint support.

### Data fetching pattern

- SWR for list/detail refresh.
- `api.ts` for all authenticated requests.
- Local component state for form draft/edit UX.

### i18n pattern

- Add keys in all three language dictionaries in `i18n.tsx`:
  - `en`
  - `ru`
  - `uz`

## 6. Page-to-API Map (Most used)

- `/sales-orders` -> `/api/sales-orders`, `/api/customers`.
- `/sales-orders/new` -> `/api/customers`, `/api/models`, `POST /api/sales-orders`.
- `/models` -> `/api/models`.
- `/models/[id]` -> `/api/models/{id}`, `/api/models/{id}/...`.
- `/planning` -> `/api/planning/...`, `/api/sales-orders`.
- `/production-orders` -> `/api/production-orders`.
- `/work-orders` -> `/api/work-orders`.
- `/bundles*` -> `/api/bundles*`.
- `/packages*` -> `/api/packages*`.
- `/inventory*` -> `/api/inventory/*`.
- `/finished-goods` -> `/api/finished-goods*`.
- `/shipments` -> `/api/shipments*`.
- `/waste` -> `/api/waste*`.
- `/finance` -> `/api/finance/*`.
- `/admin/users` -> `/api/users`, `/api/roles`, `/api/departments`.
- `/admin/departments` -> `/api/departments`.

## 7. How to Change Things Safely

### Add a new backend field

1. Update SQLAlchemy model in `models/`.
2. Add idempotent column patch in `db/schema_hotfix.py`.
3. Extend schema models in `schemas/`.
4. Update route read/write logic.
5. Update seed only if needed and idempotent.
6. Add/adjust tests.

### Add a new page feature

1. Build UI in `frontend/src/app/(app)/...`.
2. Reuse `PageHeader`, existing card/table styles.
3. Use `api.ts` calls and SWR mutate after writes.
4. Add i18n keys for EN/RU/UZ.
5. Confirm permission visibility in `Sidebar.tsx` if route is new.

### Add a new permissioned action

1. Enforce in backend route dependency (`require_permissions` or role check).
2. Add permission string to seed role map if required.
3. Gate UI buttons with `can(me, ...)`.
4. Test both allowed and denied cases.

## 8. Deployment and Runtime Notes

- The only supported production topology and release process are defined in the repository root `DEPLOYMENT.md`.
- Production uses immutable release folders, a `current` symlink, a systemd-managed frontend, and a release-tagged backend Docker image.
- Frontend and backend communicate via Next API proxy (`/api/...`) from browser.
- If a deployed change is not visible:
  1. Confirm both `/opt/milana-erp/current` symlinks point to the intended release.
  2. Hard refresh browser.
  3. Check `milana-frontend` and `milana-backend` logs.

## 9. Quick Onboarding Checklist for New Engineers

1. Read `README.md` then this file.
2. Run app locally and log in with the `INITIAL_ADMIN_EMAIL` and `INITIAL_ADMIN_PASSWORD` values from `backend/.env`.
3. Open Swagger at `/docs` and inspect route groups.
4. Trace one end-to-end flow:
   1. create sales order
   2. plan production
   3. execute work orders
   4. package and ship
5. Make a small UI change and verify build.
6. Make a small API change and verify permissions + audit log.

## 10. High-Risk Areas (Pay extra attention)

- Quantity/state transitions in production, bundles, packages.
- Stock reservation and release logic.
- Finance aggregation and invoice/payment status rules.
- Seed/hotfix startup logic (runs in production startup).
- Permission checks where manager/admin overrides exist.

---

If you are unsure where to edit a feature, start with:

1. `frontend/src/components/Sidebar.tsx` to find route/page.
2. Page file under `frontend/src/app/(app)/...`.
3. API call path in that page (`/api/...`).
4. Matching backend route under `backend/app/api/routes/...`.
