# Purchasing pricing authorization rollout (API06)

Purchasing pricing now requires the stored `price_calculation.purchasing`
permission (or an effective administrator wildcard). Role grants, per-user
extra permissions and per-factory policy grants remain supported. Explicit
policy denials continue to win. Profile name and email no longer grant access.

No schema migration is needed. There is intentionally no automatic grant
backfill: repository context identifies the historical operator only by a
mutable display name, which cannot distinguish that account from an attacker.
Backfilling every matching name/email would permanently preserve the exploit.

Before deployment, an authorized administrator must independently verify the
intended purchaser's immutable account ID using trusted personnel/account
records, then grant `price_calculation.purchasing` through the existing user
access editor for the intended factory. Preserve all unrelated grants and
explicit denials. Do not select recipients solely by their current name or
email prefix. Confirm the verified account can read/update purchasing requests
and an ordinary account cannot after changing its profile name/email.

Accounts already holding explicit effective grants retain access. Accounts
relying only on the removed name/email shortcut lose it until deliberately
authorized. This change performs no production mutation or deployment.
