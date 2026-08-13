"""Provision the MetaBot POC Metabase instance against the BI warehouse.

Idempotent: safe to re-run. Each step checks for what it would create before
creating it, so a partial run can simply be repeated.

Steps
  1. Wait for the Metabase HTTP API.
  2. Complete first-time setup, or log in if an admin already exists.
  3. Register the warehouse as a database, connecting as the read-only
     `metabase_reader` role and restricted to the `analytics` schema.
  4. Trigger a schema sync and wait for the curated views and their fields.
  5. Verify the Postgres COMMENTs arrived as table and field descriptions.
  6. Declare the foreign keys, which views cannot advertise on their own.
  7. Create the collection that will hold curated MetaBot content.

Step 5 is the point of the exercise. This POC has no :ai-controls entitlement,
so the Metabot system prompt cannot be customized, and column descriptions are
the only remaining channel into the model's context. They reach it through the
`get-tables` tool, whose handler (metabase.metabot.table-utils/database-tables)
returns :description for both tables and columns. Note that the other context
path, the raw DDL sample from format-table-ddl, carries types only — so if the
descriptions do not sync, they are silently absent rather than an error.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]


def load_env_file(path=HERE / ".env"):
    """Real environment variables win over the file."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


load_env_file()

BASE_URL = os.getenv("METABOT_SITE_URL", "http://localhost:3000").rstrip("/")

ADMIN_EMAIL = os.getenv("METABOT_ADMIN_EMAIL", "admin@metabot.local")
ADMIN_PASSWORD = os.getenv("METABOT_ADMIN_PASSWORD")
ADMIN_FIRST_NAME = os.getenv("METABOT_ADMIN_FIRST_NAME", "POC")
ADMIN_LAST_NAME = os.getenv("METABOT_ADMIN_LAST_NAME", "Admin")

# Reached over the Compose network, so the service name and internal port --
# not the host-side 5433 that load_warehouse.py uses.
WAREHOUSE_DB = os.getenv("WAREHOUSE_DB", "bi_warehouse")
READER_USER = os.getenv("WAREHOUSE_READER_USER", "metabase_reader")
READER_PASSWORD = os.getenv("WAREHOUSE_READER_PASSWORD")

DB_DISPLAY_NAME = os.getenv("METABOT_DB_NAME", "BI Warehouse")
COLLECTION_NAME = os.getenv("METABOT_COLLECTION_NAME", "BI Analytics")

EXPECTED_TABLES = {
    "fact_transactions": 31685,
    "fact_events": 40000,
    "dim_customer": 4000,
    "dim_global_customer": 2600,
    "fact_customer_features": 2400,
    "dim_feature_catalogue": 34,
}

# Declared join paths, as (table, column) -> (target table, target column).
#
# Postgres exposes no foreign keys on views, so Metabase's sync finds none and
# Metabot sees five unrelated tables. These have to be set through the API.
#
# Every arrow points at dim_global_customer.global_customer_id because it is the
# only unique key among them. Metabase FKs are single-column, and the other
# candidate keys are composite — (customer_id, pnl) for the facts,
# (global_customer_id, snapshot_month) for the features — so an FK onto any of
# them would join one row to many and inflate every aggregate downstream.
FK_LINKS = {
    ("fact_transactions", "global_customer_id"): ("dim_global_customer", "global_customer_id"),
    ("fact_events", "global_customer_id"): ("dim_global_customer", "global_customer_id"),
    ("fact_customer_features", "global_customer_id"): ("dim_global_customer", "global_customer_id"),
    ("dim_customer", "global_customer_id"): ("dim_global_customer", "global_customer_id"),
}

_session_token = None


class ProvisionError(Exception):
    pass


def call(method, path, body=None, expect_json=True):
    url = f"{BASE_URL}/api{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if _session_token:
        req.add_header("X-Metabase-Session", _session_token)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return json.loads(raw) if expect_json and raw else raw
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:600]
        raise ProvisionError(f"{method} {path} -> {exc.code}\n{detail}") from None
    except urllib.error.URLError as exc:
        raise ProvisionError(f"{method} {path} -> {exc.reason}") from None


def wait_for_health(timeout=300):
    print(f"Waiting for {BASE_URL} ...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            call("GET", "/health")
            print("  up")
            return
        except ProvisionError:
            time.sleep(3)
    raise ProvisionError(
        f"Metabase did not become healthy within {timeout}s. "
        "If the image is still building, wait for the build and re-run."
    )


def authenticate():
    """Run first-time setup if no admin exists yet, otherwise log in."""
    global _session_token

    if not ADMIN_PASSWORD:
        raise ProvisionError(
            "METABOT_ADMIN_PASSWORD is not set. Add it to dev/metabot-poc/.env.\n"
            "Metabase requires a reasonably strong password."
        )

    props = call("GET", "/session/properties")

    if not props.get("has-user-setup"):
        token = props.get("setup-token")
        if not token:
            raise ProvisionError("Setup is incomplete but no setup-token was offered.")
        print("Running first-time setup...")
        result = call(
            "POST",
            "/setup",
            {
                "token": token,
                "user": {
                    "email": ADMIN_EMAIL,
                    "password": ADMIN_PASSWORD,
                    "first_name": ADMIN_FIRST_NAME,
                    "last_name": ADMIN_LAST_NAME,
                },
                "prefs": {"site_name": "MetaBot POC"},
            },
        )
        _session_token = result["id"]
        print(f"  admin created: {ADMIN_EMAIL}")
        return

    print("Logging in...")
    result = call("POST", "/session", {"username": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    _session_token = result["id"]
    print(f"  authenticated as {ADMIN_EMAIL}")


def ensure_database():
    if not READER_PASSWORD:
        raise ProvisionError("WAREHOUSE_READER_PASSWORD is not set.")

    existing = call("GET", "/database")
    for db in existing.get("data", existing if isinstance(existing, list) else []):
        if db.get("name") == DB_DISPLAY_NAME:
            print(f"Database already registered: {DB_DISPLAY_NAME} (id={db['id']})")
            return db["id"]

    print(f"Registering database: {DB_DISPLAY_NAME}")
    created = call(
        "POST",
        "/database",
        {
            "name": DB_DISPLAY_NAME,
            "engine": "postgres",
            "details": {
                # Service name on the Compose network, not localhost:5433.
                "host": "warehouse",
                "port": 5432,
                "dbname": WAREHOUSE_DB,
                "user": READER_USER,
                "password": READER_PASSWORD,
                "ssl": False,
                # The role is already confined to analytics; this keeps the
                # sync from even attempting the other schemas.
                "schema-filters-type": "inclusion",
                "schema-filters-patterns": "analytics",
            },
        },
    )
    print(f"  created (id={created['id']}) as {READER_USER}, schema=analytics")
    return created["id"]


def sync_and_wait(db_id, timeout=300):
    """Sync, then wait for the field lists to stop changing.

    Waiting only for "every table has at least one field" is not enough. Sync
    populates fields progressively, so that condition can be satisfied by a
    partial list -- and a newly added column would then skip verify_descriptions
    entirely, which defeats the point of having a gate. Observed exactly that:
    a nine-column view reported as 8/8 described.

    So require the same field counts twice in a row before believing them.
    """
    print("Syncing schema...")
    call("POST", f"/database/{db_id}/sync_schema", {})

    deadline = time.time() + timeout
    previous = None
    while time.time() < deadline:
        tables = call("GET", f"/database/{db_id}/metadata").get("tables", [])
        found = {t["name"]: t for t in tables if t["name"] in EXPECTED_TABLES}
        complete = len(found) == len(EXPECTED_TABLES) and all(
            t.get("fields") for t in found.values()
        )
        if complete:
            counts = {name: len(t["fields"]) for name, t in found.items()}
            if counts == previous:
                for name, t in sorted(found.items()):
                    print(f"  {name}: {len(t['fields'])} fields")
                return found
            previous = counts
        time.sleep(4)

    raise ProvisionError(
        f"Sync did not settle on a stable field list for {sorted(EXPECTED_TABLES)} "
        f"within {timeout}s."
    )


def verify_descriptions(tables):
    """The whole COMMENT ON strategy rests on this actually having synced."""
    print("Verifying descriptions reached Metabase...")
    problems = []

    for name, table in sorted(tables.items()):
        if not (table.get("description") or "").strip():
            problems.append(f"table {name} has no description")

        undescribed = [
            f["name"]
            for f in table.get("fields", [])
            if not (f.get("description") or "").strip()
        ]
        if undescribed:
            problems.append(f"{name}: fields without description -> {undescribed}")

        described = len(table.get("fields", [])) - len(undescribed)
        print(f"  {name}: {described}/{len(table.get('fields', []))} fields described")

    if problems:
        print("\n  DESCRIPTIONS DID NOT SYNC:")
        for p in problems:
            print(f"    - {p}")
        print(
            "\n  Metabot reads these through the get-tables tool. Without them it\n"
            "  sees column names and types only, and this POC cannot compensate\n"
            "  via the system prompt (no :ai-controls entitlement)."
        )
        return False

    print("  all tables and fields carry descriptions")
    return True


def ensure_fk_metadata(tables):
    """Declare the join paths Postgres cannot tell Metabase about.

    Marking the source column type/FK and pointing it at the target field is
    what puts the table in Metabot's reach when it builds a joined query, and
    what makes the relationship visible in the notebook editor.

    Also marks the target itself as an entity key, so Metabase treats it as the
    identifying column rather than a value to aggregate.
    """
    print("Declaring foreign keys...")

    def find_field(table_name, column):
        table = tables.get(table_name)
        if not table:
            raise ProvisionError(f"{table_name} missing from sync — cannot link FKs.")
        for f in table.get("fields", []):
            if f["name"] == column:
                return f
        raise ProvisionError(f"{table_name}.{column} not found in synced fields.")

    targets = {t for t in FK_LINKS.values()}
    for table_name, column in sorted(targets):
        field = find_field(table_name, column)
        if field.get("semantic_type") != "type/PK":
            call("PUT", f"/field/{field['id']}", {"semantic_type": "type/PK"})
            print(f"  {table_name}.{column}: marked entity key")

    changed = 0
    for (table_name, column), (target_table, target_column) in sorted(FK_LINKS.items()):
        field = find_field(table_name, column)
        target = find_field(target_table, target_column)

        if (field.get("semantic_type") == "type/FK"
                and field.get("fk_target_field_id") == target["id"]):
            continue

        call("PUT", f"/field/{field['id']}", {
            "semantic_type": "type/FK",
            "fk_target_field_id": target["id"],
        })
        print(f"  {table_name}.{column} -> {target_table}.{target_column}")
        changed += 1

    if not changed:
        print("  already declared")
    return len(FK_LINKS)


def ensure_collection():
    existing = call("GET", "/collection")
    for c in existing:
        if c.get("name") == COLLECTION_NAME:
            print(f"Collection already exists: {COLLECTION_NAME} (id={c['id']})")
            return c["id"]

    print(f"Creating collection: {COLLECTION_NAME}")
    created = call(
        "POST",
        "/collection",
        {
            "name": COLLECTION_NAME,
            "description": (
                "Curated models and metrics for MetaBot. Sourced only from the "
                "analytics schema of the BI warehouse."
            ),
        },
    )
    print(f"  created (id={created['id']})")
    return created["id"]


def metric_specs(db_id, tables):
    """The three measures the demo questions are built around.

    Metabot can already aggregate the raw views, so these exist to name the
    measures in business terms and to pin their definition -- particularly the
    `completed` filter, which is what "doanh thu" means to the business even
    though every row in this dataset happens to satisfy it.
    """
    def field(table, name):
        for f in tables[table]["fields"]:
            if f["name"] == name:
                return ["field", f["id"], {"base-type": f["base_type"]}]
        raise ProvisionError(f"{table}.{name} not found — did the sync change?")

    tx = tables["fact_transactions"]["id"]
    ev = tables["fact_events"]["id"]
    completed = ["=", field("fact_transactions", "status"), "completed"]

    return [
        {
            "name": "Doanh thu",
            "description": (
                "Tổng doanh thu (VND) của các giao dịch completed. Dùng cho câu hỏi "
                "về doanh thu, revenue, doanh số. Lưu ý: doanh thu VinFast bằng 0 "
                "trên toàn bộ dữ liệu nên chỉ có ý nghĩa với GSM."
            ),
            "query": {"source-table": tx,
                      "aggregation": [["sum", field("fact_transactions", "revenue")]],
                      "filter": completed},
        },
        {
            "name": "Số giao dịch",
            "description": (
                "Số lượng giao dịch completed. Dùng cho câu hỏi về số giao dịch, "
                "lượng giao dịch, transaction count."
            ),
            "query": {"source-table": tx, "aggregation": [["count"]], "filter": completed},
        },
        {
            "name": "Số event",
            "description": (
                "Số lượng event của người dùng trên app. Dùng cho câu hỏi về event, "
                "sự kiện, tương tác. Không liên quan tới doanh thu."
            ),
            "query": {"source-table": ev, "aggregation": [["count"]]},
        },
    ]


def ensure_metrics(db_id, tables, collection_id):
    items = call("GET", f"/collection/{collection_id}/items")
    existing = {i["name"]: i for i in items.get("data", []) if i.get("model") == "metric"}

    created = []
    for spec in metric_specs(db_id, tables):
        if spec["name"] in existing:
            print(f"  {spec['name']}: already exists (id={existing[spec['name']]['id']})")
            created.append(existing[spec["name"]]["id"])
            continue
        card = call("POST", "/card", {
            "name": spec["name"],
            "type": "metric",
            "description": spec["description"],
            "dataset_query": {"database": db_id, "type": "query", "query": spec["query"]},
            "display": "scalar",
            "visualization_settings": {},
            "collection_id": collection_id,
        })
        print(f"  {spec['name']}: created (id={card['id']})")
        created.append(card["id"])
    return created


def main():
    wait_for_health()
    authenticate()
    db_id = ensure_database()
    tables = sync_and_wait(db_id)
    described = verify_descriptions(tables)
    fk_count = ensure_fk_metadata(tables)
    collection_id = ensure_collection()

    print("Creating metrics...")
    metrics = ensure_metrics(db_id, tables, collection_id)

    print("\n" + "=" * 60)
    print(f"Database   id={db_id}  ({DB_DISPLAY_NAME})")
    print(f"Collection id={collection_id}  ({COLLECTION_NAME})")
    print(f"Tables     {len(tables)} synced, {fk_count} join paths declared")
    print(f"Metrics    {len(metrics)} in collection")
    print(f"Descriptions synced: {'yes' if described else 'NO'}")
    print("=" * 60)
    print(
        "\nNext: configure an LLM provider in Admin > AI, or set\n"
        "MB_LLM_METABOT_PROVIDER and the matching MB_LLM_*_API_KEY on the\n"
        "metabase service, then work through dev/metabot-poc/DEMO_QUESTIONS.md."
    )
    return 0 if described else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ProvisionError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(2)
