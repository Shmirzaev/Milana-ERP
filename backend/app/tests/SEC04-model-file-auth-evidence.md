# SEC04: model file session authentication

Branch: `codex/sec04-model-file-auth`, from `clone_main` at `e808891a`.
Edited in place under real `backend/` paths.

## Donor port

Ported only the model-file authentication changes in `backend/app/main.py`
from develop commit `3881177e4d3cc661387d6591471f2641103b5987`.
Current routes had shifted line numbers, but their serving/fallback structure
matched the donor. No omnibus changes or unrelated donor files were imported.

`_require_model_file_token` now takes `CurrentUser` and `DbSession` dependencies.
The normal authentication dependency rejects disabled/deleted users and tokens
older than the credentials cutoff. The guard immediately calls `db.close()`.
Both full-file and thumbnail routes declare
`dependencies=[Depends(_require_model_file_token)]`, so authentication finishes
and its connection is returned before path lookup, image generation or streaming.
Existing short-lived DB fallback sessions are unchanged.

Model files remain company-wide. No factory, role permission or per-model
ownership restriction was added. Signed sales-attachment behavior is unchanged.

## Fail first: SQLite

Adapted the donor `test_static_file_auth.py`, independently parametrizing both
file and thumbnail routes. Added same-file access for MIL, BST and ECO users.

Original clone_main: **13 failed, 11 passed** in 26.14 seconds.
The 12 revocation cases (both routes x disabled/deleted/credentials-rotated x
cookie/bearer) returned 200 where 401 was required. An additional old-token
rotation test failed. The normal `/api/auth/me` endpoint correctly rejected
those same sessions. Thumbnail caches were warmed before revocation.

```sh
python -m pytest -q backend/app/tests/test_static_file_auth.py
```

The test also checks active sessions, invalid/expired/missing credentials,
new-token acceptance after rotation, authentication connection release before
filesystem access, signed model URLs requiring sessions, unchanged sales-link
policy and company-wide access across all three factories.

Database: normal isolated SQLite test fixtures. No PostgreSQL run.
Logs: `/private/tmp/sec04-before-both.log`, `/private/tmp/sec04-after-both.log`.
No production data, migration or deployment.

## Passing results

Fixed code: **24 passed**, 2 warnings, in 26.33 seconds.
Full existing suite: **2,175 passed, 46 skipped**, 3 warnings, in 653.39 seconds.
Both used the normal isolated SQLite fixtures.

The full suite used the same temporary external Arial/Arial Bold font symlinks
as earlier tasks on this Mac; no repository font changes were made:

```sh
cd /private/tmp/s06-suite-env
python -m pytest -q \
  -c /Users/murmurbek/Code/Milana-ERP/pyproject.toml \
  /Users/murmurbek/Code/Milana-ERP/backend/app/tests
```

Full-suite log: `/private/tmp/sec04-suite.log`.
Ruff (`backend/app`), Python compilation and `git diff --check` passed.
No merge or deployment; no production data touched.
