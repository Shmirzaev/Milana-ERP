# Milana ERP - Render One-Click Deploy

This repo is configured for Render Blueprint deployment using `render.yaml`.
You only need to provide the private `INITIAL_ADMIN_PASSWORD` value when Render prompts for it.

## Deploy without typing configs

1. Open this link:
   - [Deploy Milana ERP on Render](https://render.com/deploy?repo=https://github.com/Shmirzaev/Milana-ERP)
2. Sign in to Render (or create an account).
3. Set `INITIAL_ADMIN_PASSWORD` to a strong unique password on the Blueprint screen.
4. Click **Apply** on the Blueprint screen.
5. Wait until all 3 resources are created:
   - `milana-erp-db` (PostgreSQL)
   - `milana-erp` (FastAPI)
   - `milanaerp-frontend` (Next.js)
6. Open the frontend service URL after deploy is green.

## First login

- Email: the `INITIAL_ADMIN_EMAIL` value, defaulting to `admin@example.com`
- Password: the private `INITIAL_ADMIN_PASSWORD` value you set during deploy

## URLs after deploy

- Frontend: the `milanaerp-frontend` service URL
- Backend docs (Swagger): the `milana-erp` service URL plus `/docs`
- Backend health: the `milana-erp` service URL plus `/health`

## Notes

- Backend migrations and seed run automatically on each deploy.
- The legacy shared admin password is rejected by the API.
- Free Render instances sleep after inactivity and can be slow on first request.
- Free Render Postgres has platform limits; upgrade to paid for stable production usage.

## If you already created services manually and see Alembic errors

If logs show `No 'script_location' key found in configuration`:

1. Open backend service -> **Settings** -> **Build**.
2. Set **Root Directory** to `backend`.
3. Set **Build Command** to `pip install -r requirements.txt`.
4. Set **Start Command** to:
   - `alembic upgrade head && python -m app.db.seed && uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Save and run **Manual Deploy -> Clear build cache & deploy**.
