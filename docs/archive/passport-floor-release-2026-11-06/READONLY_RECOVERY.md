# Read-only recovery restriction, 6 November 2026

Live release is green `20261106_061725` / `a8579e64efbb2f9545d6df1c35d527c1d4ae2f01`.
Compatible degraded read-only source/images are retained on blue
`20261106_054000` / `bf9cb9f0e738e82b9a21909b22e4cdecae7bed37`.
See the [release record](../../COMBINED_PASSPORT_FLOOR_RELEASE_20261106.md).

Business storage and PostgreSQL stay read-only, seed/sync stay disabled, and two
workers share a separate private writable SQLite operational counter directory.
Login locks and rate limits remain enabled. SQLite was cloned through its online
backup API with a `mode=ro` source, preserving committed WAL rows, namespace,
values and absolute expiry. This retained copy is a rehearsal snapshot.

**Do not run the old frozen `activate-readonly-backend` action directly.** Its
previous approval is superseded for counter continuity. Neither reviewed
supplement offers an activation phase. No automatic fallback is configured.
Plain writable 488 must not return after new grouped/Eco/rejection facts exist.

Emergency activation needs a separately reviewed, hash-approved root procedure:

1. Acquire and verify the normal owned deployment lease. Validate exact green
   and compatible blue IDs/images/labels/loopback ports, both roles' allowed
   source/router/control state, source inode/path and operational mounts. Preserve
   the first attempt and complete pre-action evidence. Do not overwrite a foreign
   lease or replay an uncertain action.
2. Stop exact inactive blue, then stop exact serving green to quiesce auth/rate
   writes. This deliberately introduces brief downtime. Preserve source files,
   container identities and router selection. Do not claim a live copy alone
   gives zero-loss security-counter continuity.
3. Open authoritative `/app/storage/shared_store.sqlite3` using SQLite URI
   `mode=ro` and online backup. Create a fresh private operational directory,
   preserving complete schema/key/value/expiry rows and effective
   `SHARED_STORE_KEY_PREFIX`, without logging keys or values. Verify integrity
   and source device/inode. Never raw-copy SQLite/WAL files, set `immutable=1`,
   clear counters or initialize an empty replacement security store.
4. Recreate only the exact stopped blue with its approved immutable digest and
   fresh counter RW mount. Keep `/app/storage:ro`, `INCIDENT_READ_ONLY=true`,
   seed/sync=false, two workers and pool 8+4. Derive UID/GID from the retained
   image or previously validated evidence if green is stopped; the normal
   retention-only wrapper requires green to be running and is not this emergency
   procedure. Original validated runtime UID/GID were 1000:1000.
5. Verify strict startup 0154, both workers, read-only health/header, PostgreSQL
   default/transaction read-only settings, unsafe HTTP 503 and signed read-only
   auth/passport facts without business mutation. Distinguish intentional
   read-only 503 probe access logs from unexpected startup/server failures;
   the old generic health helper rejects all 5xx and is not sufficient unchanged.
6. Apply a new CAS against stopped owned green and refreshed healthy blue, then
   activate backend blue and update `current`. Continue compatible frontend
   recovery or explicitly validated degraded baseline-frontend recovery. Run
   immediate four-health, public Edge/signed read and strict fixed-identity
   performance checks. Record the refreshed identities and actual result.

If a guard fails, investigate while keeping writes blocked. Do not activate a
stale counter clone or writable 488. No incident recovery activation is claimed
by the normal deployment's passing retention tests. The owner waived timed
observation; this does not waive immediate recovery checks. Human acceptance of
the feature release remains separate.
