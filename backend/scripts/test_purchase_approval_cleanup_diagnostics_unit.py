"""Offline simulations of the actual generated fixture and cleanup branch."""
import ast
import hashlib
import io
import json
from pathlib import Path
import types
import unittest

SOURCE = Path(__file__).with_name("test_purchase_request_approval_postgres.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
functions = [n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name in {"pool_checked_out", "owned_activity"}]
ns = {"hashlib": hashlib}
exec(compile(ast.Module(body=functions, type_ignores=[]), str(SOURCE), "exec"), ns)
main = next(n for n in TREE.body if isinstance(n, ast.FunctionDef) and n.name == "main")


class Tests(unittest.TestCase):
    def test_activity_uses_only_owned_db_and_hashes_application(self):
        class Cursor:
            def execute(self, sql, args): self.sql, self.args = sql, args
            def fetchall(self): return [(17, "idle", "client backend", "sensitive", 2.5, None)]
        c = Cursor(); rows = ns["owned_activity"](c, "owned")
        self.assertEqual(c.args, ("owned",))
        self.assertIn("WHERE datname = %s", c.sql)
        self.assertNotIn("query", c.sql.lower())
        self.assertNotIn("sensitive", repr(rows))
        self.assertEqual(rows[0]["application_name_sha256"], hashlib.sha256(b"sensitive").hexdigest())

    def test_generated_fixture_teardown_preserves_original_pool(self):
        write = next(n for n in ast.walk(main) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                     and n.func.attr == "write_text" and n.args)
        text = eval(compile(ast.Expression(write.args[0]), str(SOURCE), "eval"), {"database": "owned"})
        fixture = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == "owned_database")
        after_yield = fixture.body[next(i for i, n in enumerate(fixture.body)
                            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Yield)) + 1:]
        class Pool:
            def __init__(self, count): self.count = count
            def checkedout(self): return self.count
        class Engine:
            def __init__(self): self.pool = Pool(1)
            def dispose(self): self.pool = Pool(0)
        output = io.StringIO(); engine = Engine(); original = engine.pool
        ctx = {"engine": engine, "json": json, "sys": types.SimpleNamespace(__stdout__=output)}
        exec(compile(ast.Module(body=after_yield, type_ignores=[]), str(SOURCE), "exec"), ctx)
        self.assertIsNot(engine.pool, original)
        self.assertEqual(json.loads(output.getvalue()), {"phase": "fixture_dispose", "original_pool_before": 1,
                         "original_pool_after": 1, "replacement_pool_after": 0})

    def test_actual_cleanup_branch_fails_after_drop_even_if_activity_query_fails(self):
        branch = next(n for n in ast.walk(main) if isinstance(n, ast.If) and ast.unparse(n.test) == "created and admin is not None")
        class Cursor:
            def __init__(self): self.calls = []
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query, *args): self.calls.append(str(query))
            def fetchone(self): return (1,) if len(self.calls) == 1 else (0,)
        class SQL:
            def __init__(self, value): self.value = value
            def format(self, value): return self.value.format(value)
        c = Cursor(); report = {}
        def fail(*args): raise ValueError("secret must not appear")
        ctx = {"created": True, "admin": types.SimpleNamespace(cursor=lambda: c), "database": "owned",
               "report": report, "owned_activity": fail,
               "sql": types.SimpleNamespace(SQL=SQL, Identifier=lambda x: x)}
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            exec(compile(ast.Module(body=[branch], type_ignores=[]), str(SOURCE), "exec"), ctx)
        self.assertEqual(len(c.calls), 3)
        self.assertIn("DROP DATABASE owned", c.calls[1])
        self.assertTrue(report["dropped"])
        self.assertEqual(report["remaining"], 1)
        self.assertEqual(report["activity_error_type"], "ValueError")
        self.assertNotIn("secret", repr(report))

if __name__ == "__main__": unittest.main()
