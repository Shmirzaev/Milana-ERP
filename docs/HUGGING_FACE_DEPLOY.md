# Milana ERP - Hugging Face Backend + Vercel Frontend

The supported online setup is:

- Frontend: Vercel project `milana-erp-web`
- Backend API: Hugging Face Docker Space

## Backend on Hugging Face

Create a Hugging Face Space using the contents of `backend/` as the Space
repository. The backend folder includes a Space README with:

```yaml
sdk: docker
app_port: 7860
```

The backend Dockerfile honors the Space `PORT` environment variable. The current
Space sets `PORT=7860`, so the Space metadata uses `app_port: 7860`.

Set these Space secrets or variables:

```env
DATABASE_URL=postgresql+psycopg2://...
JWT_SECRET=<strong random value>
FILE_SIGNING_SECRET=<different strong random value>
JWT_ALGORITHM=HS256
JWT_EXPIRES_MINUTES=480
INITIAL_ADMIN_EMAIL=admin@example.com
INITIAL_ADMIN_PASSWORD=<strong admin password>
SEED_DEMO_USERS=false
RUN_SEED_ON_STARTUP=true
APP_NAME=Milana ERP
ENV=production
DEBUG=false
CORS_ORIGINS=https://milana-erp-web.vercel.app
FRONTEND_BASE_URL=https://milana-erp-web.vercel.app
BARCODE_STORAGE_DIR=/app/storage/barcodes
MODEL_FILES_DIR=/app/storage/model_files
SALES_ORDER_FILES_DIR=/app/storage/sales_order_files
INTEGRATION_1C_TOKEN=<strong random value>
```

Expected backend URL:

```text
https://shmirzaev-milana-erp-api.hf.space
```

If the Space name is different, update Vercel's `NEXT_PUBLIC_API_URL` and
`API_URL` to the real `.hf.space` URL.

## Frontend on Vercel

The frontend is linked to the Vercel project `milana-erp-web`.

Set these Vercel environment variables:

```env
NEXT_PUBLIC_API_URL=https://shmirzaev-milana-erp-api.hf.space
API_URL=https://shmirzaev-milana-erp-api.hf.space
```

The Next.js proxy forwards `/api/*`, `/storage/*`, and `/health` to the
configured Hugging Face backend.

## Checks

- Backend health: `https://shmirzaev-milana-erp-api.hf.space/health`
- Backend docs: `https://shmirzaev-milana-erp-api.hf.space/docs`
- Frontend: `https://milana-erp-web.vercel.app`
