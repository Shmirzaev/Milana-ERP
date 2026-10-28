"""Hosted negative/positive controls against two explicitly owned PG targets."""
import ipaddress
import json
import os
import secrets
import psycopg2
from psycopg2 import sql
from sqlalchemy.engine import make_url
from test_purchase_request_approval_postgres import cleanup_owned_target, wait_owned_disconnect

url = make_url(os.environ["PUR_APPROVAL_PG_ADMIN_URL"])
if (url.drivername not in {"postgresql", "postgresql+psycopg2"} or url.host not in {"127.0.0.1", "::1"}
        or url.database != "postgres" or not url.port or url.query):
    raise RuntimeError("Expected explicit loopback postgres admin endpoint")
kwargs = dict(host=url.host, port=url.port, user=url.username, password=url.password, connect_timeout=5, options="-c statement_timeout=1000")
admin = psycopg2.connect(dbname="postgres", **kwargs)
admin.autocommit = True
try:
    with admin.cursor() as cur:
        cur.execute("SELECT current_database(), inet_server_port(), host(inet_server_addr())")
        db, port, host = cur.fetchone()
        if db != "postgres" or port != url.port or not ipaddress.ip_address(host).is_loopback:
            raise RuntimeError("Unexpected admin identity")
        outcomes = []
        for mode in ("held", "closed"):
            name = "review_pur_control_" + secrets.token_hex(8)
            created = False
            held = None
            try:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created = True
                held = psycopg2.connect(dbname=name, **kwargs)
                if mode == "closed":
                    held.close(); held = None
                    result = wait_owned_disconnect(cur, name, timeout=2.0)
                    if result["final"] != 0 or result["timed_out"]:
                        raise RuntimeError("Closed-connection control did not reach zero")
                    report = {}
                    cleanup_owned_target(cur, name, report)
                    created = not report["dropped"]
                    outcomes.append({"mode": mode, "wait": result, "cleanup": report})
                else:
                    report = {}
                    try:
                        cleanup_owned_target(cur, name, report, timeout=0.25)
                    except RuntimeError as error:
                        if str(error) != "Owned PostgreSQL cleanup failed or tests leaked connections":
                            raise
                    else:
                        raise RuntimeError("Held-connection guard failed to reject")
                    created = not report.get("dropped", False)
                    if not report.get("dropped") or not report["disconnect"]["timed_out"] or report["remaining"] < 1:
                        raise RuntimeError("Negative control evidence incomplete")
                    outcomes.append({"mode": mode, "cleanup": report})
            finally:
                if held is not None:
                    held.close()
                if created:
                    cur.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
                    cur.execute("SELECT count(*) FROM pg_database WHERE datname=%s", (name,))
                    if cur.fetchone()[0]: raise RuntimeError("Control database cleanup failed")
        print(json.dumps({"controls": outcomes}))
finally:
    admin.close()
