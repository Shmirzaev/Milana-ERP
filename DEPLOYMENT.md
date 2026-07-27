# Milana ERP Production Deployment Rule

This is the only supported production deployment procedure for Milana ERP.
No alternative production deployment process is supported.

## Production topology

- Public domain: `https://erp.milanapremium.uz`
- PostgreSQL VM: `172.16.10.3`
- FastAPI backend VM: `172.16.10.4`
- Next.js frontend VM: `172.16.10.5`
- Nginx Proxy Manager routes the domain to `172.16.10.5:3000` and routes
  `/api`, `/storage`, and `/health` to `172.16.10.4:8000`.
- Releases: `/opt/milana-erp/releases/<YYYYMMDD_HHMMSS>`
- Current release: `/opt/milana-erp/current`
- Backend environment: `/opt/milana-erp/shared/backend.env`
- Frontend environment: `/opt/milana-erp/shared/frontend.env`
- Persistent backend storage: host `/app/storage`, mounted at `/app/storage`
- Backend container: `milana-backend`
- Backend image: `milana-backend:<release_id>`
- FastAPI listens on container port `10000`, published as VM port `8000`.

## Required release process

1. Create a UTC release ID in `YYYYMMDD_HHMMSS` format.
2. Upload the same source tree to both application VMs under
   `/opt/milana-erp/releases/<release_id>`.
3. Never change either `current` symlink until the relevant build and the
   database migration have completed successfully.
4. On the frontend VM:

   ```sh
   cd /opt/milana-erp/releases/<release_id>/frontend
   npm ci --legacy-peer-deps --include=dev
   set -a
   . /opt/milana-erp/shared/frontend.env
   set +a
   npm run build
   ```

5. On the backend VM:

   ```sh
   cd /opt/milana-erp/releases/<release_id>/backend
   docker build -t milana-backend:<release_id> .
   docker run --rm \
     --env-file /opt/milana-erp/shared/backend.env \
     -v /app/storage:/app/storage \
     milana-backend:<release_id> \
     sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head'
   ```

6. After both builds and the migration pass, cut over the backend:

   ```sh
   ln -sfn /opt/milana-erp/releases/<release_id> /opt/milana-erp/current
   docker rm -f milana-backend || true
   docker run -d \
     --name milana-backend \
     --restart unless-stopped \
     --env-file /opt/milana-erp/shared/backend.env \
     -p 8000:10000 \
     -v /app/storage:/app/storage \
     milana-backend:<release_id>
   ```

7. Cut over the frontend:

   ```sh
   ln -sfn /opt/milana-erp/releases/<release_id> /opt/milana-erp/current
   sudo systemctl restart milana-frontend
   ```

8. Verify all four endpoints:

   ```sh
   curl --fail http://172.16.10.4:8000/health
   curl --fail --head http://172.16.10.5:3000/login
   curl --fail https://erp.milanapremium.uz/health
   curl --fail --head https://erp.milanapremium.uz/login
   ```

## Rollback

Select the previous working folder in `/opt/milana-erp/releases`, repoint both
`current` symlinks, restart `milana-frontend`, and recreate `milana-backend`
from the previous release-tagged image with `-p 8000:10000`. Database rollback
is not automatic; prefer forward-compatible migrations and a corrective release.

## Safety requirements

- Never store SSH, database, JWT, signing, or application passwords in Git.
- Never upload local `.env` files; production uses the shared environment files.
- Do not delete the previous working release during a deployment.
- Do not reuse an untagged backend image for production.
- Do not expose FastAPI port `10000` directly on the VM; publish `8000:10000`.
