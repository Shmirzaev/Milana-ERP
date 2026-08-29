# Milana ERP API

FastAPI backend for Milana ERP.

This backend is deployed as a release-tagged Docker image on the production
backend VM. Follow the repository root `DEPLOYMENT.md`; no other production
deployment process is supported.

Required production settings:

- `DATABASE_URL`
- `JWT_SECRET`
- `FILE_SIGNING_SECRET` (different from `JWT_SECRET`)
- `INITIAL_ADMIN_PASSWORD`
- `ENV=production`
- `DEBUG=false`
- `CORS_ORIGINS=https://erp.milanapremium.uz`
- `FRONTEND_BASE_URL=https://erp.milanapremium.uz`
- `SHARED_STORE_URL=sqlite:////app/storage/shared-store.db`
- `ATTENDANCE_INTEGRATION_TOKEN` (unique high-entropy connector credential)
- `ATTENDANCE_INTEGRATION_FACTORY_CODE=MIL`
- `ATTENDANCE_PHOTOS_DIR=/app/storage/attendance_photos`

Use Redis instead of SQLite for multi-replica deployments:

- `REDIS_URL=redis://...`
