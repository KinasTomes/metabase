"""Load a generated scenario into its own warehouse schema.

Each scenario lands in `scenario_<name>` and is shaped to match `analytics`, so
the nightly scanner runs the same SQL against a fixture as it does against the
real surface -- only the schema name changes.

ISOLATION IS THE POINT
----------------------
Scenario rows are fabricated shifts. They are not facts. Two independent
barriers keep them away from MetaBot:

  1. the Metabase connection uses `schema-filters-type: inclusion` = analytics,
     so sync never sees these schemas;
  2. this loader explicitly REVOKEs everything from the reader role.

The second is not redundant. The first is a setting someone can change in the
admin UI in two clicks; the second fails closed at the database. Without it, a
fabricated 57% Tet surge is one careless config edit away from being reported to
a manager as fact -- the same shape of failure as serving the cancelled feature
columns, which is what the catalogue/fact split exists to prevent.

Usage:
    python load_scenario.py                       # every generated scenario
    python load_scenario.py --only null tet_surge
    python load_scenario.py --drop                # tear all scenario schemas down
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

from load_warehouse import (  # reuse the same connection settings and .env handling
    READER_USER,
    get_connection,
    load_env_file,
    read_csv,
)

_HERE = Path(__file__).resolve().parent
SCENARIO_DIR = _HERE / "scenarios"

# Only the columns the scanner needs. Narrower than silver on purpose: a fixture
# that carries geo coordinates invites someone to demo off it.
TABLES = {
    "transactions": """
        transaction_id      TEXT PRIMARY KEY,
        customer_id         TEXT NOT NULL,
        pnl                 TEXT NOT NULL,
        company             TEXT NOT NULL,
        transaction_date    DATE NOT NULL,
        transaction_month   TEXT NOT NULL,
        product             TEXT NOT NULL,
        status              TEXT NOT NULL,
        amount              NUMERIC(18,2) NOT NULL,
        province            TEXT NOT NULL,
        global_customer_id  TEXT NOT NULL
    """,
    "events": """
        event_id            TEXT PRIMARY KEY,
        customer_id         TEXT NOT NULL,
        pnl                 TEXT NOT NULL,
        company             TEXT NOT NULL,
        event_date          DATE NOT NULL,
        event_name          TEXT NOT NULL,
        province            TEXT NOT NULL,
        global_customer_id  TEXT NOT NULL
    """,
    "feature_values_monthly": """
        global_customer_id  TEXT NOT NULL,
        customer_id         TEXT NOT NULL,
        pnl                 TEXT NOT NULL,
        snapshot_month      TEXT NOT NULL,
        feature_name        TEXT NOT NULL,
        feature_value       TEXT,
        value_type          TEXT
    """,
}

CSV_FOR = {
    "transactions": "transactions.csv",
    "events": "events.csv",
    "feature_values_monthly": "feature_values_monthly.csv",
}


def views_sql(schema):
    """Mirror the analytics fact views so the scanner's SQL is schema-agnostic.

    No column comments here. Comments exist to steer an LLM reading the
    analytics surface; nothing reads this schema but the scanner, and adding
    them would only make the fixture look more like production than it is.
    """
    return f"""
    DROP VIEW IF EXISTS {schema}.fact_transactions;
    DROP VIEW IF EXISTS {schema}.fact_events;
    DROP VIEW IF EXISTS {schema}.fact_customer_features;

    CREATE VIEW {schema}.fact_transactions AS
    SELECT transaction_id, transaction_date, transaction_month, company, pnl,
           product, province, status, amount AS revenue,
           customer_id, global_customer_id
    FROM {schema}.transactions;

    CREATE VIEW {schema}.fact_events AS
    SELECT event_id, event_date,
           TO_CHAR(event_date, 'YYYY-MM') AS event_month,
           company, pnl, event_name, province, customer_id, global_customer_id
    FROM {schema}.events;

    -- Long, not pivoted. The analytics view pivots to 20 named columns so an LLM
    -- does not have to spell feature names; the scanner iterates features
    -- programmatically, so the EAV shape is the convenient one here and it keeps
    -- this loader independent of the generated registry SQL.
    CREATE VIEW {schema}.fact_customer_features AS
    SELECT global_customer_id, snapshot_month, feature_name,
           NULLIF(feature_value, '')::NUMERIC AS feature_value
    FROM {schema}.feature_values_monthly
    WHERE value_type IN ('integer', 'float', 'numeric');
    """


def scenario_names():
    if not SCENARIO_DIR.exists():
        sys.exit(f"no scenarios at {SCENARIO_DIR} -- run gen_scenario_data.py first")
    return sorted(p.name for p in SCENARIO_DIR.iterdir()
                  if p.is_dir() and (p / "labels.json").exists())


def drop_all(cursor, conn):
    for name in scenario_names():
        cursor.execute(f'DROP SCHEMA IF EXISTS "scenario_{name}" CASCADE')
        print(f"  dropped scenario_{name}")
    conn.commit()


def load_one(cursor, conn, name):
    schema = f"scenario_{name}"
    src = SCENARIO_DIR / name

    cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    cursor.execute(f'CREATE SCHEMA "{schema}"')
    cursor.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM PUBLIC')

    total = 0
    for table, ddl in TABLES.items():
        cursor.execute(f'CREATE TABLE {schema}.{table} ({ddl})')
        rows = read_csv(src / CSV_FOR[table])
        if not rows:
            print(f"    ! {table}: no rows")
            continue

        wanted = [c.split()[0] for c in
                  (line.strip() for line in ddl.strip().splitlines()) if c]
        quoted = ", ".join(f'"{c}"' for c in wanted)
        values = [tuple(None if r.get(c, "") == "" else r.get(c) for c in wanted)
                  for r in rows]
        execute_values(
            cursor,
            f"INSERT INTO {schema}.{table} ({quoted}) VALUES %s ON CONFLICT DO NOTHING",
            values, page_size=2000,
        )
        total += len(rows)
        print(f"    {table:24s} {len(rows):>7,d} rows")

    cursor.execute(views_sql(schema))

    # Fails closed regardless of what the Metabase connection is configured to see.
    cursor.execute(f'REVOKE ALL ON SCHEMA "{schema}" FROM {READER_USER}')
    cursor.execute(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM {READER_USER}')

    conn.commit()
    return total


def verify_isolation(cursor):
    """Assert the reader cannot reach any scenario schema.

    The doubled %% in the LIKE is required: psycopg2 scans the whole statement
    for placeholders, so a single one would be read as the start of a parameter.
    Keep prose out of the SQL string for the same reason.
    """
    cursor.execute(
        """
        SELECT n.nspname
        FROM pg_namespace n
        WHERE n.nspname LIKE 'scenario\\_%%'
          AND has_schema_privilege(%(reader)s, n.nspname, 'USAGE')
        """,
        {"reader": READER_USER},
    )
    leaked = [r[0] for r in cursor.fetchall()]
    if leaked:
        sys.exit(f"ISOLATION FAILURE: {READER_USER} can reach {', '.join(leaked)}")
    print(f"  isolation ok — {READER_USER} has no USAGE on any scenario schema")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--drop", action="store_true", help="drop every scenario schema and exit")
    args = ap.parse_args()

    load_env_file()
    conn = get_connection()
    cursor = conn.cursor()

    try:
        if args.drop:
            drop_all(cursor, conn)
            return

        names = args.only or scenario_names()
        for name in names:
            print(f"scenario_{name}")
            load_one(cursor, conn, name)

        verify_isolation(cursor)

        labels = []
        for name in names:
            labels.append(json.loads((SCENARIO_DIR / name / "labels.json").read_text(encoding="utf-8")))
        must = sum(1 for l in labels for e in l["expectations"] if e.get("expect_detect") is True)
        must_not = sum(1 for l in labels for e in l["expectations"] if e.get("expect_detect") is False)
        print(f"\n{len(names)} scenario(s) loaded — {must} labelled shifts to find, "
              f"{must_not} that must stay silent")
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    main()
