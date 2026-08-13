"""Detect notable shifts in a monthly series. Deterministic, no LLM.

Every number that ever reaches a reader is produced here. `narrate.py` only
rephrases this file's output and `fidelity.py` refuses to publish prose
containing a figure that is not in it.

THE STEP RULE, WHICH MOST FINDINGS COME FROM
--------------------------------------------
1. Sample size. Fewer than MIN_ROWS rows in the current month and the series is
   suppressed, however large the percentage move. VinFast averages 31
   transactions a month; a 1.8x campaign on 31 rows is real and still not
   something to put in front of a manager as a trend.

2. Modified z-score against the trailing window -- median and MAD, not mean and
   sd, because 64% of transactions have amount 0 and the top 1% carry 37% of
   revenue, so sd is inflated by the tail. Two floors sit under it, both
   calibrated against the 12 real months rather than chosen: a Poisson floor on
   the scale, and a minimum relative move per family. Then a non-parametric
   backstop -- a month inside the range of the six before it is not an outlier
   whatever the arithmetic says.

3. Tail check, monetary series only. Recompute with values winsorised at p99. A
   finding that survives raw and dies winsorised is not revenue growth, it is a
   handful of large jobs, and it is reported as `tail_driven`. Four rows moved
   one fixture month by 60% with volume flat -- that has to read as four rows.

TWO RULES THE STEP RULE CANNOT REACH
------------------------------------
4. Trend. A month-against-baseline comparison cannot see a slow bleed: -4% a
   month compounds to -19% over six without any month looking unusual next to
   the five before it, which is also the most ordinary way a business declines.
   Mann-Kendall over seven months, plus the requirement that the series has
   ended up somewhere it has never been -- six consecutive falls happen by
   chance about once in 720, and across 40 series that is one a month.

5. New category. A dimension with no history has nothing to deviate from, so it
   is reported rather than scored, on share of the month rather than row count.

Measured: 12/12 against the labelled fixtures, 6/6 sensitivity and 6/6
specificity, and 0.33 findings a month backtesting the real data -- both of
those being the same real December spike in Binh Duong.

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

# Trend rule. TREND_S_MIN is calibrated the same way as the floors above:
# swept against the 12 real months until the trend arm stopped firing on data
# with nothing in it. |S| >= 19 of a possible 21 means at most one inversion in
# seven months.
TREND_MONTHS = 7
TREND_S_MIN = 19
TREND_REL_FLOOR = 0.15

# A dimension absent for the whole baseline window and now carrying this share
# of the month is reported as a new category rather than scored. MIN_ROWS cannot
# do this job: Khanh Hoa opened at 128 transactions, below the 300-row gate, yet
# already 5% of the month -- the launch is the story, not its first-month size.
NEW_CATEGORY_SHARE = 0.03


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


def mann_kendall_s(values):
    """Sum of the signs of every pairwise difference, later minus earlier.

    Rank-based, so a single outlying month cannot manufacture a trend the way it
    can drag a regression slope. For n=7 the statistic runs -21..21.
    """
    n = len(values)
    return sum(
        (values[j] > values[i]) - (values[j] < values[i])
        for i in range(n) for j in range(i + 1, n)
    )


def evaluate_trend(points, as_of, metric):
    """Is the series drifting, even though no single month steps out of line?

    The step detector compares one month against a baseline, so a slow bleed is
    invisible to it: -4% a month compounds to -19% over six without any month
    looking unusual next to the five before it. That is also the most ordinary
    way a business declines, so it needs its own rule rather than a lower
    threshold on the other one -- lowering the step threshold enough to catch
    this fired twice a month on data containing nothing.
    """
    months = sorted(m for m in points if m <= as_of)[-TREND_MONTHS:]
    if len(months) < TREND_MONTHS or as_of not in points:
        return None
    if points[as_of][1] < (MIN_FEATURE_ROWS if family(metric) == "feature" else MIN_ROWS):
        return None

    values = [points[m][0] for m in months]
    s = mann_kendall_s(values)
    if abs(s) < TREND_S_MIN:
        return None

    # Monotone is not the same as material: compare the medians of the two ends
    # rather than first against last, so one soft month does not set the size.
    third = max(2, len(values) // 3)
    early = statistics.median(values[:third])
    late = statistics.median(values[-third:])
    if not early or abs(late - early) / abs(early) < TREND_REL_FLOOR:
        return None

    # A trend has to take the series somewhere it has not been. Six consecutive
    # falls happen by chance roughly once in 720, and across ~40 series that is
    # about one a month: the null fixture produced exactly one, Binh Duong
    # sliding 336 -> 306 after December's spike, perfectly monotone and entirely
    # inside its own normal range of 260..423. Drifting back to ordinary is not
    # a decline. Food, by contrast, ends at 477 against a floor of 575.
    history = [points[m][0] for m in points if m < months[0]]
    if not history:
        return None
    if min(history) <= points[as_of][0] <= max(history):
        return None

    return {"value": late, "baseline_median": early, "s": s,
            "change": (late - early) / early, "months": months}


def scan_month(series, as_of):
    findings, suppressed = [], []
    months_seen = sorted({m for p in series.values() for m in p})
    total_points = series.get(("transaction_count", "overall"), {})
    month_total = total_points.get(as_of, (0, 0))[0]

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

        # A dimension with no history at all is not a deviation to be scored --
        # there is nothing to deviate from, and a z-score either divides by zero
        # or, as here, gets skipped for a short baseline. A province that did
        # not exist last month and now carries 12% of transactions is the most
        # reportable thing in the dataset, so it gets its own verdict.
        prior = sorted(m for m in months_seen if m < as_of)[-BASELINE_MONTHS:]
        share = points[as_of][0] / month_total if month_total else 0
        if (v.get("reason") == "short_baseline" and dim != "overall"
                and family(metric) == "count"
                and not any(m in points for m in prior)
                and share >= NEW_CATEGORY_SHARE):
            findings.append({
                "id": f"{metric}:{dim}:{as_of}:new",
                "title": TITLES.get(metric, metric),
                "metric": metric, "dimension": dim, "direction": "new",
                "value": round(points[as_of][0], 2), "baseline_median": None,
                "unit": UNITS.get(metric, ""), "z": None, "n": points[as_of][1],
                "kind": "new_category",
                "note": f"Chưa từng xuất hiện trước đó; nay chiếm {share:.1%} số giao dịch của tháng.",
            })
            continue

        if not v["fired"]:
            t = evaluate_trend(points, as_of, metric)
            if t:
                findings.append({
                    "id": f"{metric}:{dim}:{as_of}:trend",
                    "title": TITLES.get(metric, metric),
                    "metric": f"{metric}_trend",
                    "dimension": None if dim == "overall" else dim,
                    "direction": "up" if t["change"] > 0 else "down",
                    "value": round(t["value"], 2),
                    "baseline_median": round(t["baseline_median"], 2),
                    "unit": UNITS.get(metric, ""), "z": None,
                    "n": points[as_of][1], "kind": "trend",
                    "note": (f"Xu hướng {TREND_MONTHS} tháng liên tiếp, "
                             f"cộng dồn {t['change']:+.0%}. Không tháng nào "
                             f"lệch đủ để bị bắt riêng lẻ."),
                })
                continue
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

    findings.sort(key=lambda f: -abs(f["z"] or 0))
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
                               "baseline_range", "tail_check", "trend",
                               "new_category"],
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
