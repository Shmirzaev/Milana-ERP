# Milana ERP — Garment Manufacturing MVP

A production-ready MVP ERP for a textile/garment manufacturing company. It implements the full lifecycle from **Sales Order → Planning → Cutting → Bundle QR/Barcode → Printing → Sewing → Packaging → Package QR/Barcode → Finished Goods → Shipment**, plus **Branded Stock Production**, **Waste**, **Finance**, **Inventory**, **HR**, **Audit logs**, and **Role-based access control**.

> Stack: **FastAPI · SQLAlchemy 2 · Alembic · PostgreSQL · Pydantic · JWT · Next.js 14 · TypeScript · TailwindCSS · Docker Compose**

---

## Developer documentation

- Codebase walkthrough for new engineers: `docs/DEVELOPER_GUIDE.md`
- Hugging Face backend deployment notes: `docs/HUGGING_FACE_DEPLOY.md`
- Frontend deployment target: Vercel project `milana-erp-web`

## Quick start (Docker)

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env
# Edit backend/.env and set INITIAL_ADMIN_PASSWORD to a strong unique password.

docker compose up --build
```

When the stack is up:

| Service        | URL                              |
|----------------|----------------------------------|
| Frontend       | http://localhost:3000            |
| API (Swagger)  | http://localhost:8000/docs       |
| API (ReDoc)    | http://localhost:8000/redoc      |
| PostgreSQL     | localhost:5432 (erp / erp / erp) |

The backend container automatically runs `alembic upgrade head`, then starts uvicorn. When `RUN_SEED_ON_STARTUP=true`, it also seeds initial data.

### First admin login

The seed creates an active admin only when `INITIAL_ADMIN_PASSWORD` is set. The email defaults to `admin@example.com`, or you can change it with `INITIAL_ADMIN_EMAIL`. Shared demo/admin passwords are blocked for the admin account.

Demo role users are not created unless `SEED_DEMO_USERS=true`.

---

## Run locally without Docker

### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# point DATABASE_URL at your local Postgres
# set INITIAL_ADMIN_PASSWORD to a strong unique password
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend
```bash
cd frontend
cp .env.example .env
npm install --legacy-peer-deps
npm run dev
```

### Tests
```bash
cd backend
pip install -r requirements.txt
pytest -q
```
Tests use SQLite + the seeded dataset and cover login, model CRUD, and the full production flow (SO → planning → PO → WO → cutting + bundles → bundle scans → sewing → packaging → package + storage receive).

### 1C finance sync setup
Set `INTEGRATION_1C_TOKEN` in `backend/.env`. 1C should send that same value in `X-1C-Token` when calling `POST /api/finance/integrations/1c/sync`.

---

## Project structure

```
.
├── backend/
│   ├── alembic/                         # migrations (single initial revision creates all tables)
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_initial.py
│   ├── alembic.ini
│   ├── app/
│   │   ├── api/
│   │   │   ├── router.py                # main /api router
│   │   │   └── routes/
│   │   │       ├── auth.py, admin.py, partners.py, catalog.py, inventory.py
│   │   │       ├── sales.py, planning.py, production.py
│   │   │       ├── bundles.py, packages.py, finished_goods.py, shipments.py
│   │   │       ├── waste.py, finance.py, dashboards.py, hr.py, barcode.py
│   │   ├── core/                        # config, security, deps (auth + RBAC)
│   │   ├── db/                          # SQLAlchemy base, session, seed
│   │   ├── models/                      # SQLAlchemy 2 models
│   │   ├── schemas/                     # Pydantic request/response
│   │   ├── services/                    # business logic (production, bundles, packages, planning, …)
│   │   ├── tests/                       # pytest suite (SQLite)
│   │   └── main.py                      # FastAPI app
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── login/page.tsx
│   │   │   └── (app)/                   # authenticated layout (Sidebar + Topbar)
│   │   │       ├── page.tsx             # main dashboard
│   │   │       ├── sales-orders/
│   │   │       ├── customers/
│   │   │       ├── models/, brands/, collections/
│   │   │       ├── planning/
│   │   │       ├── production-orders/
│   │   │       ├── work-orders/[id]/{cutting,printing,sewing,packaging}
│   │   │       ├── bundles/{scan,[id]}
│   │   │       ├── packages/{scan,[id]}
│   │   │       ├── inventory/{receive,batches}
│   │   │       ├── finished-goods/, shipments/, waste/, finance/, hr/employees/
│   │   │       └── admin/{users,departments,audit-logs}
│   │   ├── components/                  # Sidebar, Topbar, AuthGate, PageHeader
│   │   └── lib/                         # api client, auth hook
│   ├── Dockerfile
│   ├── package.json, tsconfig.json, tailwind.config.js, next.config.js
│   └── .env.example
├── docker-compose.yml
├── .gitignore
└── README.md
```

---

## Database structure (overview)

40+ tables, grouped into:

* **Identity / RBAC**: `users`, `roles`, `departments`, `employees`, `audit_logs`, `notifications`
* **Partners**: `customers`, `suppliers`
* **Catalog / PLM**: `brands`, `collections`, `collection_models`, `models`, `model_images`, `model_sizes`, `model_colors`, `model_bom`
* **Inventory**: `items`, `warehouses`, `stock_batches`, `stock_movements`
* **Sales**: `sales_orders`, `sales_order_items`, `invoices`, `payments`, `shipments`, `shipment_packages`
* **Production**: `production_orders`, `production_order_items`, `work_orders`, `cutting_records`, `printing_records`, `sewing_records`, `packaging_records`, `quality_checks`
* **Tracking**: `bundles`, `bundle_scan_logs`, `packages`, `package_items`, `package_scan_logs`, `finished_goods_stock`, `stock_reservations`
* **Waste**: `waste_records`, `waste_sales`, `waste_disposal_requests`

Every business-critical write produces an `audit_logs` row.

---

## Main workflows

### A. Client order production flow

1. **Sales** creates a Sales Order (`SO-YYYY-NNNNNN`).
2. **Planning** views the Sales Order, requests material requirements (BOM × quantity × (1 + waste%)), creates a `production_orders` row with status `planning`, and generates `work_orders` for cutting, optional printing, sewing, packaging, and storage transfer.
3. **Storage** receives fabric — every `stock_batches` row also produces a `receive` `stock_movements` entry.
4. **Cutting** posts a `cutting_records` row that bumps work-order counters AND generates `bundles` (each with a unique `BND-…` number, Code128 barcode, and PNG QR). Each bundle gets a `bundle_scan_logs` `created` entry.
5. **Bundle scan flow**: send → receive transitions for Printing/Sewing. Status guards prevent invalid transitions (e.g. you can't receive at sewing without first being sent to sewing).
6. **Printing** (if required) posts a `printing_records` row.
7. **Sewing** posts a `sewing_records` row. **Rule enforced**: sewing input ≤ upstream cutting/printing passed.
8. **Packaging** posts a `packaging_records` row; **Rule enforced**: packaging input ≤ sewing passed. Then operators create `packages`. Each package has a unique `PKG-…` number, QR, Code128 barcode, and one or more `package_items` (sizes inside). Capacity defaults to 60 pcs; over-capacity or mixed-model packages require an admin override.
9. **Ready Goods Storage** scans each package barcode → `receive-storage` action transitions status to `received_in_storage` and appends a `package_scan_logs` entry.
10. **Shipment**: create a `shipments` row, add packages, then `ship` / `deliver` actions update both shipment and per-package statuses.
11. **Finance**: invoice and payment flow updates `invoices.status` automatically.

### B. Branded stock production flow

1. **Modeling** creates a model and submits for approval.
2. **Management** approves via `POST /api/models/{id}/approve` — only `status == "approved"` models can be used for branded production.
3. **Planning** creates a branded production order (`production_type=branded_stock`, no Sales Order). Generates work orders just like a client order.
4. Goods flow through Cutting → Sewing → Packaging exactly the same way, but `packages` end up in `finished_goods_stock` with a `brand_id` and `available` status.
5. **Sales** can later create a `branded_stock_sale` Sales Order. `POST /api/sales-orders/{id}/reserve-stock` iterates over each line, finds matching available FG stock, decrements `available_qty`, increments `reserved_qty`, and writes `stock_reservations`. Shortages are returned for Planning to action.

---

## API docs

Full Swagger UI is at **http://localhost:8000/docs** and ReDoc at **/redoc**. Major route groups:

* `/api/auth` — login + me
* `/api/users`, `/api/roles`, `/api/departments`, `/api/audit-logs` — admin
* `/api/customers`, `/api/suppliers` — partners
* `/api/brands`, `/api/collections`, `/api/models` — PLM
* `/api/inventory/items|stock|receive|transfer|batches|warehouses`
* `/api/sales-orders`, `/api/sales-orders/{id}/{confirm,reserve-stock}`
* `/api/planning/material-requirements/{so_id}`, `/api/planning/{create-production-order,create-branded-production}`
* `/api/production-orders`, `/api/work-orders`, `/api/cutting/records`, `/api/printing/records`, `/api/sewing/records`, `/api/packaging/records`, `/api/quality/checks`
* `/api/bundles` + `/api/bundles/{id}/{send-printing,receive-printing,send-sewing,receive-sewing,history,label}`
* `/api/packages` + `/api/packages/{id}/{receive-storage,reserve,ship,mark-delivered,mark-damaged,history,label}`
* `/api/finished-goods`, `/api/finished-goods/branded-stock`, `/api/finished-goods/reserve|release-reservation`
* `/api/shipments`, `/api/shipments/{id}/{add-package,ship,deliver}`
* `/api/waste` + receive/sell/request-disposal/disposal/approve/reject/mark-disposed
* `/api/finance/{dashboard,order-profit,branded-stock-value,waste-report,invoices,payments}`
* `/api/finance/integrations/1c/sync` (token auth via `X-1C-Token`)
* `/api/dashboard/{management,planning,production,finance,waste,inventory}`
* `/api/employees`, `/api/barcode/bundle/{no}`, `/api/barcode/package/{no}`

---

## What's completed

* **Auth** with JWT and bcrypt; OAuth2 password-form + JSON login
* **Roles & permissions** — fine-grained permission strings (`sales.orders`, `cutting.bundles`, …) with admin "*" wildcard. Sidebar and route protection use the same source of truth.
* **All 40+ database tables** (SQLAlchemy 2 typed models) with relationships and constraints
* **Alembic migrations** (single initial migration creates the full schema from metadata — easy to extend with autogen later)
* **Seed data**: 13 departments, 14 roles, 14 users (one per role), customers, suppliers, warehouses, items, fabric batches, brand + collection + approved model + BOM, sample sales order with size breakdown
* **Sales orders** (client + branded stock sale), confirm, reserve stock from FG with shortage report
* **Planning**: material requirements from BOM × waste, production-order + work-order creation
* **Cutting** posts a record AND generates `Bundle` rows with QR + Code128 barcode images stored under `/storage/barcodes/...`
* **Bundle scan flow** (created → sent_to_printing → received_printing → sent_to_sewing → received_sewing) with `bundle_scan_logs` audit trail and status guards
* **Printing / Sewing / Packaging records** with quantity guards (sewing input ≤ cutting/printing passed, packaging input ≤ sewing passed)
* **Packages** with default 60-pcs capacity, mixed-size support, QR + Code128 barcode, **admin-override** for capacity/multi-model, printable HTML labels, and per-package size breakdown. Finished packages create per-size `finished_goods_stock` rows with computed cost from BOM × latest batch cost.
* **Stock reservations** for branded-stock sales
* **Shipments** with package linkage, ship/deliver flows that update package statuses
* **Waste** lifecycle: recorded → received → (sold | pending_disposal_approval → approved → disposed)
* **Finance** dashboard: revenue, payments, branded stock value, waste cost/income, order profit
* **Dashboards** for Management / Planning / Production / Finance / Waste / Inventory
* **Audit logs** for create/update/approve/transition actions on every entity
* **Printable labels** (`/api/bundles/{id}/label`, `/api/packages/{id}/label`) — HTML with embedded QR + barcode value
* **Frontend**: 30+ pages including login, dashboard, sales orders (list/new/detail), customers, models PLM with BOM editor, brands, collections, planning, production orders (list/detail), department work-order screens (cutting/printing/sewing/packaging), bundles (list/detail/scan), packages (list/detail/scan), inventory (overview/receive/batches), finished goods, shipments, waste, finance, admin (users/departments/audit), HR.
* **Pytest** suite that exercises auth, catalog CRUD, model approval, and the full multi-step production flow with bundle and package creation.

## What should be built next (post-MVP)

* Full purchasing module (purchase requests → PO → receiving → supplier payments)
* Real barcode-scanner hardware integration (USB HID device wrapper, MQTT for shop floor)
* PDF / Excel exports of orders, invoices, shipment manifests
* Mobile-optimized scan + packing screens
* Advanced HR: attendance, overtime, operator efficiency tracking with KPIs
* Notifications via email / Slack and an in-app notification feed
* Granular stock reservation per `stock_batches` (FEFO/FIFO)
* Granular work-order assignment with shifts and sewing lines
* Multi-warehouse transfers with stock-movement reconciliation reports
* Forecasting and AI assistant for capacity / deadline risk
* Public-facing customer order portal
* Stricter Alembic migrations (per-table revisions, autogenerate) once schema stabilizes
* End-to-end Playwright tests of the frontend flow

---

## Notes on assumptions

* Generated QR images are stored as PNG files under `BARCODE_STORAGE_DIR` and served by FastAPI at `/storage/barcodes/...`. The frontend proxies the same path via Next.js rewrites — this keeps the MVP fully local and zero-cloud.
* The initial Alembic revision creates the schema from SQLAlchemy metadata for simplicity. As the schema evolves, switch to `alembic revision --autogenerate -m "..."` for proper per-change migrations.
* Cost-per-finished-piece is computed at packaging time from BOM × the latest received batch cost. For accounting-grade cost tracking, replace with WAC/FIFO over `stock_movements`.
* Permission strings are simple strings stored on `roles.permissions` (JSON list). The wildcard `*` grants all access (Admin). Extending to RBAC tables (resource × action × scope) is straightforward.
