# Generic retry identity (FN06)

HTTP callers keep their existing operation `scope`, payload and optional
`Idempotency-Key` header. Package workflow callers keep their body `request_key`.
Keys retain the existing normalization and 1–128 character validation.

Authentication binds `(positive_user_id, authorized_selected_factory_code)` to
the request's SQLAlchemy `Session.info["idempotency_identity"]`, after token,
user and selected-factory validation. A keyed request without this context is
rejected. Background jobs or tests calling routes/services directly must first
call `bind_idempotency_identity(db, verified_user)`; loading a user alone does
not authenticate a session. All 28 existing HTTP replay call sites are unchanged.

The logical retry identity is:

```
(full explicit operation scope, user ID, selected factory, normalized supplied key)
```

Its database representation is:

```
digest = SHA256(UTF8(JSON(["fn06-v2", full_scope, user_id, factory_code],
                        separators=(",", ":"), ensure_ascii=True))).hexdigest()
stored scope = full_scope[:60] + ":v2:" + digest
stored key   = normalized supplied key
```

The scope is at most 128 characters. Its digest includes the entire original
scope, so scopes sharing a truncated prefix remain distinct. The existing
unique `(scope, key)` constraint now enforces caller/factory/operation isolation
without a migration. Two different users or factories can independently process
the same supplied key. Within one identity, a changed payload still returns 409.
The payload fingerprint encoding is unchanged.

Python function names do not affect identity. Workflow write and reconciliation
share an operation scope, as do shipment scanning and its response-save wrapper.
Shipment cleanup can retain its `shipments.%` selector; scan invalidation accepts
both `shipments.scan-package` and `shipments.scan-package:v2:` prefixes. Readers
requiring an exact old scope must account for the versioned namespace.

## Legacy recovery

After checking the versioned namespace, replay also checks the original exact
`(scope, supplied key)`. Legacy records are preserved, not renamed or discarded.

- A known different owner cannot occupy the authenticated caller's namespace.
  Its result is not exposed, and the caller can write its own versioned record.
- An unknown/null owner returns 409 for operator review; processing again could
  repeat an already committed operation.
- For a matching owner, the historical factory must be established by the old
  purchasing scope (`purchasing.receive:FACTORY:USER:ORDER`) or the persisted
  response's `factory_code`. Today's account assignment and the incoming payload
  are not historical factory evidence.
- A proven different factory belongs to another namespace. A matching factory
  and payload replay the original result; changed payloads return 409.
- A matching owner's record without historical factory evidence returns 409 for
  operator review. This includes old finance results without a `factory_code`;
  blindly replaying or forgetting them would be unsafe.

No historical database records are backfilled or rewritten by this change.

## Concurrent retries

On PostgreSQL, replay first takes `pg_advisory_xact_lock` using the signed first
eight SHA256 bytes of compact JSON
`["milana-idempotency-v2", stored_scope, normalized_key]`. The lock is retained
through the business writes and response storage until commit or rollback.
The waiting transaction refreshes its replay read after acquiring the lock.
Different users/factories have different lock identities. Existing business locks
and package-workflow locks remain in place and retain their acquisition order.

The real PostgreSQL regression tests use independent connections, observable
lock waits and real payments. They cover same-key replay, independent users and
factories, changed payloads, uncommitted foreign-user keys, and rollback recovery.
Set `STABILIZATION_POSTGRES_URL`, for example
`postgresql+psycopg2://postgres@localhost:5433/milana_test`, to run them. They skip
when unset and require loopback PostgreSQL. Each run uses and drops an isolated
schema. SQLite regression tests verify isolation and legacy behavior; SQLite
does not prove PostgreSQL transaction-lock behavior.
