# data-load-audit

Two questions come up after every bulk load into a production table:

1. **Did the load do what it should?** For each group (city, region, product…), how many records from the source file are in the table, and how many are missing?
2. **Did it do anything it shouldn't?** Were the groups that were *out of scope* left exactly as they were?

`loadaudit` answers both from the command line, against PostgreSQL.

> **About this repo.** I wrote this after auditing a real subscriber-base load with millions of records across hundreds of cities. This portfolio version was written from scratch with synthetic data; no employer code or data is included.

## The idea: an order-independent signature

Each record is hashed (MD5 of its normalized fields, first 64 bits). A group's **signature** is the XOR of all its record hashes.

- XOR does not depend on row order, so a CSV and a table can be compared without sorting.
- It runs in one pass, also **inside PostgreSQL** (`bit_xor`): millions of rows never leave the database.
- Any added, removed or changed record changes the signature.
- The SQL and Python implementations produce the same value (covered by a test), so a file can be compared with a table directly.

Caveat: a record present an even number of times cancels itself out, so row counts are stored next to each signature.

## Usage

```bash
pip install -e ".[dev]"
export DATABASE_URL=postgresql://user:pass@localhost:5432/db
python examples/make_demo.py        # synthetic table (10 cities) + load file (3 cities)
```

**1. Reconcile the file with the table**

```bash
loadaudit compare --file examples/load_file.csv --table demo.subscribers \
                  --key mac --group city --html report.html
```
```
 group  in_file  in_table  matched  missing_from_table  orphans_in_table
City A     8802      9569     8134                 668              1435
City B     8176      8770     7461                 715              1309
City C     7340      7918     6723                 617              1195
```

**2. Prove that out-of-scope groups were not touched**

```bash
loadaudit snapshot --table demo.subscribers --group city \
                   --columns mac,city,node,contract,zip -o before.json
# ... the load runs ...
loadaudit snapshot ... -o after.json
loadaudit diff before.json after.json --expected-groups "City A,City B,City C"
```
```json
{ "changed": ["City A", "City H"], "unexpected_changes": ["City H"], ... }
```

`diff` exits with code 1 when an unexpected group changed, so it can gate a deployment or a CI job.

## Tests

```bash
pytest                    # signature properties, reconciliation, diff
DATABASE_URL=... pytest   # + SQL and Python signatures are identical
```

Stack: Python, pandas, psycopg2, PostgreSQL 14+ (`bit_xor`).
