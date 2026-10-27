# Model endpoint incident deployment runbook

This runbook supplements, but does not replace, `DEPLOYMENT.md`. Production is
still on release `20260814_113548` and Alembic `0096_batch_item_consistency` at
the time this file was written. The model endpoint fix is not deployed.

## Release and migration

Build the backend and frontend from one reconciled release candidate and follow
steps 1–7 of `DEPLOYMENT.md`. Do not move either `current` symlink until both
builds, the fresh validated PostgreSQL backup, and this command succeed:

```sh
docker run --rm \
  --env-file /opt/milana-erp/shared/backend.env \
  -v /app/storage:/app/storage \
  milana-backend:<release_id> \
  sh -c 'PYTHONPATH=/app:/app/backend alembic -c /app/alembic.ini upgrade head'
```

Migration `0097_model_lookup_indexes` creates
`ix_models_legacy_status_created_id` with PostgreSQL `CREATE INDEX
CONCURRENTLY`. Verify both required model indexes from the candidate image:

```sh
docker run --rm \
  --env-file /opt/milana-erp/shared/backend.env \
  milana-backend:<release_id> \
  python - <<'PY'
from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(settings.DATABASE_URL)
with engine.connect() as conn:
    rows = conn.execute(text("""
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND indexname IN (
            'ix_models_model_group_key_id',
            'ix_models_legacy_status_created_id'
          )
        ORDER BY indexname
    """)).all()
assert len(rows) == 2, rows
for name, definition in rows:
    print(name, definition)
PY
```

If the concurrent index build is interrupted, stop and inspect
`pg_index.indisvalid`. Drop only an invalid
`ix_models_legacy_status_created_id` concurrently before retrying the
migration. Do not continue to cutover with an invalid index.

## Coordinated cutover and memory recovery

On the backend VM, record the old release, repoint the symlink, and recreate the
backend container exactly as documented. Recreating the container is required
to reclaim the workers' exhausted RSS and swap-backed pages. Do not run
`swapoff -a`.

```sh
readlink -f /opt/milana-erp/current
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

On the frontend VM, activate the exact same release and restart Next.js:

```sh
ln -sfn /opt/milana-erp/releases/<release_id> /opt/milana-erp/current
sudo systemctl restart milana-frontend
```

There is currently one backend container. If a second backend instance is
introduced, drain and recreate one instance at a time and require a healthy
replacement before touching the next.

## Post-cutover checks

Run all four required health checks from `DEPLOYMENT.md`, then confirm both VMs
resolve the same release. On the backend VM run:

```sh
readlink -f /opt/milana-erp/current
free -h
docker inspect -f '{{.Config.Image}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}' milana-backend
docker top milana-backend -eo pid,ppid,cmd
docker stats --no-stream milana-backend
ps aux --sort=-rss | head
docker logs --since 15m milana-backend 2>&1 | \
  grep -Ei 'worker.*(died|exit)|oom|killed|traceback|exception| 5[0-9][0-9] ' || true
```

Use an operator-owned authenticated cookie file without printing its contents:

```sh
ERP_COOKIE_FILE=/secure/operator/session.cookie
curl --fail --silent --show-error --cookie "$ERP_COOKIE_FILE" \
  'https://erp.milanapremium.uz/api/models?page=1&page_size=100&include_total=false' \
  -o /tmp/models-page.json
python3 - <<'PY'
import json
rows = json.load(open('/tmp/models-page.json', encoding='utf-8'))
assert isinstance(rows, list) and len(rows) <= 100
assert all('images' not in row and 'bom' not in row for row in rows)
print('model rows:', len(rows))
PY

curl --silent --show-error --cookie "$ERP_COOKIE_FILE" \
  -o /tmp/models-oversize.json -w '%{http_code}\n' \
  'https://erp.milanapremium.uz/api/models?page_size=500'
# Expected HTTP status: 422

curl --fail --silent --show-error --cookie "$ERP_COOKIE_FILE" \
  'https://erp.milanapremium.uz/api/model-options?status=approved&page=1&page_size=30' \
  -o /tmp/model-options.json
python3 - <<'PY'
import json
page = json.load(open('/tmp/model-options.json', encoding='utf-8'))
assert len(page['items']) <= 30
assert set(page['items'][0]) <= {'id', 'code', 'name', 'thumbnail_url'} if page['items'] else True
print('option rows:', len(page['items']), 'has_more:', page['has_more'])
PY
```

In signed-in UI QA, search and incrementally load approved models in Planning,
select a production order in Cutting Passports, and open a model with variants.
Refresh tabs that were open before deployment so stale Next.js Server Action
references are discarded.

For at least 30 minutes, monitor backend restart count/RSS/swap, worker-death
messages, proxy 499/502 responses, cancelled `/api/models` requests, and new
422 responses that identify overlooked oversized callers. Roll back both VMs
to the recorded prior release if health checks fail, workers restart, or new
5xx/traceback errors appear. The forward-compatible index can remain in place
during an application rollback.

## Optional guardrails after the fix is stable

Keep the current two-worker limit. Separately evaluate a modest Gunicorn/Uvicorn
`max_requests` plus jitter, container memory alerts, worker restart alerts,
swap alerts, and route latency/response-size metrics. These are defense in
depth; none replaces the bounded SQL and response projections in this fix.
