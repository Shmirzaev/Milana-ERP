# OPS07 network capture checklist

This is a read-only evidence procedure, not a network change or a finding
closure. Run it only from an owner-authorized workstation on each relevant
factory/branch path. This repository task did not connect to factory or
production networks.

## Before measuring

- Name the exact site, workstation, access path (wired, Wi-Fi, or approved VPN),
  gateway, proxy, and ISP/circuit. Run separate captures for each path that is
  in scope; do not infer a branch path from a backend-host or office result.
- Coordinate a fixed time window with the network owner. Record UTC start/end,
  workstation clock source, link state, and any known maintenance or concurrent
  load. Do not change DNS, firewall, QoS/shaping, proxy, or route settings.
- Use only approved read-only targets. The normal application targets are the
  public `https://erp.milanapremium.uz/ready` and `/login`; internal targets
  `http://172.16.10.4:8000/ready` and
  `http://172.16.10.5:3000/login` are reachable only from permitted networks.
  Probe business API paths only when specifically approved, with the fixed
  signed GET request set and credentials supplied out-of-band. Never use
  uploads, POST/PUT/PATCH/DELETE, or capture business response bodies.
- Ask the network owner to provide time-matched, read-only snapshots of the
  relevant firewall/ACL, NAT, proxy, DNS and traffic-shaping/QoS rules and
  counters. Include rule identifiers, effective interface/path, timestamps,
  and export hashes; redact secrets and unrelated network inventory. Do not
  infer that a rule is absent from an application-host test.

## Capture each path

1. Record `ipconfig /all`, `route print`, and `Resolve-DnsName
   erp.milanapremium.uz -Type A` output (or the site-approved equivalents).
   Preserve DNS server and answer/TTL details; do not flush caches. Mark whether
   the client used a proxy or VPN.
2. Check the approved destination ports with `Test-NetConnection <host> -Port
   <port>`. If permitted by the network owner, capture one route trace with
   `tracert -d <host>`. A missing ICMP hop is not proof of a broken application
   path; retain the output as context, not a pass/fail gate.
3. For HTTP timing, use a serial, fixed-size capture (three unscored warm-ups,
   then 50 measured requests per target) and retain every sample and failure.
   Example for a single approved readiness target in PowerShell:

   ```powershell
   curl.exe --silent --show-error --output NUL --max-time 15 `
     --write-out "http=%{http_code} remote_ip=%{remote_ip} dns_s=%{time_namelookup} connect_s=%{time_connect} tls_s=%{time_appconnect} ttfb_s=%{time_starttransfer} total_s=%{time_total}`n" `
     https://erp.milanapremium.uz/ready
   ```

   Run the same fixed sequence once per path; do not parallelize requests or
   repeat until a passing sample appears. Use only GET/HEAD, discard response
   bodies, and do not put tokens in command history or saved output. `tls_s` is
   meaningful for HTTPS; `time_appconnect` on plain HTTP is not a TLS result.
4. Keep client/path captures paired by timestamp. Compare DNS, connect, TLS,
   first-byte and total time separately; include status, resolved/remote IP,
   sample count, failures/timeouts, median and p95. Preserve raw samples before
   calculating summaries. Do not attribute all API latency to DNS based on a
   readiness or login probe alone.
5. If capturing an application performance baseline, use the exact approved
   signed read-only endpoint set and query parameters on every path, unchanged
   result counts, ordering and payloads, and retain all raw samples. Do not
   compare different application revisions, datasets, clients, or query sets.

## Evidence record

Create one record per site/path and attach sanitized raw command output, sample
data, and owner-provided network-rule snapshots. Keep credentials and response
bodies out of the evidence bundle.

```text
site/path:
workstation and link (wired/Wi-Fi/VPN):
gateway, proxy, ISP/circuit:
capture window (UTC):
application commit/release, if applicable:
targets and fixed request set:
DNS servers, answers and TTLs:
firewall/ACL/NAT/QoS/proxy rule snapshot IDs and hashes:
sample count / warm-ups / failures:
per-target median and p95 (DNS/connect/TLS/TTFB/total):
raw-evidence filenames and hashes:
limitations or concurrent events:
network owner / review date:
```

OPS07 remains open until owners collect and review comparable captures for the
actual factory and branch paths, reconcile effective network rules, and decide
whether any network change is warranted. A successful public-path sample or
historical diagnostic alone is not whole-finding evidence.
