"""Generate sql/07_init_analytics_features.sql from the feature registry.

The serving table is EAV — one row per (customer, month, feature name), 163,200
rows for 34 features. That shape is hostile to a text-to-SQL agent: answering
"how many GSM trips did this customer complete in the last 3 months" means
knowing that the literal string 'gsm_transaction_completed_txn_count_l3m'
exists, and getting it exactly right. Everything that has worked in this POC has
worked because the model could see a column name and its description.

So the analytics surface is a pivot, and each column gets a COMMENT ON built
from its registry entry. The registry already carries domain, window and value
type, so the descriptions are derived rather than invented, and they cannot
drift from the governed metadata.

Two surfaces, not one
---------------------
The registry is a catalogue of what has been *defined*; it is not evidence that
a measure can be *answered*. Those come apart for cancelled transactions:

* transaction_status_semantics_v1 (mentor-approved) makes `cancelled` a real
  business status, reported separately from `completed`.
* data_contract.json pins transactions.status to ["completed"], so no cancelled
  row was ever materialised into the fact layer, and nothing downstream
  reconciles against one.
* Holdout question H008, "cancelled GSM transactions by province", is marked
  `unsupported` for exactly that reason.

The registry still carries 14 cancelled features with values in serving. Pivot
them into a queryable column and the agent will answer H008 with a confident
number sourced from an unreconciled snapshot — the failure the review was
written to prevent, arriving through the semantic layer rather than the prompt.

So the split is structural: cancelled features are withheld from the fact view
and published in a catalogue view instead, with the reason attached as data. The
agent can then discover that cancelled exists and say why it cannot be served,
without either hallucinating a number or denying the concept.

Writing the SQL out to a file rather than executing a generated string keeps the
DDL reviewable in git — a diff shows exactly which features moved between the
two surfaces when the registry moves to 1.1.0.

Usage:
    python dev/metabot-poc/warehouse/gen_feature_view_sql.py
    python dev/metabot-poc/warehouse/gen_feature_view_sql.py --check
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
OUT_PATH = HERE / "sql" / "07_init_analytics_features.sql"
REGISTRY_PATH = (
    REPO_ROOT / "local-context" / "data" / "pipeline" / "feature_store" / "registry_1.0.0.json"
)

# Window suffix -> (English, Vietnamese). The registry stores the raw suffix.
WINDOWS = {
    "daily": ("on the snapshot day", "trong ngày"),
    "l1w": ("over the last 7 days", "trong 7 ngày gần nhất"),
    "l2w": ("over the last 14 days", "trong 14 ngày gần nhất"),
    "l1m": ("over the last 1 month", "trong 1 tháng gần nhất"),
    "l3m": ("over the last 3 months", "trong 3 tháng gần nhất"),
    "l6m": ("over the last 6 months", "trong 6 tháng gần nhất"),
    "l12m": ("over the last 12 months", "trong 12 tháng gần nhất"),
}


# Why a feature is defined but cannot answer a question. Keyed by the marker
# found in the feature name; the text lands in the catalogue view as data, so
# the model can quote a reason instead of improvising one.
WITHHELD_REASON = (
    "Defined and mentor-approved as a business status, but no cancelled "
    "transaction has been materialised into the fact layer: the data contract "
    "pins transactions.status to 'completed' only. The serving snapshot holds "
    "values for this feature, but nothing reconciles them against a fact, so "
    "they must not be reported as a figure. Answer that cancelled exists as a "
    "concept and that no verified cancelled fact is available yet."
)


def is_servable(feature_name):
    """Cancelled features are catalogue-only. See the module docstring."""
    return "cancel" not in feature_name.lower()


def unit_of(domain):
    return "GSM" if domain.startswith("gsm") else "VinFast"


def measure_of(feature_name, domain, window):
    """Strip the domain prefix and window suffix to get the measure name.

    GSM and VinFast disagree on word order for the same measure — GSM writes
    canceled_txn_count, VinFast writes txn_canceled_count — so the measure is
    classified by keyword rather than by matching a fixed vocabulary.
    """
    core = feature_name[len(domain) + 1 : -(len(window) + 1)]
    if "event" in core:
        return "app events", "sự kiện trên app"
    if "cancel" in core:
        return "cancelled transactions", "giao dịch bị huỷ"
    if "completed" in core:
        return "completed transactions", "giao dịch hoàn thành"
    raise SystemExit(f"Unrecognised measure in {feature_name!r} (core={core!r})")


def column_comment(feature):
    unit = unit_of(feature["domain"])
    win_en, win_vi = WINDOWS[feature["window"]]
    meas_en, meas_vi = measure_of(
        feature["feature_name"], feature["domain"], feature["window"]
    )
    return (
        f"Number of {unit} {meas_en} for this customer {win_en} "
        f"(số {meas_vi} của {unit} {win_vi}), as of the snapshot month. "
        f"Registry feature {feature['feature_name']}."
    )


def sql_literal(text):
    return "'" + text.replace("'", "''") + "'"


VIEW_HEADER = """\
-- GENERATED by gen_feature_view_sql.py from the feature registry. Do not edit
-- by hand — rerun the generator instead.
--
-- Pivots feature_store.feature_values_monthly into one row per customer per
-- month with one column per registered feature.
--
-- Grain is (global_customer_id, snapshot_month), not (customer_id, pnl, month).
-- The serving table stores each global customer twice, once under each PnL, and
-- fills the other unit's features with NULL. Verified against the source: no
-- (global_customer_id, month, feature) key has two non-null values, so folding
-- the pair together with MAX is lossless and gives something better than either
-- half — a single row holding both GSM and VinFast features side by side. That
-- is what makes cross-unit comparison possible without a self-join.
--
-- Only the newest snapshot is exposed. The serving table is content-addressed
-- and appends history under a new source_snapshot_hash rather than overwriting,
-- so an unfiltered pivot would silently mix snapshots once a second one lands.

CREATE SCHEMA IF NOT EXISTS analytics;

DROP VIEW IF EXISTS analytics.fact_customer_features;

CREATE VIEW analytics.fact_customer_features AS
WITH latest_snapshot AS (
    SELECT source_snapshot_hash
    FROM feature_store.feature_values_monthly
    WHERE registry_version = {version}
    ORDER BY loaded_at DESC
    LIMIT 1
)
SELECT
    v.global_customer_id,
    v.snapshot_month,
"""

VIEW_FOOTER = """\
FROM feature_store.feature_values_monthly v
JOIN latest_snapshot s ON s.source_snapshot_hash = v.source_snapshot_hash
WHERE v.registry_version = {version}
GROUP BY v.global_customer_id, v.snapshot_month;
"""

VIEW_COMMENT = (
    "One row per customer per month with the {n} servable feature store features "
    "as columns (feature store, đặc trưng khách hàng). Covers {months} and "
    "{customers} customers only — a curated subset, NOT the full customer base in "
    "dim_global_customer. Both GSM and VinFast features sit on the same row, so "
    "cross-unit comparison needs no join. Join to analytics.dim_global_customer "
    "on global_customer_id. Completed-transaction and app-event measures only: "
    "{withheld} cancelled-transaction features are defined in the registry but "
    "deliberately NOT served here, because no cancelled transaction exists in the "
    "fact layer to reconcile them against. Look them up in "
    "analytics.dim_feature_catalogue and report the reason — never a figure."
)

CATALOGUE_SQL = """\

-- -----------------------------------------------------------------------------
-- Feature catalogue — what is defined, and what can actually be answered
-- -----------------------------------------------------------------------------
-- Published so the agent can distinguish "this measure does not exist" from
-- "this measure exists but has no verified fact behind it". Those need very
-- different answers, and without this view the agent can only guess which case
-- it is in — or worse, serve a number from the unreconciled snapshot.

DROP VIEW IF EXISTS analytics.dim_feature_catalogue;

CREATE VIEW analytics.dim_feature_catalogue AS
SELECT
    r.feature_name,
    r.domain,
    CASE WHEN r.domain LIKE 'gsm%' THEN 'GSM' ELSE 'VinFast' END AS company,
    r.window_name,
    r.value_type,
    r.business_approval_status,
    CASE WHEN r.feature_name IN (
{withheld_list}
    ) THEN 'catalogue_only' ELSE 'servable' END AS serving_status,
    CASE WHEN r.feature_name IN (
{withheld_list}
    ) THEN {reason} END AS not_servable_reason
FROM feature_store.feature_registry r
WHERE r.registry_version = {version};

COMMENT ON VIEW analytics.dim_feature_catalogue IS
    'Catalogue of every registered feature store feature (danh mục đặc trưng), including ones that cannot be queried. Use it to answer "does this measure exist" and "why can I not get a number for it". A row here is NOT data — it is a definition. Only features with serving_status = ''servable'' have columns in analytics.fact_customer_features.';

COMMENT ON COLUMN analytics.dim_feature_catalogue.feature_name IS
    'Registered feature name (tên đặc trưng). Matches the column name in fact_customer_features when serving_status is servable.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.domain IS
    'Source domain of the feature: gsm_event, gsm_transaction or vinfast_transaction.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.company IS
    'Operating company the feature belongs to (công ty): GSM or VinFast.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.window_name IS
    'Time window the feature is measured over (khoảng thời gian): daily, l1w, l2w, l1m, l3m, l6m, l12m.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.value_type IS
    'Declared value type of the feature.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.business_approval_status IS
    'Whether the business has signed off on the definition. Engineering review is a separate, already-satisfied gate.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.serving_status IS
    'Whether the feature can be queried for a figure: ''servable'' means it has a column in fact_customer_features; ''catalogue_only'' means it is defined but must not be reported as a number (không được trả số). Check not_servable_reason before answering.';
COMMENT ON COLUMN analytics.dim_feature_catalogue.not_servable_reason IS
    'Why a catalogue_only feature cannot be served (lý do không trả được số). Quote this instead of producing a figure. NULL for servable features.';
"""


def build_sql(registry, months, customers):
    version = registry["contract_version"]
    features = sorted(registry["features"], key=lambda f: f["feature_name"])
    servable = [f for f in features if is_servable(f["feature_name"])]
    withheld = [f for f in features if not is_servable(f["feature_name"])]
    vlit = sql_literal(version)

    parts = [VIEW_HEADER.format(version=vlit)]

    selects = []
    for f in servable:
        name = f["feature_name"]
        selects.append(
            f"    MAX(NULLIF(v.feature_value, '')::INT)\n"
            f"        FILTER (WHERE v.feature_name = {sql_literal(name)}) AS {name}"
        )
    parts.append(",\n".join(selects) + "\n")
    parts.append(VIEW_FOOTER.format(version=vlit))

    parts.append("\nCOMMENT ON VIEW analytics.fact_customer_features IS\n")
    parts.append(
        "    "
        + sql_literal(
            VIEW_COMMENT.format(
                n=len(servable), withheld=len(withheld),
                months=months, customers=customers,
            )
        )
        + ";\n\n"
    )

    parts.append(
        "COMMENT ON COLUMN analytics.fact_customer_features.global_customer_id IS\n"
        "    'Cross-company customer identifier (mã khách hàng toàn hệ thống). "
        "Join key to analytics.dim_customer.';\n"
        "COMMENT ON COLUMN analytics.fact_customer_features.snapshot_month IS\n"
        "    'Snapshot month as YYYY-MM (tháng). Every feature on the row is "
        "measured as of the end of this month.';\n\n"
    )

    for f in servable:
        parts.append(
            f"COMMENT ON COLUMN analytics.fact_customer_features.{f['feature_name']} IS\n"
            f"    {sql_literal(column_comment(f))};\n"
        )

    withheld_list = ",\n".join(
        f"        {sql_literal(f['feature_name'])}" for f in withheld
    )
    parts.append(CATALOGUE_SQL.format(
        withheld_list=withheld_list,
        reason=sql_literal(WITHHELD_REASON),
        version=vlit,
    ))

    parts.append("\nREVOKE ALL ON ALL TABLES IN SCHEMA analytics FROM PUBLIC;\n")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check", action="store_true",
        help="Exit non-zero if the generated SQL differs from what is on disk.")
    parser.add_argument("--months", default="2025-01 to 2025-12")
    parser.add_argument("--customers", default="200")
    args = parser.parse_args()

    if not REGISTRY_PATH.exists():
        raise SystemExit(
            f"Registry not found: {REGISTRY_PATH}\n"
            "Copy it from the BI pipeline's metadata/feature_store/registry/."
        )

    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    sql_text = build_sql(registry, args.months, args.customers)

    if args.check:
        current = OUT_PATH.read_text(encoding="utf-8") if OUT_PATH.exists() else ""
        if current != sql_text:
            print(f"{OUT_PATH.name} is out of date — rerun the generator.")
            return 1
        print(f"{OUT_PATH.name} is up to date.")
        return 0

    OUT_PATH.write_text(sql_text, encoding="utf-8", newline="\n")
    features = registry["features"]
    servable = [f for f in features if is_servable(f["feature_name"])]
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)}")
    print(f"  registry {registry['contract_version']}: {len(features)} features")
    print(f"  {len(servable)} servable -> columns in fact_customer_features")
    print(f"  {len(features) - len(servable)} catalogue_only -> "
          f"dim_feature_catalogue, no column")
    return 0


if __name__ == "__main__":
    sys.exit(main())
