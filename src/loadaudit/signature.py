"""Order-independent signatures for sets of records.

Each record is reduced to a 64-bit integer (first 16 hex digits of the MD5 of
its normalized fields); a group's signature is the XOR of all its records.

Why XOR:
* it does not depend on row order, so a file and a table can be compared
  without sorting either of them;
* it is computed in one streaming pass, also inside PostgreSQL (``bit_xor``),
  so millions of rows never need to leave the database;
* any changed, added or removed record changes the signature (barring a
  2^-64 collision). One caveat: a record present an even number of times
  cancels out, so duplicates are checked separately by count.

The SQL and Python implementations produce identical values, so a signature
taken from a CSV can be compared directly with one taken from the database.
"""
from __future__ import annotations

import hashlib
from typing import Iterable, Sequence

SEP = "\x1f"  # unit separator: cannot appear in normal text fields


def normalize(value) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    return "" if s.lower() in {"nan", "none", "null"} else s


def record_hash(values: Sequence) -> int:
    """Signed 64-bit integer, identical to the SQL expression in ``sql_record_hash``."""
    payload = SEP.join(normalize(v) for v in values).encode("utf-8")
    h = int(hashlib.md5(payload).hexdigest()[:16], 16)
    return h - (1 << 64) if h >= (1 << 63) else h


def signature(rows: Iterable[Sequence]) -> tuple[int, int]:
    """Return (xor_signature, row_count)."""
    sig, n = 0, 0
    for r in rows:
        sig ^= record_hash(r)
        n += 1
    return sig, n


def sql_record_hash(columns: Sequence[str]) -> str:
    """SQL expression that matches ``record_hash`` for the given columns."""
    parts = ", ".join(
        f"CASE WHEN lower(trim({c}::text)) IN ('nan', 'none', 'null') THEN '' "
        f"ELSE coalesce(trim({c}::text), '') END"
        for c in columns
    )
    return f"('x' || substr(md5(concat_ws(E'\\x1f', {parts})), 1, 16))::bit(64)::bigint"
