# Returned split label correction

Owner request: edit returned divided labels, preserve payroll history, test and
deploy without timed 30-minute monitoring. Refactoring remains untouched.
Payroll ownership: Dilmurod (engineer), Mirshoir (reviewer), Shavkat (operator
acceptance). Implementation is Codex; independent AI review is technical evidence,
not human acceptance.

The existing manager-only split-allocation operation gains a returned mode.
Returned available children can change pieces, operation and rate. They remain
unassigned until normal scanning. Scanned siblings are read-only. Every child is
submitted exactly once and the original total is conserved. Historical earnings,
employee snapshots, return history and QR identities remain unchanged, including
history in closed periods. Normal scanning creates the next earning under its
existing period rules. Stale, nested, inconsistent, wrong-factory and unauthorized
requests refuse atomically; retries do not append another audit.

No schema migration or production data repair. A new manager-only GET print
operation renders the same group with current assignments and existing QR tokens.
Verification and deployment results will be recorded here before handoff.

Preparation: 84 focused API/print/scanning cases and 40 real PostgreSQL race cases
pass with zero skips. Independent technical review found and verified fixes for
print fitting CSP and blank/padded read-only historical operation names. A
disposable actual-source fault rewrote historical payroll notes: the history
fingerprint test failed, then passed after restoring the exact helper bytes.
Production build, lint and strict types pass; full backend and exact-commit CI
remain release gates. Local real-page save/reopen proves 53/52 -> 60/45 while all
historical payroll columns and QR/return identities stay unchanged.
