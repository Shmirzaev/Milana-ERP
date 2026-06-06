---
title: Milana ERP API
sdk: docker
app_port: 10000
---

# Milana ERP API

FastAPI backend for Milana ERP.

This folder is intended to be deployed as a Hugging Face Docker Space. Configure
the runtime secrets below, then point the Vercel frontend at the Space URL with
`NEXT_PUBLIC_API_URL` and `API_URL`.

Required production settings:

- `DATABASE_URL`
- `JWT_SECRET`
- `INITIAL_ADMIN_PASSWORD`
- `ENV=production`
- `DEBUG=false`
- `CORS_ORIGINS=https://milana-erp-web.vercel.app`
- `FRONTEND_BASE_URL=https://milana-erp-web.vercel.app`
