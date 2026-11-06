#!/usr/bin/env python3
"""Read-only production capacity/workload evidence; no configuration changes."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit


def command(args, timeout=20):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"exit_code": -1, "output": "", "error": str(error)}
    return {"exit_code": result.returncode, "output": result.stdout.strip(), "error": result.stderr.strip()}


def postgres_snapshot():
    # Catalog and aggregate statistics only. Query text and business rows are excluded.
    sql = """BEGIN READ ONLY; SET LOCAL statement_timeout = '5s';
    SELECT json_build_object(
      'utc', clock_timestamp(),
      'settings', (SELECT json_object_agg(name, setting) FROM pg_settings WHERE name IN
        ('max_connections','superuser_reserved_connections','reserved_connections','shared_buffers',
         'work_mem','maintenance_work_mem','max_worker_processes','max_parallel_workers',
         'archive_mode','synchronous_commit','max_wal_senders','wal_level','logging_collector')),
      'clients', (SELECT coalesce(json_agg(c), '[]'::json) FROM (
        SELECT datname, usename, application_name, client_addr::text, backend_type, state,
          wait_event_type, wait_event, count(*) AS connections,
          max(extract(epoch FROM clock_timestamp()-xact_start)) AS max_transaction_age_seconds
        FROM pg_stat_activity WHERE pid <> pg_backend_pid()
        GROUP BY datname,usename,application_name,client_addr,backend_type,state,wait_event_type,wait_event
      ) c),
      'roles', (SELECT coalesce(json_agg(r), '[]'::json) FROM (
        SELECT rolname,rolconnlimit,rolcanlogin,rolsuper FROM pg_roles WHERE rolcanlogin
      ) r),
      'databases', (SELECT coalesce(json_agg(d), '[]'::json) FROM (
        SELECT d.datname,pg_get_userbyid(d.datdba) AS owner,d.datconnlimit,
          pg_database_size(d.datname) AS bytes,s.numbackends,s.xact_commit,s.xact_rollback,
          s.blks_read,s.blks_hit,s.deadlocks,s.temp_bytes,s.blk_read_time,s.blk_write_time,s.stats_reset
        FROM pg_database d LEFT JOIN pg_stat_database s ON s.datid=d.oid WHERE NOT d.datistemplate
      ) d),
      'archiver', (SELECT row_to_json(a) FROM (
        SELECT archived_count,last_archived_time,failed_count,last_failed_time,stats_reset FROM pg_stat_archiver
      ) a),
      'replication', (SELECT coalesce(json_agg(r), '[]'::json) FROM (
        SELECT application_name,client_addr::text,state,sync_state,write_lag,flush_lag,replay_lag
        FROM pg_stat_replication
      ) r)
    ); ROLLBACK;"""
    result = command(["sudo", "-u", "postgres", "psql", "-X", "-A", "-t", "-d", "postgres", "-c", sql])
    if result["exit_code"]:
        return result
    body = result["output"]
    return json.loads(body[body.index("{"):body.rindex("}")+1])


def container_inventory():
    listed = command(["docker", "ps", "-aq"])
    if listed["exit_code"] or not listed["output"]:
        return listed
    inspected = command(["docker", "inspect", *listed["output"].split()])
    rows = []
    for item in json.loads(inspected["output"]):
        env = dict(v.split("=", 1) for v in item["Config"].get("Env", []) if "=" in v)
        row = {"name": item["Name"].lstrip("/"), "image": item["Config"]["Image"],
               "state": {k: item["State"].get(k) for k in ("Status", "Pid", "StartedAt", "OOMKilled")},
               "restarts": item["RestartCount"],
               "limits": {k: item["HostConfig"].get(k) for k in
                          ("Memory", "MemorySwap", "NanoCpus", "CpuQuota", "CpuPeriod", "PidsLimit")},
               "pool": {k: env[k] for k in ("DB_POOL_SIZE", "DB_MAX_OVERFLOW", "DB_POOL_TIMEOUT",
                                            "DB_POOL_RECYCLE", "WEB_CONCURRENCY") if k in env}}
        if env.get("DATABASE_URL"):
            # Some other workloads contain unescaped reserved characters in passwords.
            # Strip userinfo before URL parsing and never emit parsing errors or secrets.
            raw = env["DATABASE_URL"]
            scheme, _, remainder = raw.partition("://")
            userinfo, sep, address = remainder.rpartition("@")
            parsed = urlsplit(scheme + "://" + (address if sep else remainder))
            try:
                port = parsed.port
            except ValueError:
                port = None
            row["database_client"] = {"host": parsed.hostname, "port": port,
                                       "database": parsed.path.lstrip("/"),
                                       "role": userinfo.partition(":")[0] if sep else None}
        args = (item["Config"].get("Entrypoint") or []) + (item["Config"].get("Cmd") or [])
        row["declared_worker_flags"] = [args[i+1] for i, arg in enumerate(args[:-1])
                                         if arg in ("--workers", "-w")]
        # Never emit the complete environment, commands, labels or connection URL.
        rows.append(row)
    return rows


def cron_inventory():
    records = []
    paths = [Path("/etc/crontab"), *Path("/etc/cron.d").glob("*"),
             *Path("/var/spool/cron/crontabs").glob("*")]
    for path in paths:
        if not path.is_file():
            continue
        for line in path.read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", line):
                continue
            parts = line.split()
            count = 1 if parts[0].startswith("@") else 5
            system = path.parent == Path("/etc/cron.d") or path == Path("/etc/crontab")
            executable_index = count + int(system)
            records.append({"source": str(path), "schedule": " ".join(parts[:count]),
                            "account": parts[count] if system else path.name,
                            "executable": parts[executable_index] if len(parts) > executable_index else None})
    return records


def capture(role, duration, interval):
    now = datetime.now(timezone.utc).isoformat()
    result = {"started_at": now, "role": role, "host": command(["hostname"]),
              "scope": "read-only catalogs, aggregate statistics, limits and schedules",
              "owner_of_erp_ops02_ops03": "Ismail", "other_workload_human_owners": "require operator confirmation",
              "memory": command(["free", "-m"]), "filesystems": command(["df", "-PT"]),
              "services": command(["systemctl", "list-units", "--type=service", "--state=running", "--no-pager"]),
              "timers": command(["systemctl", "list-timers", "--all", "--no-pager"]),
              "cron": cron_inventory(), "containers": container_inventory(), "samples": []}
    start = time.monotonic()
    while True:
        sample = {"utc": datetime.now(timezone.utc).isoformat(),
                  "load": Path("/proc/loadavg").read_text().strip(),
                  "cpu": Path("/proc/stat").read_text().splitlines()[0],
                  "disk_io": Path("/proc/diskstats").read_text(),
                  "processes": command(["ps", "-eo", "user,comm,%cpu,%mem,rss", "--sort=-%cpu"]),
                  "container_stats": command(["docker", "stats", "--no-stream", "--format",
                                               "{{.Name}} | {{.CPUPerc}} | {{.MemUsage}} | {{.PIDs}}"])}
        if role == "database":
            sample["postgres"] = postgres_snapshot()
        result["samples"].append(sample)
        remaining = duration - (time.monotonic() - start)
        if remaining <= 0:
            break
        time.sleep(min(interval, remaining))
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["peak_window_confirmed"] = False
    result["acceptance_limit"] = "Operator-confirmed peak traffic, workload ownership, resource and backup evidence are required for closure."
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--role", choices=("backend", "frontend", "database"), required=True)
    parser.add_argument("--duration", type=int, default=600)
    parser.add_argument("--interval", type=int, default=5)
    args = parser.parse_args()
    if args.duration < 0 or args.duration > 3600 or args.interval < 1:
        parser.error("duration must be 0..3600 seconds and interval at least 1 second")
    print(json.dumps(capture(args.role, args.duration, args.interval), indent=2))
