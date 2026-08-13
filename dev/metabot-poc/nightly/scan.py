"""Detect notable shifts in a monthly series. Deterministic, no LLM.

Every number that ever reaches a reader is produced here. `narrate.py` only
rephrases this file's output and `fidelity.py` refuses to publish prose
containing a figure that is not in it.

THREE GATES, ALL OF WHICH A FINDING MUST PASS
---------------------------------------------
1. Sample size. Fewer than MIN_ROWS rows in the current month and the series is
   suppressed, however large the percentage move. VinFast averages 31
   transactions a month; a 1.8x campaign on 31 rows is real and still not
   something to put in front of a manager as a trend.

2. Modified z-score against the trailing window -- median and MAD, not mean and
   sd. 64% of transactions have amount 0 and the top 1% carry 37% of revenue, so
   sd is inflated by the tail and hides genuine moves behind its own noise.
   Threshold 3.5 is the Iglewicz-Hoaglin cutoff.

3. Tail check, monetary series only. Recompute with values winsorised at p99. A
   finding that survives raw and dies winsorised is not revenue growth, it is a
   handful of large jobs, and it is reported as `tail_driven`. Four rows moved
   one fixture month by 60% with volume flat -- that has to read as four rows.

WHAT THIS VERSION CANNOT SEE
----------------------------
It compares one month against a baseline, so a slow bleed slips through: the
`food_churn` fixture loses 4% a month to -19% cumulative without a single
detectable step. A new category has no baseline at all, so `province_expansion`
divides by zero and is skipped. Both are labelled `expect_detect: false` for
this detector and true for the trend and new-category rules that come next --
the gap is measured, not hidden.

Usage:
    python scan.py --schema analytics --as-of 2025-12
    python scan.py --schema scenario_corporate_whale --as-of 2026-04
    python scan.py --schema analytics --backtest        # every month, for calibration
"""

from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

_HERE = Path(__file__).resolve().parent

# --- gates -----------------------------------------------------------------
MIN_ROWS = 300          # transactions/events in the current month
MIN_FEATURE_ROWS = 100  # non-null feature values in the current month
Z_THRESHOLD = 3.5       # modified z-score (Iglewicz-Hoaglin)
BASELINE_MONTHS = 6
WINSOR_Q = 0.99         # revenue
FEATURE_WINSOR_Q = 0.95 # feature columns, whose tail is heavier still

# Minimum relative move, by metric family. Calibrated against the 12 real
# months, not chosen by taste: with the z-score alone the backtest fired 2.00
# times a month on data containing no signal. A 6-point baseline makes MAD a
# poor scale estimate, and on a near-flat series it collapses -- `app_open`
# moved 4.1% and scored z=-4.43 because its baseline MAD was about 7.
RELATIVE_FLOOR = {"count": 0.15, "revenue": 0.25, "feature": 0.45}


def family(metric):
    if metric.startswith("revenue"):
        return "revenue"
    if metric == "feature_wmean":
        return "feature"
    return "count"

# 8 of the 20 servable feature columns. The other 12 are NON_DISTRIBUTED:
# resampled from a static distribution at each snapshot, so their
# month-over-month deltas are noise by construction and scanning them would
# manufacture findings. Same distribution_status boundary the catalogue uses.
PROFILED_FEATURES = [
    "gsm_transaction_completed_txn_count_l1m",
    "gsm_transaction_completed_txn_count_l3m",
    "gsm_transaction_completed_txn_count_l6m",
    "gsm_transaction_completed_txn_count_l12m",
    "vinfast_transaction_txn_completed_count_l1m",
    "vinfast_transaction_txn_completed_count_l3m",
    "vinfast_transaction_txn_completed_count_l6m",
    "vinfast_transaction_txn_completed_count_l12m",
]


def load_env(path=_HERE.parent / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def connect():
    return psycopg2.connect(
        host=os.getenv("WAREHOUSE_HOST", "localhost"),
        port=int(os.getenv("WAREHOUSE_PORT", "5433")),
        dbname=os.getenv("WAREHOUSE_DB", "bi_warehouse"),
        user=os.getenv("WAREHOUSE_USER", "postgres"),
        password=os.getenv("WAREHOUSE_PASSWORD", "postgres"),
    )


# --------------------------------------------------------------------------
# Series extraction
#
# Each query returns (month, dimension, value, n). One row per month per
# dimension; `n` is the row count backing the value and drives gate 1.
# --------------------------------------------------------------------------

def q_count(schema, group_expr, label):
    dim = group_expr or "'overall'"
    return (label, f"""
        SELECT transaction_month, {dim} AS dim, COUNT(*)::float, COUNT(*)
        FROM {schema}.fact_transactions
        GROUP BY 1, 2
    """)


def q_revenue(schema, winsorised):
    if not winsorised:
        return ("revenue_total", f"""
            SELECT transaction_month, company, SUM(revenue)::float, COUNT(*)
            FROM {schema}.fact_transactions
            GROUP BY 1, 2
        """)
    # Winsorise inside each month: the cap is a property of the month being
    # summarised, not of all history. LEAST() is deliberately avoided -- it
    # returns the cap for a NULL input rather than NULL, which would turn every
    # missing value into a maximum. revenue is NOT NULL here, but the feature
    # query below shares this shape and is 70% NULL.
    return ("revenue_winsorised", f"""
        WITH caps AS (
            SELECT transaction_month AS m, company AS c,
                   PERCENTILE_CONT({WINSOR_Q}) WITHIN GROUP (ORDER BY revenue) AS cap
            FROM {schema}.fact_transactions GROUP BY 1, 2
        )
        SELECT t.transaction_month, t.company,
               SUM(CASE WHEN t.revenue IS NULL THEN NULL
                        WHEN t.revenue > caps.cap THEN caps.cap
                        ELSE t.revenue END)::float,
               COUNT(*)
        FROM {schema}.fact_transactions t
        JOIN caps ON caps.m = t.transaction_month AND caps.c = t.company
        GROUP BY 1, 2
    """)


def q_active_customers(schema):
    return ("active_customers", f"""
        SELECT transaction_month, 'overall',
               COUNT(DISTINCT global_customer_id)::float, COUNT(*)
        FROM {schema}.fact_transactions
        GROUP BY 1, 2
    """)


def q_events(schema, by_name):
    dim = "event_name" if by_name else "'overall'"
    return (f"event_count{'_by_name' if by_name else ''}", f"""
        SELECT event_month, {dim}, COUNT(*)::float, COUNT(*)
        FROM {schema}.fact_events
        GROUP BY 1, 2
    """)


def feature_source(cur, schema):
    """The two schemas hold feature values in different shapes; normalise here.

    `analytics.fact_customer_features` is pivoted to one column per feature,
    because an LLM should not have to spell
    `gsm_transaction_completed_txn_count_l3m` correctly to ask a question. The
    scenario schemas keep the serving table's EAV shape, which is what a scanner
    iterating features programmatically wants. Neither is wrong for its reader,
    so the scanner unpivots the wide one rather than either surface changing --
    adding a long-form view to `analytics` would put a seventh table in front of
    Metabase and move a surface Sprint 2 has already measured.

    Returns a SQL expression yielding (snapshot_month, feature_name, feature_value).
    """
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %(schema)s
          AND table_name = 'fact_customer_features'
          AND column_name = 'feature_name'
        """,
        {"schema": schema},
    )
    if cur.fetchone():
        return f"SELECT snapshot_month, feature_name, feature_value FROM {schema}.fact_customer_features"

    union = "\n            UNION ALL\n            ".join(
        f"SELECT snapshot_month, '{f}' AS feature_name, {f}::numeric AS feature_value "
        f"FROM {schema}.fact_customer_features"
        for f in PROFILED_FEATURES
    )
    return union


def q_features(schema, source):
    names = ", ".join(f"'{f}'" for f in PROFILED_FEATURES)
    return ("feature_wmean", f"""
        WITH src AS (
            {source}
        ), kept AS (
            SELECT * FROM src
            WHERE feature_name IN ({names}) AND feature_value IS NOT NULL
        ), caps AS (
            SELECT snapshot_month AS m, feature_name AS f,
                   PERCENTILE_CONT({FEATURE_WINSOR_Q})
                       WITHIN GROUP (ORDER BY feature_value) AS cap
            FROM kept GROUP BY 1, 2
        )
        SELECT v.snapshot_month, v.feature_name,
               AVG(CASE WHEN v.feature_value > caps.cap THEN caps.cap
                        ELSE v.feature_value END)::float,
               COUNT(v.feature_value)
        FROM kept v
        JOIN caps ON caps.m = v.snapshot_month AND caps.f = v.feature_name
        GROUP BY 1, 2
    """)


def all_queries(schema, feature_src):
    return [
        q_count(schema, None, "transaction_count"),
        q_count(schema, "company", "transaction_count_by_company"),
        q_count(schema, "product", "transaction_count_by_product"),
        q_count(schema, "province", "transaction_count_by_province"),
        q_revenue(schema, False),
        q_revenue(schema, True),
        q_active_customers(schema),
        q_events(schema, False),
        q_events(schema, True),
        q_features(schema, feature_src),
    ]


def fetch_series(cur, schema):
    """-> {(metric, dim): {month: (value, n)}}"""
    series = {}
    for metric, sql in all_queries(schema, feature_source(cur, schema)):
        cur.execute(sql)
        for month, dim, value, n in cur.fetchall():
            series.setdefault((metric, dim), {})[month] = (float(value), int(n))
    return series


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

def modified_z(x, baseline, counting):
    """Robust z-score with a floor under the scale estimate.

    `counting` series get a Poisson floor: a count with mean m carries at least
    sqrt(m) of irreducible variation, so no estimate of its spread may come out
    below that however smooth six consecutive months happened to look. Without
    it the event-name series -- six months inside a 5% band -- scored |z| above
    4 on moves of 4%.

    Returns (z, median), or (None, median) when the series is constant and no
    change can be quantified at all.
    """
    med = statistics.median(baseline)
    mad = statistics.median([abs(v - med) for v in baseline])
    scale = 1.4826 * mad
    if counting:
        scale = max(scale, math.sqrt(max(med, 1.0)))
    if scale == 0:
        return None, med
    return (x - med) / scale, med


MONETARY = {"revenue_total"}


def scan_month(series, as_of):
    findings, suppressed = [], []

    # Pass 1: winsorised revenue verdicts, needed to classify raw revenue.
    wins_fired = {}
    for (metric, dim), points in series.items():
        if metric != "revenue_winsorised":
            continue
        v = evaluate(points, as_of, metric)
        wins_fired[dim] = bool(v and v["fired"])

    for (metric, dim), points in sorted(series.items()):
        if metric == "revenue_winsorised":
            continue  # a supporting statistic, never a finding of its own

        v = evaluate(points, as_of, metric)
        if v is None:
            continue
        if not v["fired"]:
            if v.get("reason"):
                suppressed.append({"metric": metric, "dimension": dim,
                                   "reason": v["reason"]})
            continue

        kind = None
        note = None
        if metric in MONETARY and not wins_fired.get(dim, True):
            kind = "tail_driven"
            note = ("Biến mất sau khi cắt 1% giá trị cao nhất — do một số ít "
                    "giao dịch rất lớn.")

        findings.append({
            "id": f"{metric}:{dim}:{as_of}",
            "title": TITLES.get(metric, metric),
            "metric": metric,
            "dimension": None if dim == "overall" else dim,
            "direction": "up" if v["value"] > v["median"] else "down",
            "value": round(v["value"], 2),
            "baseline_median": round(v["median"], 2),
            "unit": UNITS.get(metric, ""),
            "z": round(v["z"], 2),
            "n": v["n"],
            "kind": kind,
            "note": note,
        })

    findings.sort(key=lambda f: -abs(f["z"]))
    return findings, suppressed


def evaluate(points, as_of, metric):
    """Apply the gates to one series. None when the month is absent entirely."""
    if as_of not in points:
        return None
    value, n = points[as_of]
    fam = family(metric)

    months = sorted(m for m in points if m < as_of)[-BASELINE_MONTHS:]
    if len(months) < BASELINE_MONTHS:
        return {"fired": False, "reason": "short_baseline"}

    if n < (MIN_FEATURE_ROWS if fam == "feature" else MIN_ROWS):
        return {"fired": False, "reason": "sample_size"}

    baseline = [points[m][0] for m in months]
    z, med = modified_z(value, baseline, counting=(fam == "count"))
    if z is None:
        return {"fired": False, "reason": "flat_baseline"}
    if abs(z) < Z_THRESHOLD:
        return {"fired": False, "reason": "below_threshold"}

    if med and abs(value - med) / abs(med) < RELATIVE_FLOOR[fam]:
        return {"fired": False, "reason": "below_relative_floor"}

    # Non-parametric backstop: whatever the arithmetic says, a month sitting
    # inside the range of the six before it is not an outlier. This is what
    # rejects the bike series at +16% -- 698 against a baseline that had already
    # been as high as 736.
    if min(baseline) <= value <= max(baseline):
        return {"fired": False, "reason": "within_baseline_range"}

    return {"fired": True, "value": value, "median": med, "z": z, "n": n}


TITLES = {
    "transaction_count": "Số giao dịch",
    "transaction_count_by_company": "Số giao dịch theo công ty",
    "transaction_count_by_product": "Số giao dịch theo sản phẩm",
    "transaction_count_by_province": "Số giao dịch theo tỉnh",
    "revenue_total": "Doanh thu",
    "active_customers": "Khách hàng hoạt động",
    "event_count": "Số sự kiện",
    "event_count_by_name": "Số sự kiện theo loại",
    "feature_wmean": "Feature store",
}
UNITS = {"revenue_total": "VND"}


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def build_report(series, schema, as_of):
    findings, suppressed = scan_month(series, as_of)
    return {
        "as_of": as_of,
        "schema": schema,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "detector": {"rules": ["sample_size", "modified_z", "relative_floor",
                               "baseline_range", "tail_check"],
                     "z_threshold": Z_THRESHOLD, "min_rows": MIN_ROWS,
                     "baseline_months": BASELINE_MONTHS},
        "narration": None,
        "findings": findings,
        "suppressed": suppressed,
    }


def latest_month(series):
    return max(m for points in series.values() for m in points)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", default="analytics")
    ap.add_argument("--as-of", help="month to summarise, YYYY-MM (default: latest)")
    ap.add_argument("--backtest", action="store_true",
                    help="scan every month with a full baseline and print a table")
    ap.add_argument("--out", help="write findings JSON here")
    args = ap.parse_args()

    load_env()
    conn = connect()
    cur = conn.cursor()
    try:
        series = fetch_series(cur, args.schema)
    finally:
        cur.close()
        conn.close()

    if not series:
        sys.exit(f"no data in schema {args.schema}")

    if args.backtest:
        months = sorted({m for p in series.values() for m in p})
        total = 0
        print(f"{'month':9} {'findings':>9}  detail")
        for m in months[BASELINE_MONTHS:]:
            findings, _ = scan_month(series, m)
            total += len(findings)
            detail = ", ".join(
                f"{f['metric']}/{f['dimension'] or 'overall'} z={f['z']}"
                for f in findings[:3])
            print(f"{m:9} {len(findings):>9}  {detail}")
        n = len(months) - BASELINE_MONTHS
        print(f"\n{total} finding(s) over {n} month(s) "
              f"— {total / n:.2f} per month on {args.schema}")
        return

    as_of = args.as_of or latest_month(series)
    report = build_report(series, args.schema, as_of)
    out = Path(args.out) if args.out else _HERE / "out" / f"findings-{as_of}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"{args.schema} @ {as_of}: {len(report['findings'])} finding(s), "
          f"{len(report['suppressed'])} suppressed -> {out}")
    for f in report["findings"]:
        tag = f" [{f['kind']}]" if f["kind"] else ""
        print(f"  {f['direction']} {f['metric']}/{f['dimension'] or 'overall'} "
              f"z={f['z']} {f['value']:,.0f} vs {f['baseline_median']:,.0f}{tag}")


if __name__ == "__main__":
    main()
