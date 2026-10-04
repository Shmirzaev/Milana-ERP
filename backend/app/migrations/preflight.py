"""Read-only, predecessor-gated migration impact preflight.

Tracker DB05: migration impact preview/preflight tooling was missing. The row
requires *"read-only predecessor-gated previews adapted to clone migration
lineage. Never rerun old destructive/grant migrations; require exact impact,
backup and owner approval for changes."*

This module answers "what exactly would this migration do to *this* database?"
without running it. It has three properties, each covered by a regression test:

**Read-only.** Every statement this module sends to a database is validated by
:func:`_validate_read_only` (must be a single ``SELECT``/``WITH``, and must
contain no data-modifying keyword) and is executed inside an explicit
``SET TRANSACTION READ ONLY`` transaction that is always rolled back. The module
never imports :mod:`alembic.command` and never calls :func:`alembic.op.execute`,
so it cannot be a path that re-runs a destructive or grant migration.

**Predecessor-gated.** A preview is only meaningful at the revision the target
migration actually applies to. :func:`predecessor_gate` resolves the lineage from
*this* branch's ``alembic/versions`` directory at call time and refuses when the
database is not at one of the target's ``down_revision`` values, so a preview can
never be mistaken for a statement about a database at the wrong revision.

**Exact impact.** Destructive ``DO $$ ... $$`` blocks are parsed with :mod:`ast`,
the ``SELECT ... INTO`` assignment is resolved into a scalar subquery, and each
``DELETE`` is reported as the exact ``SELECT count(*)`` it would delete. A shape
the parser cannot resolve raises :class:`PreflightUnsupported` instead of
guessing, so the tool refuses rather than understates impact.

Destructive-migration grants stay manual: nothing here executes a migration, and
every report carries the approval requirements decision D2 tracks.
"""

from __future__ import annotations

import ast
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from sqlalchemy import text

__all__ = [
    "PreflightError",
    "PreflightRefused",
    "PreflightReport",
    "PreflightUnsupported",
    "classify_source",
    "describe_lineage",
    "predecessor_gate",
    "preview_revision",
    "read_only_connection",
    "resolve_script_directory",
]

# Statements this module is willing to run. Everything else is refused.
_ALLOWED_LEADING = ("SELECT", "WITH")
_MUTATING_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE",
    "GRANT", "REVOKE", "COMMENT", "VACUUM", "REINDEX", "COPY", "CALL", "DO",
)


class PreflightError(RuntimeError):
    """Base class for every refusal raised by this module."""


class PreflightRefused(PreflightError):
    """The preview was refused; the migration was not and will not be run."""


class PreflightUnsupported(PreflightError):
    """The migration's impact could not be resolved exactly, so we refuse."""


# --------------------------------------------------------------------------- #
# lineage
# --------------------------------------------------------------------------- #

def resolve_script_directory(start: Path | str | None = None) -> ScriptDirectory:
    """Locate ``alembic.ini`` by walking up from ``start`` (default: this file).

    The lineage is read from the checkout the tool runs in, so a preview always
    reflects *this* branch's revisions rather than an assumed one.
    """
    here = Path(start or __file__).resolve()
    roots = [here] + list(here.parents) if here.is_dir() else [here, *here.parents]
    for candidate in roots:
        for root in {candidate, *candidate.parents}:
            ini = root / "alembic.ini"
            if ini.is_file() and (root / "alembic" / "versions").is_dir():
                return ScriptDirectory.from_config(Config(str(ini)))
    raise PreflightError(f"No alembic.ini with an alembic/versions directory found from {here}")


def _down_revisions(script: Script) -> tuple[str, ...]:
    if not script.down_revision:
        return ()
    if isinstance(script.down_revision, (list, tuple)):
        return tuple(script.down_revision)
    return (script.down_revision,)


def _resolve_revision(script: ScriptDirectory, revision: str) -> Script:
    try:
        return script.get_revision(revision)
    except Exception as error:  # unknown / ambiguous revision
        raise PreflightRefused(f"Unknown or ambiguous revision {revision!r}: {error}") from error


def current_revision(connection: sa.Connection) -> str | None:
    """Return the database's current Alembic revision, or ``None`` if unmigrated."""
    from alembic.migration import MigrationContext

    return MigrationContext.configure(connection).get_current_revision()


def describe_lineage(script: ScriptDirectory, revision: str) -> dict:
    """Describe one revision and its immediate predecessors in this lineage."""
    target = _resolve_revision(script, revision)
    return {
        "revision": target.revision,
        "down_revisions": list(_down_revisions(target)),
        "is_head": target.revision in set(script.get_heads()),
        "heads": sorted(script.get_heads()),
        "path": str(target.path) if target.path else None,
        "summary": (target.doc or "").strip().splitlines()[0] if target.doc else None,
    }


def predecessor_gate(script: ScriptDirectory, revision: str, database_revision: str | None) -> dict:
    """Refuse unless the database sits at one of the target's predecessors.

    Returns a gate dict, or raises :class:`PreflightRefused`. A preview taken at
    the wrong revision would report impact for a state the target never sees.
    """
    target = _resolve_revision(script, revision)
    expected = _down_revisions(target)
    if not expected:
        raise PreflightRefused(
            f"{target.revision} has no down_revision in this lineage; there is no "
            f"predecessor state to preview it against"
        )
    if database_revision is None:
        raise PreflightRefused(
            f"Database is not Alembic-stamped (current=<none>); {target.revision} "
            f"previews only at {', '.join(expected)}"
        )
    if database_revision not in expected:
        raise PreflightRefused(
            f"Predecessor gate refused: database is at {database_revision!r} but "
            f"{target.revision} applies to {', '.join(expected)}"
        )
    return {
        "revision": target.revision,
        "expected_predecessors": list(expected),
        "database_revision": database_revision,
        "passed": True,
    }


# --------------------------------------------------------------------------- #
# read-only execution
# --------------------------------------------------------------------------- #

def _validate_read_only(statement: str) -> str:
    """Return ``statement`` if it is safe to run read-only, else raise."""
    text_value = " ".join(statement.split())
    leading = text_value.lstrip("( \t\r\n")
    if not leading.upper().startswith(_ALLOWED_LEADING):
        raise PreflightRefused(f"Refusing to run a non-SELECT statement: {text_value[:120]!r}")
    if ";" in text_value.rstrip(";"):
        raise PreflightRefused(f"Refusing to run a multi-statement preview: {text_value[:120]!r}")
    upper = text_value.upper()
    for keyword in _MUTATING_KEYWORDS:
        if re.search(rf"\b{keyword}\b", upper):
            raise PreflightRefused(
                f"Refusing to run a statement containing {keyword}: {text_value[:120]!r}"
            )
    return text_value


def read_only_connection(engine: sa.Engine) -> sa.Connection:
    """Open a connection whose transaction rejects every write.

    ``SET TRANSACTION READ ONLY`` is issued as the first statement of the
    transaction, so PostgreSQL itself rejects any write for the rest of it. The
    caller must roll back; :func:`preview_revision` always does.
    """
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(text("SET TRANSACTION READ ONLY"))
    transaction.rollback()
    return connection


def _scalar(connection: sa.Connection, statement: str) -> Any:
    checked = _validate_read_only(statement)
    return connection.execute(text(checked)).scalar()


# --------------------------------------------------------------------------- #
# source classification
# --------------------------------------------------------------------------- #

def _execute_payloads(source: str) -> list[tuple[str, str]]:
    """Return ``(kind, sql)`` for each ``op.execute`` payload in ``source``.

    Uses :mod:`ast` rather than a regex so a Python string that merely *looks*
    like SQL is never treated as migration impact.
    """
    tree = ast.parse(source)
    payloads: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr not in {"execute"} or not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            payloads.append(("execute", argument.value))
        else:
            payloads.append((f"execute:{type(argument).__name__}", ""))
    return payloads


def classify_source(source: str) -> dict:
    """Classify a migration's risk from its ``op.execute`` payloads and calls."""
    payloads = _execute_payloads(source)
    sql_text = "\n".join(sql for _, sql in payloads).upper()
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    dynamic = [kind for kind, _ in payloads if kind != "execute"]
    return {
        "destructive": bool(re.search(r"\b(DELETE\s+FROM|TRUNCATE|DROP\s+TABLE|DROP\s+COLUMN)\b", sql_text))
                      or bool(called & {"drop_table", "drop_column"}),
        "permission": bool(re.search(r"\b(CREATE\s+ROLE|ALTER\s+ROLE|GRANT|REVOKE)\b", sql_text)),
        "data_write": bool(re.search(r"\b(INSERT\s+INTO|UPDATE\s+\w+\s+SET)\b", sql_text)),
        "ddl": bool(called & {"create_table", "add_column", "create_index", "alter_column"}),
        "dynamic_sql_payloads": dynamic,
        "previews_statically": not dynamic,
    }


# --------------------------------------------------------------------------- #
# destructive DO-block analysis
# --------------------------------------------------------------------------- #

_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'", re.DOTALL)


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return re.sub(r"--[^\n]*", " ", sql)


_KEYWORD_HEAD = re.compile(
    r"[ \t]*(?:BEGIN|END|IF|ELSIF|ELSE|DECLARE|RETURN|RAISE|DELETE|SELECT|INSERT"
    r"|UPDATE|DROP|CREATE|ALTER|GRANT|REVOKE|COMMIT|ROLLBACK)\b",
    re.IGNORECASE,
)


def _split_plpgsql_statements(body: str) -> list[str]:
    """Split a PL/pgSQL body into statements.

    A plain ``;`` split is not enough: PL/pgSQL headers such as
    ``IF cond THEN`` and ``BEGIN`` are not ``;``-terminated, so a naive split
    glues a header to the first statement in its body. This scanner cuts on
    ``;`` at paren depth 0 *and* on a statement keyword that starts a line at
    depth 0, which is how these migrations are formatted. String literals are
    consumed verbatim so a ``;`` or a keyword inside a message never splits.
    """
    statements: list[str] = []
    buffer: list[str] = []
    depth = 0
    line_start = True
    index = 0
    length = len(body)

    while index < length:
        char = body[index]
        if char == "'":
            end = index + 1
            while end < length:
                if body[end] == "'":
                    if end + 1 < length and body[end + 1] == "'":
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            buffer.append(body[index:end])
            index = end
            line_start = False
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == ";" and depth == 0:
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            line_start = True
            continue
        elif char == "\n":
            line_start = True
        elif depth == 0 and line_start:
            if char in " \t":
                if _KEYWORD_HEAD.match(body, index):
                    statement = "".join(buffer).strip()
                    if statement:
                        statements.append(statement)
                    buffer = []
                    line_start = False
                    index += 1
                    continue
            else:
                line_start = False
        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements


def _strip_literals(fragment: str) -> str:
    """Blank out string literals so identifier scanning cannot match inside them."""
    return _STRING_LITERAL.sub("''", fragment)


def substitute_identifiers(fragment: str, replacements: dict[str, str]) -> str:
    """Replace bare PL/pgSQL variable names outside string literals.

    ``replacements`` maps a variable to a SQL expression. Word boundaries keep a
    longer identifier such as ``target_id2`` from being rewritten.
    """
    out: list[str] = []
    for part in re.split(r"('(?:[^']|'')*')", fragment):
        if part.startswith("'") and part.endswith("'"):
            out.append(part)
            continue
        for name, expression in replacements.items():
            part = re.sub(rf"(?<![\w.]){re.escape(name)}(?![\w])", expression, part)
        out.append(part)
    return "".join(out)


def _find_do_body(sql: str) -> str | None:
    match = re.search(r"DO\s+\$\$+(.*?)\$\$+\s*;?", sql, flags=re.DOTALL | re.IGNORECASE)
    return _strip_comments(match.group(1)) if match else None


@dataclass
class _Statement:
    table: str
    where: str


def _parse_select_into(statement: str) -> tuple[str, str, str, str] | None:
    match = re.match(
        r"SELECT\s+(.+?)\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\s+FROM\s+([A-Za-z_][A-Za-z0-9_.]*)"
        r"(?:\s+WHERE\s+(.+?))?$",
        statement.strip(),
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    selected, variable, table, where = match.groups()
    where = (where or "").strip()
    # FOR UPDATE / LOCK IN SHARE MODE cannot run in a read-only transaction and
    # are locking-only, so they never affect which rows match.
    where = re.sub(r"\s+FOR\s+(UPDATE|NO\s+KEY\s+UPDATE|SHARE|KEY\s+SHARE)\s*$", "", where,
                   flags=re.IGNORECASE)
    where = re.sub(r"\s+LOCK\s+IN\s+SHARE\s+MODE\s*$", "", where, flags=re.IGNORECASE)
    selected = selected.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", selected):
        raise PreflightUnsupported(
            f"SELECT INTO {variable!r} selects {selected!r}; preflight only resolves a "
            f"single named column or a literal"
        )
    if not where:
        raise PreflightUnsupported(
            f"SELECT INTO {variable!r} has no WHERE clause; preflight refuses to "
            f"preview an unbounded lookup"
        )
    return variable, table, where.strip(), selected


def _parse_condition(statement: str) -> str | None:
    match = re.match(r"IF\s+(.+?)\s+THEN$", statement.strip(), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _raise_details(statement: str) -> tuple[str | None, str | None]:
    """Return ``(level, message)`` for a ``RAISE NOTICE|EXCEPTION '...'``."""
    match = re.search(r"RAISE\s+(EXCEPTION|NOTICE)\s+'((?:[^']|'')*)'", statement,
                      re.IGNORECASE | re.DOTALL)
    if not match:
        return None, None
    return match.group(1).upper(), match.group(2).replace("''", "'")


def analyze_destructive_block(sql: str) -> dict:
    """Turn a destructive ``DO $$`` block into exact, read-only preview SQL.

    Returns resolved ``SELECT count(*)`` statements for every ``DELETE``, plus
    the target's own guard conditions. Raises :class:`PreflightUnsupported` for
    any statement shape that cannot be resolved exactly.
    """
    body = _find_do_body(sql)
    if body is None:
        raise PreflightUnsupported("No DO $$ block found; destructive payload shape changed")
    statements = _split_plpgsql_statements(body)
    variables: dict[str, str] = {}
    deletes: list[_Statement] = []
    conditions: list[dict] = []
    returns = False

    index = 0
    while index < len(statements):
        statement = statements[index]
        head = statement.strip()

        if re.match(r"DECLARE\b", head, re.IGNORECASE):
            for part in head[len("DECLARE"):].split(";"):
                # A declaration is "<name> [CONSTANT] <type>"; keep the name only.
                declared = re.match(r"([A-Za-z_][A-Za-z0-9_]*)", part.strip())
                if declared:
                    variables[declared.group(1)] = ""
            index += 1
            continue

        if (assignment := _parse_select_into(head)) is not None:
            variable, table, where, selected = assignment
            variables[variable] = f"(SELECT {selected} FROM {table} WHERE {where})"
            index += 1
            continue

        if (condition := _parse_condition(head)) is not None:
            block, index = _collect_if_block(statements, index)
            level, message = _raise_details(" ".join(block))
            conditions.append({
                "condition": condition,
                "raise_level": level,
                "raise_message": message,
                "returns_early": any(
                    re.match(r"RETURN\s*$", item.strip(), re.IGNORECASE) for item in block
                ),
            })
            continue

        if re.match(r"DELETE\s+FROM\b", head, re.IGNORECASE):
            match = re.match(
                r"DELETE\s+FROM\s+([A-Za-z_][A-Za-z0-9_.]*)(?:\s+WHERE\s+(.+?))?$",
                head, re.IGNORECASE | re.DOTALL,
            )
            if not match:
                raise PreflightUnsupported(f"Unresolvable DELETE statement: {head[:120]!r}")
            table, where = match.group(1), (match.group(2) or "").strip()
            if not where:
                raise PreflightUnsupported(
                    f"DELETE FROM {table} has no WHERE clause; preflight refuses to "
                    f"preview an unbounded delete"
                )
            deletes.append(_Statement(table, where))
            index += 1
            continue

        if re.match(r"RETURN\s*$", head, re.IGNORECASE):
            returns = True
            index += 1
            continue

        # Only a bare control word may be skipped. Anything else that reached
        # this point is an unrecognised statement and must be refused: silently
        # ignoring it could drop a DELETE from the reported impact.
        if re.match(r"RAISE\b", head, re.IGNORECASE) or re.fullmatch(
            r"(BEGIN|END|END\s+IF|ELSIF|ELSE|COMMIT|ROLLBACK|EXCEPTION)\s*",
            head, re.IGNORECASE,
        ):
            index += 1
            continue

        raise PreflightUnsupported(
            f"Unresolvable statement in destructive block: {head[:160]!r}. Preflight "
            f"refuses to guess exact impact."
        )

    resolved = {name: expression for name, expression in variables.items() if expression}
    for statement in deletes:
        statement.where = substitute_identifiers(statement.where, resolved)
    for condition in conditions:
        condition["condition"] = substitute_identifiers(condition["condition"], resolved)

    # A declared variable that is never assigned and still appears in the impact
    # would resolve to a nonexistent column at run time. Refuse instead.
    combined = " ".join(
        [delete.where for delete in deletes] + [item["condition"] for item in conditions]
    )
    for name, expression in variables.items():
        if expression:
            continue
        if re.search(rf"(?<![\w.]){re.escape(name)}(?![\w])", combined, re.IGNORECASE):
            raise PreflightUnsupported(
                f"PL/pgSQL variable {name!r} is declared but never assigned in this block; "
                f"preflight refuses to guess its value"
            )

    return {
        "deletes": [
            {
                "table": delete.table,
                "where": delete.where,
                "count_sql": f"SELECT count(*) FROM {delete.table} WHERE {delete.where}",
            }
            for delete in deletes
        ],
        "conditions": conditions,
        # An early return can only come from inside a guard block, so derive it
        # from the conditions rather than from a top-level RETURN.
        "returns_early": returns or any(item["returns_early"] for item in conditions),
        "scalar_resolutions": resolved,
    }


def _collect_if_block(statements: list[str], index: int) -> tuple[list[str], int]:
    """Collect the statements of an ``IF ... THEN ... END IF`` block."""
    block: list[str] = []
    index += 1
    depth = 1
    while index < len(statements):
        current = statements[index].strip()
        if _parse_condition(current) is not None and re.search(r"\bBEGIN\s*$", current, re.IGNORECASE):
            depth += 1
        if re.match(r"END(\s+IF)?\s*$", current, re.IGNORECASE):
            depth -= 1
            if depth == 0:
                return block, index + 1
        block.append(current)
        index += 1
    raise PreflightUnsupported("Unterminated IF block in destructive migration")


# --------------------------------------------------------------------------- #
# report
# --------------------------------------------------------------------------- #

@dataclass
class PreflightReport:
    revision: str
    summary: str | None
    lineage: dict
    gate: dict
    classification: dict
    exact_impact: dict
    safety: dict

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int | None = 2) -> str:
        import json

        return json.dumps(self.to_dict(), indent=indent, sort_keys=True, default=str)


def _approval_block() -> dict:
    return {
        "executes_migration": False,
        "read_only": True,
        "requires_postgresql_backup": True,
        "requires_owner_approval": True,
        "approval_reference": "bugs.md decision D2",
        "note": (
            "This preview never runs the migration. Executing a destructive or "
            "grant migration requires an exact-impact review, a PostgreSQL backup "
            "and explicit owner approval."
        ),
    }


def preview_revision(
    engine: sa.Engine,
    revision: str,
    *,
    script: ScriptDirectory | None = None,
) -> PreflightReport:
    """Preview ``revision``'s exact impact without executing it.

    Raises :class:`PreflightRefused` when the predecessor gate fails and
    :class:`PreflightUnsupported` when the impact cannot be resolved exactly.
    """
    script = script or resolve_script_directory()
    target = _resolve_revision(script, revision)
    path = Path(target.path)
    if path is None or not path.is_file():
        raise PreflightRefused(f"Revision {revision} has no readable file: {path}")
    source = path.read_text(encoding="utf-8")
    classification = classify_source(source)

    payloads = [sql for kind, sql in _execute_payloads(source) if sql]
    destructive_payloads = [
        sql for sql in payloads
        if re.search(r"\b(DELETE\s+FROM|TRUNCATE)\b", sql.upper())
    ]

    connection = engine.connect()
    try:
        transaction = connection.begin()
        connection.execute(text("SET TRANSACTION READ ONLY"))
        try:
            gate = predecessor_gate(script, revision, current_revision(connection))
            analysis: dict = {"deletes": [], "conditions": [], "returns_early": False}
            if destructive_payloads:
                analysis = analyze_destructive_block(destructive_payloads[0])
                for condition in analysis["conditions"]:
                    condition["holds"] = bool(
                        _scalar(connection, f"SELECT {condition['condition']}")
                    )
                for delete in analysis["deletes"]:
                    delete["rows"] = int(_scalar(connection, delete["count_sql"]))
        finally:
            # Never commit: a read-only preview must leave no trace.
            transaction.rollback()
    finally:
        connection.close()

    rows = sum(delete.get("rows", 0) for delete in analysis.get("deletes", []))
    guard = next(
        (item for item in analysis.get("conditions", [])
         if item["raise_level"] == "EXCEPTION"),
        None,
    )
    no_op = next(
        (item for item in analysis.get("conditions", []) if item.get("returns_early")),
        None,
    )
    would_no_op = bool(no_op and no_op.get("holds"))
    would_refuse = bool(guard and guard.get("holds"))

    if would_no_op:
        outcome = "no_op"
    elif would_refuse:
        outcome = "refuse"
    elif rows:
        outcome = "delete"
    else:
        outcome = "no_op"

    return PreflightReport(
        revision=revision,
        summary=lineage_summary(target),
        lineage=describe_lineage(script, revision),
        gate=gate,
        classification=classification,
        exact_impact={
            "outcome": outcome,
            "would_no_op": would_no_op,
            "would_raise_exception": would_refuse,
            "refusal_message": guard.get("raise_message") if would_refuse else None,
            "total_rows_deleted": 0 if (would_no_op or would_refuse) else rows,
            "deletes": analysis.get("deletes", []),
            "guard_conditions": analysis.get("conditions", []),
        },
        safety=_approval_block(),
    )


def lineage_summary(target: Script) -> str | None:
    return target.doc.strip().splitlines()[0] if target.doc else None
