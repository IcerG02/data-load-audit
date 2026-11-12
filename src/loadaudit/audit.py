"""File-vs-database reconciliation and before/after integrity checks.

Commands
--------
compare   Reconcile a source CSV against a table, per group (e.g. per city):
          records in the file, in the table, matched, missing from the table,
          and orphans (in the table, not in the file).
snapshot  Save the per-group XOR signatures of a table to JSON.
diff      Compare two snapshots: which groups changed between them.

Typical use around a bulk load that should only touch some groups:

    loadaudit snapshot --table crm.subscribers --group city --columns ... -o before.json
    ... the load runs ...
    loadaudit snapshot ... -o after.json
    loadaudit diff before.json after.json --expected-groups "Alpha City,Beta Town"

Any group outside the expected list whose signature changed was touched by the load.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd
import psycopg2

from .report import render_html
from .signature import normalize, signature, sql_record_hash


@dataclass
class GroupResult:
    group: str
    in_file: int
    in_table: int
    matched: int
    missing_from_table: int
    orphans_in_table: int


def _connect():
    return psycopg2.connect(os.environ["DATABASE_URL"])


def table_keys(conn, table: str, key: str, group: str) -> pd.DataFrame:
    with conn.cursor() as cur:
        cur.execute(f"SELECT DISTINCT {key}::text, {group}::text FROM {table}")
        return pd.DataFrame(cur.fetchall(), columns=["key", "group"])


def compare(file_df: pd.DataFrame, db_df: pd.DataFrame, only_file_groups: bool = True) -> list[GroupResult]:
    """Per-group reconciliation of two (key, group) frames of distinct records.

    'matched' follows the file's group label; 'in_table' and 'orphans' follow the
    table's label, so a record whose group differs between sides is visible.
    Groups absent from the file are skipped by default: use snapshot/diff to
    prove those were left untouched.
    """
    f = file_df.drop_duplicates()
    d = db_df.drop_duplicates()
    db_keys = set(d["key"])
    file_keys = set(f["key"])
    results = []
    groups = set(f["group"]) if only_file_groups else set(f["group"]) | set(d["group"])
    for g in sorted(groups):
        fk = set(f.loc[f["group"] == g, "key"])
        dk = set(d.loc[d["group"] == g, "key"])
        results.append(GroupResult(
            group=g,
            in_file=len(fk),
            in_table=len(dk),
            matched=len(fk & db_keys),
            missing_from_table=len(fk - db_keys),
            orphans_in_table=len(dk - file_keys),
        ))
    return results


def table_signatures(conn, table: str, group: str, columns: list[str]) -> dict[str, dict]:
    expr = sql_record_hash(columns)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT {group}::text, bit_xor({expr}), count(*) FROM {table} GROUP BY 1 ORDER BY 1"
        )
        return {g: {"signature": str(sig), "rows": n} for g, sig, n in cur.fetchall()}


def file_signatures(df: pd.DataFrame, group: str, columns: list[str]) -> dict[str, dict]:
    out = {}
    for g, part in df.groupby(df[group].map(normalize)):
        sig, n = signature(part[columns].itertuples(index=False, name=None))
        out[g] = {"signature": str(sig), "rows": n}
    return out


def diff(before: dict, after: dict, expected: set[str] | None = None) -> dict[str, list[str]]:
    groups = set(before) | set(after)
    changed = sorted(g for g in groups if before.get(g) != after.get(g))
    expected = expected or set()
    return {
        "changed": changed,
        "unexpected_changes": [g for g in changed if g not in expected],
        "unchanged": sorted(groups - set(changed)),
    }


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compare")
    c.add_argument("--file", type=Path, required=True)
    c.add_argument("--table", required=True)
    c.add_argument("--key", required=True, help="record identifier, e.g. mac")
    c.add_argument("--group", required=True, help="grouping column, e.g. city")
    c.add_argument("--html", type=Path, help="write an HTML report here")
    c.add_argument("--all-groups", action="store_true", help="also list table groups absent from the file")

    s = sub.add_parser("snapshot")
    s.add_argument("--table", required=True)
    s.add_argument("--group", required=True)
    s.add_argument("--columns", required=True, help="comma-separated columns that define a record")
    s.add_argument("-o", "--out", type=Path, required=True)

    d = sub.add_parser("diff")
    d.add_argument("before", type=Path)
    d.add_argument("after", type=Path)
    d.add_argument("--expected-groups", default="", help="comma-separated groups the load was allowed to touch")

    a = ap.parse_args(argv)
    if a.cmd == "compare":
        src = pd.read_csv(a.file, dtype=str)
        fdf = pd.DataFrame({"key": src[a.key].map(normalize), "group": src[a.group].map(normalize)})
        with _connect() as conn:
            res = compare(fdf, table_keys(conn, a.table, a.key, a.group), not a.all_groups)
        table = pd.DataFrame([asdict(r) for r in res])
        print(table.to_string(index=False))
        if a.html:
            a.html.write_text(render_html(table, title=f"{a.file.name} vs {a.table}"), encoding="utf-8")
            print(f"report: {a.html}")
    elif a.cmd == "snapshot":
        cols = [x.strip() for x in a.columns.split(",")]
        with _connect() as conn:
            snap = table_signatures(conn, a.table, a.group, cols)
        a.out.write_text(json.dumps({"table": a.table, "columns": cols, "groups": snap}, indent=2))
        print(f"{len(snap)} groups -> {a.out}")
    else:
        b, af = json.loads(a.before.read_text()), json.loads(a.after.read_text())
        exp = {x.strip() for x in a.expected_groups.split(",") if x.strip()}
        r = diff(b["groups"], af["groups"], exp)
        print(json.dumps(r, indent=2, ensure_ascii=False))
        raise SystemExit(1 if r["unexpected_changes"] else 0)


if __name__ == "__main__":
    main()
