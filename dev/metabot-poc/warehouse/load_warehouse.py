"""Load the MetaBot POC warehouse from the local BI pipeline CSVs.

Adapted from ``scripts/load_to_postgres.py`` in the previous BI project. Four
differences:

* Only the Silver and Gold layers are loaded. Bronze is a near-duplicate of
  Silver and nothing in this POC reads it.
* The curated views come from ``04_init_analytics_views.sql``, which exposes
  fact-grain views rather than the old monthly aggregates.
* The Feature Store is loaded too — registry from JSON, serving values from
  CSV — and surfaced to BI through the pivoted view in ``07``.
* A read-only Metabase login is provisioned here, granted on ``analytics``
  only, so the BI connection cannot browse Silver, Gold or the Feature Store.

The CSV source lives outside the repository (``local-context/`` is untracked).
Point ``PIPELINE_DIR`` at it with the ``WAREHOUSE_PIPELINE_DIR`` environment
variable.
"""

import csv
import json
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
    "05_init_feature_store.sql",
    "06_init_analytics_dim_customer.sql",
    # Generated from the registry — see gen_feature_view_sql.py.
    "07_init_analytics_features.sql",
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

CURATED_VIEWS = [
    "fact_transactions",
    "fact_events",
    "dim_customer",
    "dim_global_customer",
    "fact_customer_features",
    "dim_feature_catalogue",
]

# The Feature Store arrives in two pieces with different formats: the registry
# is the governed JSON contract, the values are a serving CSV export.
FEATURE_REGISTRY_JSON = PIPELINE_DIR / "feature_store" / "registry_1.0.0.json"
FEATURE_VALUES_CSV = PIPELINE_DIR / "serving" / "feature_values_monthly_v1_0_0.csv"

# JSON key -> registry column, for the two that differ. Everything else matches.
REGISTRY_KEY_MAP = {"owner": "owner_name", "window": "window_name"}
# Stored as JSONB, so they have to be serialised rather than passed as lists.
REGISTRY_JSON_COLUMNS = ("governance_decision_ids", "assumption_ids", "dq_checks")

FEATURE_STORE_TABLES = [
    ("feature_store", "feature_registry"),
    ("feature_store", "feature_values_monthly"),
]


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


def load_feature_store(cursor):
    """Load the Feature Store registry and its monthly serving values.

    Kept out of LOAD_PLAN because neither piece is a plain schema/table.csv: the
    registry is JSON keyed by a contract version, and the values CSV is named
    after the version it serves. The registry must land first — the values table
    has a foreign key into it, which is the mechanism that stops an unregistered
    feature from being served.
    """
    if not FEATURE_REGISTRY_JSON.exists():
        print(f"  ! missing {FEATURE_REGISTRY_JSON} — skipping feature store")
        return 0

    registry = json.loads(FEATURE_REGISTRY_JSON.read_text(encoding="utf-8"))
    version = registry["contract_version"]

    # Children before parents: the FK points values -> registry.
    cursor.execute("TRUNCATE TABLE feature_store.feature_values_monthly")
    cursor.execute("TRUNCATE TABLE feature_store.feature_registry CASCADE")

    columns = [
        "registry_version", "feature_name", "domain", "entity", "grain",
        "window_name", "source_artifact", "source_column", "owner_name",
        "semantic_status", "business_approval_status", "source_metadata_status",
        "definition_source", "value_type", "nullable",
        "governance_decision_ids", "assumption_ids", "dq_checks",
        "review_group_id", "review_decision_hash", "provenance_hash",
    ]
    reverse_map = {v: k for k, v in REGISTRY_KEY_MAP.items()}

    rows = []
    for feature in registry["features"]:
        values = []
        for column in columns:
            if column == "registry_version":
                values.append(version)
                continue
            raw = feature[reverse_map.get(column, column)]
            values.append(json.dumps(raw) if column in REGISTRY_JSON_COLUMNS else raw)
        rows.append(tuple(values))

    quoted = ", ".join(f'"{c}"' for c in columns)
    execute_values(
        cursor,
        f"INSERT INTO feature_store.feature_registry ({quoted}) VALUES %s",
        rows,
    )
    print(f"  - feature_store.feature_registry: {len(rows)} (registry {version})")

    values_rows = read_csv(FEATURE_VALUES_CSV)
    n = load_table(cursor, "feature_store", "feature_values_monthly", values_rows)
    if n:
        print(f"  - feature_store.feature_values_monthly: {n}")
    return len(rows) + n


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
    for schema, table in LOAD_PLAN + FEATURE_STORE_TABLES:
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

    print("\nLoading feature store...")
    total += load_feature_store(cursor)
    conn.commit()

    print("\nConfiguring read-only access...")
    configure_reader_role(cursor, conn)

    verify(cursor)

    cursor.close()
    conn.close()
    print(f"\nDone. {total} rows loaded.")


if __name__ == "__main__":
    sys.exit(main())
