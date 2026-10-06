"""Plan, apply or roll back PostgreSQL role admission budgets; no business writes.

Run as postgres on the database VM (peer authentication) or specify a local
psql command for testing. Default is read-only planning. Application and server
restart, password changes and session termination are deliberately absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def validate_policy(policy: dict) -> None:
    roles = policy["role_limits"]
    if not roles or any(not re.fullmatch(r"[a-z][a-z0-9_]*", role) for role in roles):
        raise ValueError("Invalid role identities")
    if any(type(value) is not int or value < 1 for value in roles.values()):
        raise ValueError("Application role budgets must be positive finite integers")
    integers = ("max_connections", "superuser_reserved_connections", "ordinary_maintenance_margin",
                "erp_workers_per_slot", "erp_pool_size", "erp_max_overflow", "erp_slots")
    if any(type(policy[k]) is not int or policy[k] < 0 for k in integers):
        raise ValueError("Budget settings must be nonnegative integers")
    erp = policy["erp_slots"] * policy["erp_workers_per_slot"] * (policy["erp_pool_size"] + policy["erp_max_overflow"])
    if erp != roles.get("erp") or erp < 1:
        raise ValueError("ERP role ceiling must equal its slot/worker/pool budget")
    if sum(roles.values()) + policy["ordinary_maintenance_margin"] + policy["superuser_reserved_connections"] > policy["max_connections"]:
        raise ValueError("Global application and maintenance budgets exceed PostgreSQL capacity")
    if set(roles) & set(policy["administrative_roles"]):
        raise ValueError("Administrative and application roles must be distinct")
    if not policy["administrative_roles"] or any(
        not re.fullmatch(r"[a-z][a-z0-9_]*", role) for role in policy["administrative_roles"]
    ):
        raise ValueError("Invalid administrative role identities")


def sql_json(psql: list[str], sql: str) -> dict:
    result = subprocess.run([*psql, "-X", "-q", "-A", "-t", "-v", "ON_ERROR_STOP=1"],
                            input=sql, capture_output=True, text=True, timeout=20)
    if result.returncode:
        # SQL contains role names/limits only, but return a value-free failure.
        raise RuntimeError("PostgreSQL budget command failed; no partial transaction was accepted")
    body = result.stdout
    return json.loads(body[body.index("{"):body.rindex("}") + 1])


SNAPSHOT = """SELECT json_build_object(
 'max_connections', current_setting('max_connections')::int,
 'superuser_reserved_connections', current_setting('superuser_reserved_connections')::int,
 'reserved_connections', coalesce(nullif(current_setting('reserved_connections', true),''),'0')::int,
 'roles', (SELECT json_agg(r) FROM (
   SELECT rolname AS name, rolconnlimit AS connection_limit, rolsuper AS superuser,
     (SELECT count(*) FROM pg_stat_activity a WHERE a.usename=pg_roles.rolname
       AND a.backend_type='client backend' AND a.pid<>pg_backend_pid()) AS connections
   FROM pg_roles WHERE rolcanlogin ORDER BY rolname
 ) r));"""


def snapshot(psql: list[str]) -> dict:
    return sql_json(psql, "BEGIN READ ONLY; SET LOCAL statement_timeout='5s';\n" + SNAPSHOT + "\nROLLBACK;")


def plan(policy: dict, state: dict) -> dict:
    validate_policy(policy)
    for name in ("max_connections", "superuser_reserved_connections"):
        if state[name] != policy[name]:
            raise ValueError("Live PostgreSQL settings differ from the reviewed budget")
    if state["reserved_connections"]:
        raise ValueError("Additional reserved connections require a new reviewed allocation")
    live = {r["name"]: r for r in state["roles"]}
    if set(live) != set(policy["role_limits"]) | set(policy["administrative_roles"]):
        raise ValueError("Unknown or missing login role; every consumer must have an allocation")
    for name, row in live.items():
        if row["superuser"] != (name in policy["administrative_roles"]):
            raise ValueError("Unexpected application/admin superuser privileges")
        if name in policy["role_limits"] and row["connections"] > policy["role_limits"][name]:
            raise ValueError("A proposed role budget is below its current client count")
    admin = sum(live[n]["connections"] for n in policy["administrative_roles"])
    if admin > policy["ordinary_maintenance_margin"] + policy["superuser_reserved_connections"]:
        raise ValueError("Administrative clients already exhaust the maintenance margin")
    proposal = {"policy": policy, "previous_limits": {n: live[n]["connection_limit"] for n in policy["role_limits"]}}
    digest = hashlib.sha256(json.dumps(proposal, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {**proposal, "plan_sha256": digest, "live": state,
            "application_budget": sum(policy["role_limits"].values()),
            "shared_budget": sum(v for k, v in policy["role_limits"].items() if k != "erp")}


def transaction(policy: dict, previous: dict, target: dict) -> str:
    # All names and integer limits are validated before SQL construction.
    validate_policy(policy)
    if set(previous) != set(policy["role_limits"]) or set(target) != set(previous):
        raise ValueError("Rollback/target identities differ from the reviewed roles")
    if any(type(v) is not int or v < -1 for v in [*previous.values(), *target.values()]):
        raise ValueError("Invalid connection limit")
    expected = ",".join("('%s',%d)" % (n, v) for n, v in sorted(previous.items()))
    roles = ",".join("'%s'" % n for n in sorted(set(previous) | set(policy["administrative_roles"])))
    admins = ",".join("'%s'" % n for n in sorted(policy["administrative_roles"]))
    changes = "\n".join(f'ALTER ROLE "{name}" CONNECTION LIMIT {limit};' for name, limit in sorted(target.items()))
    checks = "\n".join(
        "IF (SELECT count(*) FROM pg_stat_activity WHERE usename='%s' AND backend_type='client backend') > %d THEN RAISE EXCEPTION 'Active clients exceed new budget'; END IF;" % (n, v)
        for n, v in sorted(target.items()) if v >= 0)
    return f"""BEGIN; SET LOCAL statement_timeout='5s'; SET LOCAL lock_timeout='2s';
DO $guard$ BEGIN
 IF NOT pg_try_advisory_xact_lock(20261006,202) THEN RAISE EXCEPTION 'Budget operation already running'; END IF;
 IF current_setting('max_connections')::int <> {policy['max_connections']}
 OR current_setting('superuser_reserved_connections')::int <> {policy['superuser_reserved_connections']}
 OR coalesce(nullif(current_setting('reserved_connections',true),''),'0')::int <> 0
 THEN RAISE EXCEPTION 'Server setting drift'; END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolcanlogin AND rolname NOT IN ({roles}))
 OR (SELECT count(*) FROM pg_roles WHERE rolcanlogin) <> {len(set(previous) | set(policy['administrative_roles']))}
 THEN RAISE EXCEPTION 'Consumer identity drift'; END IF;
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ({admins}) AND NOT rolsuper)
 THEN RAISE EXCEPTION 'Administrative privilege drift'; END IF;
 IF EXISTS (SELECT 1 FROM (VALUES {expected}) e(name,lim) LEFT JOIN pg_roles r ON r.rolname=e.name
            WHERE r.oid IS NULL OR NOT r.rolcanlogin OR r.rolsuper OR r.rolconnlimit<>e.lim)
 THEN RAISE EXCEPTION 'Role limit/privilege drift'; END IF;
 {checks}
END $guard$;
{changes}
{SNAPSHOT}
COMMIT;
"""


def save_exclusive(path: Path, value: dict) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--policy-json")
    parser.add_argument("--psql-json", default='["psql","-d","postgres"]')
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-plan-sha256")
    parser.add_argument("--rollback-record", type=Path)
    parser.add_argument("--rollback", type=Path)
    args = parser.parse_args()
    if bool(args.policy) == bool(args.policy_json):
        parser.error("Specify exactly one of --policy or --policy-json")
    if args.apply and args.rollback:
        parser.error("Apply and rollback are mutually exclusive")
    policy = json.loads(args.policy_json) if args.policy_json else json.loads(args.policy.read_text())
    psql = json.loads(args.psql_json)
    if args.rollback:
        record = json.loads(args.rollback.read_text())
        if record["policy"] != policy:
            raise ValueError("Rollback policy mismatch")
        after = sql_json(psql, transaction(policy, policy["role_limits"], record["previous_limits"]))
        print(json.dumps({"action": "rolled_back", "live": after}))
    elif args.apply:
        current = plan(policy, snapshot(psql))
        if current["plan_sha256"] != args.expected_plan_sha256 or not args.rollback_record:
            raise ValueError("Reviewed plan hash and rollback record are required")
        save_exclusive(args.rollback_record, {k: current[k] for k in ("policy", "previous_limits", "plan_sha256")})
        after = sql_json(psql, transaction(policy, current["previous_limits"], policy["role_limits"]))
        assert {r["name"]: r["connection_limit"] for r in after["roles"] if r["name"] in policy["role_limits"]} == policy["role_limits"]
        print(json.dumps({"action": "applied", "plan_sha256": current["plan_sha256"], "live": after}))
    else:
        current = plan(policy, snapshot(psql))
        print(json.dumps({"action": "planned", **current}))


if __name__ == "__main__":
    main()
