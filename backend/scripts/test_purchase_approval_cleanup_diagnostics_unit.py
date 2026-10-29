"""Offline behavioral simulations; no application or PostgreSQL imports."""
import ast
import hashlib
import json
import os
import runpy
from unittest.mock import patch
from pathlib import Path
import types
import unittest

SOURCE = Path(__file__).with_name("test_purchase_request_approval_postgres.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf8"))
functions = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in
             {"pool_checked_out", "owned_activity", "wait_owned_disconnect", "cleanup_owned_target", "validate_fixture_evidence"}]
ns = {"hashlib": hashlib}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), ns)
main = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")

class Clock:
    def __init__(self): self.now = 0.0
    def monotonic(self): return self.now
    def sleep(self, seconds): self.now += seconds

class Cursor:
    def __init__(self, counts): self.counts = iter(counts); self.calls = []
    def execute(self, query, *args): self.calls.append((str(query), args))
    def fetchone(self): return (next(self.counts),)

class Tests(unittest.TestCase):
    def test_control_import_without_environment_or_database_dependencies(self):
        control = SOURCE.with_name("purchase_approval_cleanup_pg_control.py")
        with patch.dict(os.environ, {}, clear=True):
            loaded = runpy.run_path(str(control), run_name="control_import_check")
        self.assertTrue(callable(loaded["main"]))
        self.assertNotIn("admin", loaded)
        tree = ast.parse(control.read_text(encoding="utf-8"))
        guard = next(n for n in tree.body if isinstance(n, ast.If))
        self.assertEqual(ast.unparse(guard.test), "__name__ == '__main__'")

    def test_wait_immediate_delayed_and_persistent(self):
        for counts, timeout, expected in [([0], 2, (0, 0, 1, False)),
                                          ([1, 1, 0], 2, (1, 0, 3, False)),
                                          ([1, 1], .1, (1, 1, 2, True))]:
            clock = Clock(); ns["time"] = clock; c = Cursor(counts)
            result = ns["wait_owned_disconnect"](c, "owned", timeout=timeout, poll=.05)
            self.assertEqual((result["initial"], result["final"], result["attempts"], result["timed_out"]), expected)
            self.assertTrue(all(args == (("owned",),) for query, args in c.calls if "pg_stat_activity" in query))
            self.assertLessEqual(result["elapsed_seconds"], timeout)

    def test_persistent_connection_still_fails_after_drop_and_activity_error(self):
        class SQL:
            def __init__(self, value): self.value = value
            def format(self, value): return self.value.format(value)
        def fail(*args): raise ValueError("secret")
        ns["sql"] = types.SimpleNamespace(SQL=SQL, Identifier=lambda s: s)
        ns["owned_activity"] = fail; ns["time"] = Clock()
        c = Cursor([1, 1, 0]); report = {}
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            ns["cleanup_owned_target"](c, "owned", report, timeout=.1)
        self.assertTrue(report["dropped"])
        self.assertTrue(report["disconnect"]["timed_out"])
        self.assertEqual(report["remaining"], 1)
        self.assertEqual(report["activity_error_type"], "ValueError")
        self.assertNotIn("secret", repr(report))
        self.assertIn("DROP DATABASE owned", c.calls[-2][0])

    def test_late_zero_fails_even_after_drop(self):
        class SlowCursor(Cursor):
            def execute(self, query, *args):
                super().execute(query, *args)
                if "pg_stat_activity" in str(query): ns["time"].now += .2
        class SQL:
            def __init__(self, value): self.value = value
            def format(self, value): return self.value.format(value)
        ns["sql"] = types.SimpleNamespace(SQL=SQL, Identifier=lambda s: s)
        ns["time"] = Clock(); c = SlowCursor([0, 0]); report = {}
        with self.assertRaises(RuntimeError): ns["cleanup_owned_target"](c, "owned", report, timeout=.1)
        self.assertTrue(report["disconnect"]["timed_out"])
        self.assertTrue(report["dropped"])

    def test_query_failure_still_attempts_drop_and_fails(self):
        class BrokenCursor(Cursor):
            def execute(self, query, *args):
                super().execute(query, *args)
                if "pg_stat_activity" in str(query): raise TimeoutError("private")
        class SQL:
            def __init__(self, value): self.value = value
            def format(self, value): return self.value.format(value)
        ns["sql"] = types.SimpleNamespace(SQL=SQL, Identifier=lambda s: s)
        ns["time"] = Clock(); c = BrokenCursor([0]); report = {}
        with self.assertRaises(RuntimeError): ns["cleanup_owned_target"](c, "owned", report)
        self.assertTrue(report["dropped"])
        self.assertEqual(report["disconnect_error_type"], "TimeoutError")
        self.assertNotIn("private", repr(report))

    def test_fixture_validation_rejects_missing_bool_negative_or_wrong_phase(self):
        valid = {"phase":"fixture_dispose", "original_pool_before":0, "original_pool_after":None, "replacement_pool_after":1}
        self.assertEqual(ns["validate_fixture_evidence"](valid), valid)
        for change in ({"original_pool_before":True}, {"original_pool_after":-1}, {"phase":"wrong"}):
            with self.assertRaises(ValueError): ns["validate_fixture_evidence"]({**valid, **change})
        missing = dict(valid); del missing["replacement_pool_after"]
        with self.assertRaises(ValueError): ns["validate_fixture_evidence"](missing)

    def test_fixture_writes_original_and_replacement_pool_to_file(self):
        write = next(n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "write_text" and n.args)
        text = eval(compile(ast.Expression(write.args[0]), str(SOURCE), "eval"), {"database": "owned"})
        fixture = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "owned_database")
        after = fixture.body[next(i for i, n in enumerate(fixture.body)
                             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield)) + 1:]
        class Pool:
            def __init__(self, count): self.count = count
            def checkedout(self): return self.count
        class Engine:
            def __init__(self): self.pool = Pool(1)
            def dispose(self): self.pool = Pool(0)
        class File:
            def __init__(self, name): self.name = name
            def write_text(self, value, encoding): output.append((self.name, json.loads(value)))
        output = []; engine = Engine(); old = engine.pool
        exec(compile(ast.Module(body=after, type_ignores=[]), str(SOURCE), "exec"),
             {"engine": engine, "json": json, "Path": File})
        self.assertIsNot(engine.pool, old)
        self.assertEqual(output, [("fixture-dispose.json", {"phase":"fixture_dispose", "original_pool_before":1,
                                  "original_pool_after":1, "replacement_pool_after":0})])

if __name__ == "__main__": unittest.main()
