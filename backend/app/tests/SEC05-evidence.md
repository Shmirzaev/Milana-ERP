SEC05: adapted reset locking/invalidation from 3881177e and shared credential
helper from f35a62e6, excluding its unrelated runtime/proxy/body-limit changes.
All three password paths lock the User and invalidate unused reset links in the
same transaction: token reset, self-service change, administrator rotation.
Reset links belonging to other users and rejected changes remain unchanged.
Metadata-only audit records never include passwords/reset tokens.
Branch codex/sec05, freshly pulled clone_main.
SQLite fail-first: 6 failed, 4 passed, 1 optional PostgreSQL test skipped.
Fixed targeted: 10 passed, 1 skipped.
Full SQLite suite (pytest -q -n 4): 2161 passed, 47 skipped in 180.21s.
Ruff/diff checks passed. External font symlinks supplied macOS compatibility.
Logs: /private/tmp/sec05-{before,after,suite}.log.
No merge, migration, production data change or deployment.
