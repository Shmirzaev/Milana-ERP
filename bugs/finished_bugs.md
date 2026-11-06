# Finished bugs: human-verified production fixes

Only move an entry here after its reviewed fix is deployed, the original failing
scenario has been checked in production, and a named human records acceptance.
Shavkat or an operator accepts business behavior; an independent engineer verifies
technical fixes. Record both when needed. An AI may move the entry after that
recorded approval; it cannot approve its own output.

Production verification uses read-only evidence or an operator's authorized real
workflow. It does not authorize creating synthetic factory data.

Retain: stable ID/title, owner, original reproduction/expected behavior, fix commit,
deployed release, relevant checks, verifier/date and verification/approval evidence.
Keep the entry concise and link long evidence. Move it; do not maintain two live
copies. If it regresses, return the same ID to [active bugs](bugs.md) and retain
the earlier verification history and new regression evidence.

No entries were newly certified or moved here during the 24 October documentation
reorganization. Historical Done/Operations done labels remain visible in the active
file's reconciliation material; they are neither erased nor silently recertified.
