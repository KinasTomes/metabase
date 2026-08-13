"""Give every finding a saved Metabase question to drill into.

A summary that says "Binh Duong rose 45%" is a claim. The same summary with a
link to a chart of the monthly series is a claim the reader can check in one
click, and checking is the point -- the reader is the last line of defence
against a scanner or a narration that got something wrong.

Questions are MBQL, built from the same series definitions the scan uses, so the
chart shows the figure the finding quotes rather than something that merely
resembles it. Names are deterministic, so re-running reuses the card instead of
littering the collection.

ONLY WORKS AGAINST `analytics`, AND THAT IS CORRECT
---------------------------------------------------
Scenario schemas are invisible to Metabase by design -- an inclusion filter on
the connection plus an explicit REVOKE. So a report scanned from a fixture gets
no drill-down links, and that is the isolation working, not a gap to patch.
Making the whale or Tet findings clickable would mean showing Metabase
fabricated rows, which is the failure the whole scenario/analytics split exists
to prevent.

Usage:
    python link_questions.py out/analytics.json
    python link_questions.py out/analytics.json --collection "Cảnh báo dữ liệu"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))

from provision_metabase import (  # noqa: E402
    BASE_URL,
    ProvisionError,
    authenticate,
    call,
)

COLLECTION_NAME = "Cảnh báo dữ liệu"

# metric -> (view, month column, aggregation, filter column). The scan's series
# definitions restated in MBQL terms; kept beside each other so a change to one
# is visibly a change to both.
SERIES = {
    "transaction_count":             ("fact_transactions", "transaction_month", ("count",), None),
    "transaction_count_by_company":  ("fact_transactions", "transaction_month", ("count",), "company"),
    "transaction_count_by_product":  ("fact_transactions", "transaction_month", ("count",), "product"),
    "transaction_count_by_province": ("fact_transactions", "transaction_month", ("count",), "province"),
    "revenue_total":                 ("fact_transactions", "transaction_month", ("sum", "revenue"), "company"),
    "active_customers":              ("fact_transactions", "transaction_month",
                                      ("distinct", "global_customer_id"), None),
    "event_count":                   ("fact_events", "event_month", ("count",), None),
    "event_count_by_name":           ("fact_events", "event_month", ("count",), "event_name"),
    "feature_wmean":                 ("fact_customer_features", "snapshot_month", ("avg",), None),
}


def load_tables(db_id):
    """name -> {id, fields}, for the views the scan reads."""
    meta = call("GET", f"/database/{db_id}/metadata")
    return {t["name"]: t for t in meta.get("tables", [])}


def field_ref(table, name):
    for f in table.get("fields", []):
        if f["name"] == name:
            return ["field", f["id"], {"base-type": f["base_type"]}]
    raise ProvisionError(f"{table['name']}.{name} not found — has the sync run?")


def build_query(db_id, tables, finding):
    """MBQL reproducing the finding's series, broken out by month."""
    metric = (finding["metric"] or "").removesuffix("_trend")
    spec = SERIES.get(metric)
    if not spec:
        return None, None
    view_name, month_col, agg, filter_col = spec
    table = tables.get(view_name)
    if not table:
        return None, None

    dim = finding.get("dimension")

    if agg[0] == "avg":
        # The feature view is pivoted, so the dimension IS the column to average
        # rather than a value to filter on.
        if not dim:
            return None, None
        aggregation = [["avg", field_ref(table, dim)]]
    elif len(agg) == 1:
        aggregation = [[agg[0]]]
    else:
        aggregation = [[agg[0], field_ref(table, agg[1])]]

    query = {
        "source-table": table["id"],
        "aggregation": aggregation,
        "breakout": [field_ref(table, month_col)],
    }
    if filter_col and dim and agg[0] != "avg":
        query["filter"] = ["=", field_ref(table, filter_col), dim]

    title = finding.get("title") or metric
    label = f"{title} — {dim}" if dim else f"{title} — toàn hệ thống"
    return {"database": db_id, "type": "query", "query": query}, label


def ensure_collection(name):
    for c in call("GET", "/collection"):
        if c.get("name") == name and not c.get("archived"):
            return c["id"]
    created = call("POST", "/collection", {
        "name": name,
        "description": ("Biểu đồ đi kèm các phát hiện của bản quét dữ liệu hằng "
                        "đêm. Tạo tự động bởi nightly/link_questions.py."),
    })
    return created["id"]


def existing_cards(collection_id):
    items = call("GET", f"/collection/{collection_id}/items")
    return {i["name"]: i["id"] for i in items.get("data", [])
            if i.get("model") == "card"}


def link(report, collection_name=COLLECTION_NAME, dry_run=False):
    if report.get("schema") != "analytics":
        return {"skipped": f"schema {report.get('schema')} không hiển thị trong "
                           f"Metabase — dữ liệu thử nghiệm được cô lập có chủ đích"}

    authenticate()
    databases = call("GET", "/database").get("data", [])
    db = next((d for d in databases if d.get("engine") == "postgres"), None)
    if not db:
        raise ProvisionError("no postgres database registered in Metabase")

    tables = load_tables(db["id"])
    collection_id = ensure_collection(collection_name)
    known = existing_cards(collection_id)

    linked, skipped = 0, 0
    for finding in report.get("findings", []):
        dataset_query, label = build_query(db["id"], tables, finding)
        if not dataset_query:
            skipped += 1
            continue

        card_id = known.get(label)
        if card_id is None and not dry_run:
            card = call("POST", "/card", {
                "name": label,
                "description": (f"Chuỗi theo tháng đứng sau phát hiện "
                                f"{finding['metric']}. Tạo tự động."),
                "dataset_query": dataset_query,
                "display": "line",
                "visualization_settings": {},
                "collection_id": collection_id,
            })
            card_id = card["id"]
            known[label] = card_id

        if card_id is not None:
            finding["drill_url"] = f"{BASE_URL}/question/{card_id}"
            linked += 1

    return {"collection": collection_name, "collection_id": collection_id,
            "linked": linked, "skipped": skipped}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings")
    ap.add_argument("--collection", default=COLLECTION_NAME)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = Path(args.findings)
    report = json.loads(path.read_text(encoding="utf-8"))
    result = link(report, args.collection, args.dry_run)

    if "skipped" in result and "linked" not in result:
        print(f"  bỏ qua: {result['skipped']}")
        return

    if not args.dry_run:
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"  {result['linked']} phát hiện có link, {result['skipped']} không dựng "
          f"được truy vấn -> collection «{result['collection']}»")
    for f in report.get("findings", []):
        if f.get("drill_url"):
            print(f"    {f['metric']}/{f.get('dimension') or 'overall'}  {f['drill_url']}")


if __name__ == "__main__":
    main()
