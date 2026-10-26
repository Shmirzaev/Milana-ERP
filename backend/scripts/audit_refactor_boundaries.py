"""Read source without importing the app; flag obvious persistence boundary violations.

Examples (from repository root):
  python backend/scripts/audit_refactor_boundaries.py --root backend/app --path api/routes/purchasing.py
  python backend/scripts/audit_refactor_boundaries.py --root backend/app --path models/purchasing --schema-writes

Default policy: no direct writes/transaction finalization in routes and no
service-to-route imports. --schema-writes additionally checks direct service
write calls against Ismail's schema-owned persistence target. It does not
relocate code or authorize changes. Session commit/rollback in services is
reported separately for transaction-owner review, not automatically forbidden.

This is a conservative static tripwire, NOT a full alias/dataflow/type analysis.
Attribute mutations, dynamic calls, custom session aliases, indirect writes,
cross-domain ownership and runtime behavior still require operation review.
Execute/text calls with unresolved SQL are explicitly review items.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

WRITE_METHODS = {"add", "add_all", "delete", "update", "merge", "bulk_save_objects",
                 "bulk_insert_mappings", "bulk_update_mappings"}
TRANSACTION_METHODS = {"commit", "rollback", "flush"}


def root_name(node: ast.AST) -> str | None:
    while isinstance(node, (ast.Attribute, ast.Call)):
        node = node.value if isinstance(node, ast.Attribute) else node.func
    return node.id if isinstance(node, ast.Name) else None


def session_info_receiver(node: ast.AST, sessions: set[str]) -> bool:
    """Recognize Session.info containers along the receiver, not call arguments.

    Audit queues stored in Session.info are transaction metadata. Their set.add
    and dict.update methods are not Session persistence methods. This is a
    narrow syntactic exclusion, not inference of arbitrary values stored there.
    """
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        if isinstance(node, ast.Attribute):
            if node.attr == "info" and isinstance(node.value, ast.Name) and node.value.id in sessions:
                return True
            node = node.value
        elif isinstance(node, ast.Call):
            node = node.func
        else:
            node = node.value
    return False


def analyze(source: str, path: str, *, schema_writes: bool = False) -> list[dict]:
    path = path.replace("\\", "/")
    findings = []

    def add(rule, node, detail, severity="error"):
        findings.append({"path": path, "line": getattr(node, "lineno", 1),
                         "rule": rule, "severity": severity, "detail": detail})

    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [{"path": path, "line": exc.lineno, "rule": "syntax",
                 "severity": "error", "detail": exc.msg}]
    route = path.startswith("api/routes/")
    service = path.startswith("models/")
    low_level_contract = path.startswith(("schemas/", "libs/dto/", "libs/types/", "libs/enums/"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            modules = [node.module or ""] if isinstance(node, ast.ImportFrom) else [n.name for n in node.names]
            if isinstance(node, ast.ImportFrom) and node.level:
                parent = ["app", *Path(path).with_suffix("").parts[:-1]]
                parent = parent[:len(parent) - node.level + 1]
                modules = [".".join(parent + ([node.module] if node.module else []))]
            for module in modules:
                if (service or low_level_contract) and (module == "app.api.routes" or module.startswith("app.api.routes.")):
                    add("reverse-route-import", node, module)
                if low_level_contract and (module == "app.models" or module.startswith("app.models.")):
                    add("contract-imports-service", node, module)
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
        sessions = {a.arg for a in args if a.arg in {"db", "session"} or
                    (a.annotation is not None and any(t in ast.unparse(a.annotation) for t in ("Session", "DbSession")))}
        # Nested functions are examined in their own pass. This walk can produce
        # duplicate findings for closures; final deduplication keeps one record.
        for call in ast.walk(node):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute):
                continue
            if root_name(call.func) not in sessions:
                continue
            if session_info_receiver(call.func.value, sessions):
                continue
            method = call.func.attr
            detail = ast.unparse(call)[:300]
            if method in WRITE_METHODS and (route or (service and schema_writes)):
                add("route-write" if route else "service-write-outside-schema", call, detail)
            elif method in TRANSACTION_METHODS:
                if route:
                    add("route-transaction", call, detail)
                elif service and schema_writes:
                    add("transaction-owner-review", call, detail, "review")
            elif method in {"execute", "executemany"} and (route or (service and schema_writes)):
                add("sql-execution-review", call, detail, "review")
    return list({(r["path"], r["line"], r["rule"], r["detail"]): r for r in findings}.values())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="backend/app directory")
    parser.add_argument("--path", action="append", default=[], help="Scoped relative file/directory; repeatable")
    parser.add_argument("--schema-writes", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    selected = set()
    for relative in args.path or ["."]:
        target = (root / relative).resolve(strict=True)
        if not target.is_relative_to(root):
            parser.error("Every selected path must stay inside --root")
        selected.update(target.rglob("*.py") if target.is_dir() else [target])
    selected = sorted(p for p in selected if p.suffix == ".py" and "tests" not in p.relative_to(root).parts)
    if not selected:
        parser.error("No Python source files selected")
    findings = [f for p in selected for f in analyze(p.read_text(encoding="utf-8-sig"), p.relative_to(root).as_posix(), schema_writes=args.schema_writes)]
    result = {"files_scanned": len(selected), "schema_writes_target": args.schema_writes,
              "errors": sum(f["severity"] == "error" for f in findings),
              "manual_review_items": sum(f["severity"] == "review" for f in findings),
              "limitations": "Static tripwire only. No alias/dataflow proof; manually trace mapped attribute mutation, alternate writers and ownership.",
              "findings": findings}
    output = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(json.dumps({k:v for k,v in result.items() if k != "findings"}))
    else:
        print(output, end="")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
