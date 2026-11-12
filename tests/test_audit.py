import os
import random

import pandas as pd
import pytest

from loadaudit.audit import compare, diff, file_signatures
from loadaudit.signature import record_hash, signature, sql_record_hash

ROWS = [("AA:01", "City A", "N1"), ("AA:02", "City A", "N2"), ("BB:01", "City B", None)]


def test_signature_is_order_independent():
    shuffled = ROWS[:]
    random.Random(3).shuffle(shuffled)
    assert signature(ROWS) == signature(shuffled)


def test_signature_detects_a_single_changed_field():
    changed = [ROWS[0], ("AA:02", "City A", "N9"), ROWS[2]]
    assert signature(ROWS)[0] != signature(changed)[0]


def test_normalization_ignores_whitespace_and_null_spellings():
    assert record_hash(["x ", None]) == record_hash(["x", "NaN"])


def test_compare_counts_missing_and_orphans():
    file_df = pd.DataFrame({"key": ["1", "2", "3"], "group": ["A", "A", "B"]})
    db_df = pd.DataFrame({"key": ["1", "3", "9"], "group": ["A", "B", "B"]})
    res = {r.group: r for r in compare(file_df, db_df)}
    assert (res["A"].in_file, res["A"].matched, res["A"].missing_from_table) == (2, 1, 1)
    assert res["B"].orphans_in_table == 1


def test_diff_flags_unexpected_groups():
    before = {"A": {"signature": "1"}, "B": {"signature": "2"}}
    after = {"A": {"signature": "5"}, "B": {"signature": "7"}}
    assert diff(before, after, expected={"A"})["unexpected_changes"] == ["B"]


@pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="needs DATABASE_URL")
def test_sql_and_python_signatures_match():
    import psycopg2

    df = pd.DataFrame(ROWS + [("CC:01", " City B ", "nan")], columns=["mac", "city", "node"])
    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("CREATE TEMP TABLE t (mac text, city text, node text)")
        cur.executemany("INSERT INTO t VALUES (%s,%s,%s)", df.itertuples(index=False, name=None))
        expr = sql_record_hash(["mac", "city", "node"])
        cur.execute(f"SELECT trim(city), bit_xor({expr})::text, count(*) FROM t GROUP BY 1 ORDER BY 1")
        sql_sigs = {g: {"signature": s, "rows": n} for g, s, n in cur.fetchall()}
    assert sql_sigs == file_signatures(df, "city", ["mac", "city", "node"])
