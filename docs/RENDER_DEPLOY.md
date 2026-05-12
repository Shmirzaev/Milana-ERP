# Milana ERP - Render One-Click Deploy

This repo is now configured for Render Blueprint deployment using `render.yaml`.
You do **not** need to manually create services or type environment variables.

## Deploy without typing configs

1. Open this link:
   - [Deploy Milana ERP on Render](https://render.com/deploy?repo=https://github.com/Shmirzaev/Milana-ERP)
2. Sign in to Render (or create an account).
3. Click **Apply** on the Blueprint screen.
4. Wait until all 3 resources are created:
   - `milana-erp-db` (PostgreSQL)
   - `milana-erp-backend` (FastAPI)
   - `milana-erp-frontend` (Next.js)
5. Open the frontend service URL after deploy is green.

## First login

- Email: `admin@example.com`
- Password: `admin12345`

## URLs after deploy

- Frontend: `https://milana-erp-frontend.onrender.com`
- Backend docs (Swagger): `https://milana-erp-backend.onrender.com/docs`
- Backend health: `https://milana-erp-backend.onrender.com/health`

## Notes

- Backend migrations and seed run automatically on each deploy.
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
