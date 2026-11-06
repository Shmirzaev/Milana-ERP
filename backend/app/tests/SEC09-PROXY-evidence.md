SEC09-PROXY: adapted scoped proxy changes from f35a62e6, with final
0ad74a69/4fee48be empty-hop and duplicate-field handling. b926fba contains only
frontend reset-proxy timeouts and does not fit this backend-only task.
Branch codex/sec09-proxy from freshly pulled clone_main.
SQLite/ASGI fail-first: 14 failures (spoofed keys/schemes and broken hop order).
Fixed new tests: 19 passed; expanded proxy/startup/security tests: 50 passed.
First full suite: 3 failures in old implicit-trust fixtures, 2167 passed.
Fixtures now supply explicit trusted peers/CIDRs and disable implicit Uvicorn
forwarding, without weakening untrusted-peer rejection tests.
Final full SQLite suite (-n 4): 2170 passed, 46 skipped in 191.30s.
Hosted runtime must set exact TRUSTED_PROXY_CIDRS and FORWARDED_ALLOW_IPS="";
otherwise startup fails clearly. /0 trust-all and invalid/noncanonical CIDRs fail.
Ruff/diff checks passed. External fonts supplied macOS compatibility.
Logs: /private/tmp/sec09-{before,after,after-expanded,suite,suite-final}.log.
No merge, deployment or production configuration/data change.
