"""Build a synthetic subscriber table and a load file to try the audit end to end.

    DATABASE_URL=... python examples/make_demo.py

Creates ``demo.subscribers`` (10 cities) and ``examples/load_file.csv`` covering
3 of those cities, with some records missing from the table and some orphans,
like a real partial load. Everything is random and fictitious.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

rng = np.random.default_rng(7)
CITIES = [f"City {c}" for c in "ABCDEFGHIJ"]
OUT = Path(__file__).parent / "load_file.csv"


def fake_macs(n: int) -> list[str]:
    raw = rng.integers(0, 2**48, size=n, dtype=np.int64)
    return [":".join(f"{(int(m) >> s) & 0xFF:02X}" for s in range(40, -8, -8)) for m in raw]


def main() -> None:
    n = 60_000
    df = pd.DataFrame({
        "mac": fake_macs(n),
        "city": rng.choice(CITIES, size=n, p=np.linspace(2, 0.5, len(CITIES)) / np.linspace(2, 0.5, len(CITIES)).sum()),
        "node": [f"N{int(x):04d}" for x in rng.integers(1, 900, n)],
        "contract": [f"C{int(x):08d}" for x in rng.integers(1, 10**8, n)],
        "zip": [f"{int(x):05d}-{int(y):03d}" for x, y in zip(rng.integers(10000, 99999, n), rng.integers(0, 999, n))],
    }).drop_duplicates("mac")

    in_scope = df[df.city.isin(CITIES[:3])]
    file_df = pd.concat([
        in_scope.sample(frac=0.85, random_state=1),              # records that exist in the table
        pd.DataFrame({"mac": fake_macs(2_000), "city": rng.choice(CITIES[:3], 2_000),
                      "node": "N0001", "contract": "C00000000", "zip": "00000-000"}),  # new: missing from table
    ])
    file_df.to_csv(OUT, index=False)

    with psycopg2.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS demo CASCADE; CREATE SCHEMA demo;"
                    "CREATE TABLE demo.subscribers (mac text PRIMARY KEY, city text, node text, contract text, zip text)")
        cur.executemany("INSERT INTO demo.subscribers VALUES (%s,%s,%s,%s,%s)", df.itertuples(index=False, name=None))
    print(f"table: {len(df):,} rows in {len(CITIES)} cities | file: {len(file_df):,} rows -> {OUT}")


if __name__ == "__main__":
    main()
