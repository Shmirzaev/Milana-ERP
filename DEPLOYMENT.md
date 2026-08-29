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

Before packaging any candidate, run the production-drift gate on **both**
application VMs:

```sh
active="$(readlink -f /opt/milana-erp/current)"
cd "$active"
sha256sum -c SOURCE_MANIFEST.sha256
```

Any missing file or checksum mismatch is an automatic stop. Preserve the
actual active source trees from the backend and frontend VMs separately,
reconcile every difference into the candidate, and add a focused regression
test for the recovered behavior before continuing. If the compiled frontend
contains behavior that is absent from its source, recover that behavior into
source before rebuilding; a route-count comparison alone is not sufficient.

1. Create a UTC release ID in `YYYYMMDD_HHMMSS` format.
2. Upload the same source tree to both application VMs under
   `/opt/milana-erp/releases/<release_id>`. Verify the archive SHA-256 and a
   deterministic source-file manifest on both VMs before building. Exclude
   dependency/build output, caches, logs, live storage, real `.env` files, and
   private keys.
3. Never change either `current` symlink until the relevant build and the
   fresh database backup and database migration have completed successfully.
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
   docker image inspect milana-backend:<release_id>
   ```

6. After both builds pass, create a fresh PostgreSQL custom-format backup in
   `/opt/milana-erp/shared/backups`. Read `DATABASE_URL` without printing it
   and pass connection fields to `pg_dump --no-password` only through the
   child process environment, never command-line arguments. Write to a unique
   temporary file, require a non-empty result, atomically rename it, set mode
   `0600`, and validate it before proceeding:

   ```sh
   pg_restore --list /opt/milana-erp/shared/backups/<backup>.dump \
     > /opt/milana-erp/shared/backups/<backup>.restore.list
   test "$(grep -vc '^;' /opt/milana-erp/shared/backups/<backup>.restore.list)" -gt 100
   sha256sum \
     /opt/milana-erp/shared/backups/<backup>.dump \
     /opt/milana-erp/shared/backups/<backup>.restore.list
   ```

   Record both hashes, the dump size, and restore-object count in
   `docs/PROJECT_CONTEXT.md`.

7. Run and verify the candidate migration before either symlink moves:

   ```sh
   docker run --rm \
     --env-file /opt/milana-erp/shared/backend.env \
     -v /app/storage:/app/storage \
     milana-backend:<release_id> \
     sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head'
   docker run --rm \
     --env-file /opt/milana-erp/shared/backend.env \
     -v /app/storage:/app/storage \
     milana-backend:<release_id> \
     sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini current'
   ```

8. After the backup, builds, and migration pass, cut over the backend:

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

   The current image startup script runs Alembic once, optionally runs the
   configured seed once, disables worker-side reseeding, and then starts two
   Uvicorn workers. Do not increase `WEB_CONCURRENCY` above `2` with the
   current per-worker pool of 15 plus 10 overflow connections.

9. Cut over the frontend:

   ```sh
   ln -sfn /opt/milana-erp/releases/<release_id> /opt/milana-erp/current
   sudo systemctl restart milana-frontend
   ```

10. Verify all four endpoints:

   ```sh
   curl --fail http://172.16.10.4:8000/health
   curl --fail --head http://172.16.10.5:3000/login
   curl --fail https://erp.milanapremium.uz/health
   curl --fail --head https://erp.milanapremium.uz/login
   ```

11. Verify the active release/image, one Uvicorn parent with two workers,
    container resource use, startup logs, and PostgreSQL connection headroom:

    ```sh
    readlink -f /opt/milana-erp/current
    docker inspect -f '{{.Config.Image}}' milana-backend
    docker top milana-backend -eo pid,ppid,cmd
    docker stats --no-stream milana-backend
    docker logs --tail 200 milana-backend
    ```

    Stop and roll back if either VM points to a different release, a required
    health check fails, a worker does not start, or new 5xx/traceback errors
    appear. Complete signed-in, read-only checks for the changed workflow
    before declaring the release complete.

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
- Never edit `/opt/milana-erp/current`, a retained release folder, or `.next`
  build output in place. Emergency fixes must be packaged as a new immutable
  release so their source, manifest, build, test, and rollback evidence remain
  reproducible.
