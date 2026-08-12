"""Load the MetaBot POC warehouse from the local BI pipeline CSVs.

Adapted from ``scripts/load_to_postgres.py`` in the previous BI project. Three
differences:

* Only the Silver and Gold layers are loaded. Bronze is a near-duplicate of
  Silver and nothing in this POC reads it.
* The curated views come from ``04_init_analytics_views.sql``, which exposes
  fact-grain views rather than the old monthly aggregates.
* A read-only Metabase login is provisioned here, granted on ``analytics``
  only, so the BI connection cannot browse Silver or Gold.

The CSV source lives outside the repository (``local-context/`` is untracked).
Point ``PIPELINE_DIR`` at it with the ``WAREHOUSE_PIPELINE_DIR`` environment
variable.
"""

import csv
import os
import sys
from pathlib import Path

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
SQL_DIR = HERE / "sql"


def load_env_file(path=HERE.parent / ".env"):
    """Read dev/metabot-poc/.env so the passwords live in one place.

    Real environment variables win, which keeps CI and one-off overrides
    working without editing the file.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

_pipeline = os.getenv("WAREHOUSE_PIPELINE_DIR")
# Resolve a relative override against the repo root, not the shell's cwd, so
# the script behaves the same whichever directory it is invoked from.
PIPELINE_DIR = (
    (REPO_ROOT / _pipeline).resolve()
    if _pipeline
    else REPO_ROOT / "local-context" / "data" / "pipeline"
)

DB_HOST = os.getenv("WAREHOUSE_HOST", "localhost")
DB_PORT = int(os.getenv("WAREHOUSE_PORT", "5433"))
DB_NAME = os.getenv("WAREHOUSE_DB", "bi_warehouse")
DB_USER = os.getenv("WAREHOUSE_USER", "postgres")
DB_PASS = os.getenv("WAREHOUSE_PASSWORD", "postgres")

# Least-privilege login handed to Metabase. Separate from the superuser above.
READER_USER = os.getenv("WAREHOUSE_READER_USER", "metabase_reader")
READER_PASSWORD = os.getenv("WAREHOUSE_READER_PASSWORD")

DDL_FILES = [
    "01_init_bronze_silver_gold.sql",
    "04_init_analytics_views.sql",
]

# Load order respects the foreign keys declared in the Silver DDL:
# transactions/events/loyalty reference customers, which references
# dim_global_customer.
LOAD_PLAN = [
    ("silver", "dim_global_customer"),
    ("silver", "customers"),
    ("silver", "transactions"),
    ("silver", "events"),
    ("silver", "loyalty_transactions"),
    ("gold", "gold_monthly_pnl"),
    ("gold", "gold_monthly_global"),
    ("gold", "gold_customer_monthly"),
]

CURATED_VIEWS = ["fact_transactions", "fact_events"]


def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )


def read_csv(path):
    if not path.exists():
        print(f"  ! missing {path}")
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_table(cursor, schema, table, rows):
    if not rows:
        print(f"  - {schema}.{table}: skipped (no rows)")
        return 0

    cols = list(rows[0].keys())
    quoted = ", ".join(f'"{c}"' for c in cols)
    query = f"INSERT INTO {schema}.{table} ({quoted}) VALUES %s ON CONFLICT DO NOTHING"

    # Empty CSV cells mean NULL, not empty string. NUMERIC and TIMESTAMPTZ
    # columns reject '' outright, so this conversion is load-bearing.
    values = [tuple(None if v == "" else v for v in r.values()) for r in rows]

    execute_values(cursor, query, values, page_size=1000)
    return len(rows)


def run_ddl(cursor, conn):
    for name in DDL_FILES:
        path = SQL_DIR / name
        if not path.exists():
            raise SystemExit(f"DDL file not found: {path}")
        print(f"  - {name}")
        cursor.execute(path.read_text(encoding="utf-8"))
        conn.commit()


def configure_reader_role(cursor, conn):
    """Create (or update) the read-only Metabase login, scoped to analytics."""
    if not READER_PASSWORD:
        print("  ! WAREHOUSE_READER_PASSWORD unset — skipping reader role")
        return

    ident = sql.Identifier(READER_USER)
    cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER_USER,))
    if cursor.fetchone():
        cursor.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD %s").format(ident),
            (READER_PASSWORD,),
        )
    else:
        cursor.execute(
            sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(ident),
            (READER_PASSWORD,),
        )

    cursor.execute(
        sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
            sql.Identifier(DB_NAME), ident
        )
    )
    # analytics only. Silver and Gold stay invisible to the BI connection even
    # though they live in the same database.
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA analytics TO {}").format(ident))
    cursor.execute(
        sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO {}").format(ident)
    )
    cursor.execute(
        sql.SQL(
            "ALTER DEFAULT PRIVILEGES IN SCHEMA analytics GRANT SELECT ON TABLES TO {}"
        ).format(ident)
    )
    cursor.execute(
        sql.SQL("ALTER ROLE {} IN DATABASE {} SET search_path TO analytics").format(
            ident, sql.Identifier(DB_NAME)
        )
    )
    conn.commit()
    print(f"  - {READER_USER}: SELECT on analytics")


def verify(cursor):
    print("\nRow counts:")
    for schema, table in LOAD_PLAN:
        cursor.execute(f"SELECT COUNT(*) FROM {schema}.{table}")
        print(f"  - {schema}.{table}: {cursor.fetchone()[0]}")

    print("\nCurated views:")
    for view in CURATED_VIEWS:
        cursor.execute(f"SELECT COUNT(*) FROM analytics.{view}")
        print(f"  - analytics.{view}: {cursor.fetchone()[0]}")


def main():
    if not PIPELINE_DIR.exists():
        raise SystemExit(
            f"Pipeline directory not found: {PIPELINE_DIR}\n"
            "Set WAREHOUSE_PIPELINE_DIR to the directory holding silver/ and gold/."
        )

    print(f"Source: {PIPELINE_DIR}")
    print(f"Target: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}\n")

    try:
        conn = get_connection()
    except psycopg2.Error as exc:
        raise SystemExit(f"Cannot connect to warehouse: {exc}")

    conn.autocommit = False
    cursor = conn.cursor()

    print("Applying DDL...")
    run_ddl(cursor, conn)

    # Reverse order so children are cleared before their parents.
    print("\nTruncating...")
    for schema, table in reversed(LOAD_PLAN):
        cursor.execute(f"TRUNCATE TABLE {schema}.{table} CASCADE")

    print("\nLoading...")
    total = 0
    for schema, table in LOAD_PLAN:
        rows = read_csv(PIPELINE_DIR / schema / f"{table}.csv")
        n = load_table(cursor, schema, table, rows)
        if n:
            print(f"  - {schema}.{table}: {n}")
        total += n
    conn.commit()

    print("\nConfiguring read-only access...")
    configure_reader_role(cursor, conn)

    verify(cursor)

    cursor.close()
    conn.close()
    print(f"\nDone. {total} rows loaded.")


if __name__ == "__main__":
    sys.exit(main())
