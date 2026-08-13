"""Score the detector against the labelled scenarios.

Sensitivity and specificity are equally weighted here. A detector that fires on
everything scores perfectly on the six labels that must be found and fails all
six that must stay silent, and it would be useless: on real data the correct
output is almost always nothing.

Labels marked `expect_detect: null` are reported but not scored -- they record a
question the fixture was built to answer (does a monthly aggregate see an
intra-month reshuffle?) rather than a requirement.

Usage:
    python check_labels.py
    python check_labels.py --scenario food_churn --verbose
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scan import connect, fetch_series, load_env, scan_month

_HERE = Path(__file__).resolve().parent
SCENARIO_DIR = _HERE.parent / "warehouse" / "scenarios"

# Labels name metrics in business terms; the scanner names them after its
# queries. Kept explicit rather than inferred: a fuzzy match here could quietly
# score a label against the wrong series and report a pass that never happened.
METRIC_MAP = {
    "transaction_count": ["transaction_count", "transaction_count_by_company",
                          "transaction_count_by_product",
                          "transaction_count_by_province"],
    "transaction_count_trend": ["transaction_count_trend"],  # not implemented yet
    "province_mix": ["transaction_count_by_province"],
    "revenue_total": ["revenue_total"],
    "revenue_winsorised_p99": ["revenue_winsorised"],
    "event_count": ["event_count", "event_count_by_name"],
    "any": None,  # matches anything
}


def dim_of(label):
    """'product=taxi' -> 'taxi'. Labels carry the column for readability.

    'overall' is a real value, not the absence of one: a label about total
    volume must not be satisfied by a single province moving. Findings spell it
    as None, so it is translated rather than dropped.
    """
    d = label.get("dimension")
    if not d:
        return None
    if d == "overall":
        return "__overall__"
    return d.split("=", 1)[1] if "=" in d else d


def label_metrics(label):
    metric = label["metric"]
    if metric.startswith("feature_median:") or metric.startswith("feature_mean:"):
        return ["feature_wmean"]
    return METRIC_MAP.get(metric, [metric])


def matches(finding, label):
    wanted = label_metrics(label)
    if wanted is not None and finding["metric"] not in wanted:
        return False
    dim = dim_of(label)
    if dim == "__overall__":
        if finding.get("dimension") is not None:
            return False
    elif dim and finding.get("dimension") != dim:
        return False
    if label["metric"].startswith(("feature_median:", "feature_mean:")):
        want = label["metric"].split(":", 1)[1]
        if finding.get("dimension") != want:
            return False
    return True


def check_scenario(cur, name, verbose=False):
    labels = json.loads((SCENARIO_DIR / name / "labels.json").read_text(encoding="utf-8"))
    series = fetch_series(cur, f"scenario_{name}")
    injected = labels["injected_months"]

    # One scan per injected month; a label is satisfied if its month fires (or,
    # for a "must stay silent" label, if it never fires in any injected month).
    per_month = {m: scan_month(series, m)[0] for m in injected}

    rows = []
    for label in labels["expectations"]:
        expect = label.get("expect_detect")
        month = label.get("month")
        scope = [month] if month else injected

        hits = [f for m in scope if m in per_month
                for f in per_month[m] if matches(f, label)]
        # A silence label must hold across every injected month, not only its own.
        if expect is False and month:
            hits = [f for m in injected for f in per_month[m] if matches(f, label)]

        detected = bool(hits)
        if expect is None:
            verdict = "INFO"
        elif detected == expect:
            verdict = "PASS"
        else:
            verdict = "FAIL"
        rows.append({"scenario": name, "id": label["id"], "metric": label["metric"],
                     "dimension": label.get("dimension"), "expect": expect,
                     "detected": detected, "verdict": verdict,
                     "hits": hits, "why": label["why"]})

    noise = sum(len(f) for f in per_month.values())
    if verbose:
        for m in injected:
            for f in per_month[m]:
                tag = f" [{f['kind']}]" if f.get("kind") else ""
                print(f"      {m} {f['metric']}/{f.get('dimension') or 'overall'} "
                      f"z={f['z']} {f['value']:,.1f} vs {f['baseline_median']:,.1f}{tag}")
    return rows, noise


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", nargs="*")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    load_env()
    conn = connect()
    cur = conn.cursor()

    names = args.scenario or sorted(
        p.name for p in SCENARIO_DIR.iterdir()
        if p.is_dir() and (p / "labels.json").exists())

    all_rows = []
    try:
        for name in names:
            rows, noise = check_scenario(cur, name, args.verbose)
            all_rows += rows
            print(f"\n{name}   ({noise} finding tổng cộng trên 6 tháng tiêm)")
            for r in rows:
                mark = {"PASS": "  ok  ", "FAIL": " FAIL ", "INFO": " info "}[r["verdict"]]
                want = {True: "phải kêu", False: "phải im", None: "không chấm"}[r["expect"]]
                got = "kêu" if r["detected"] else "im"
                dim = f" {r['dimension']}" if r["dimension"] else ""
                print(f"  [{mark}] {r['id']:3s} {r['metric']}{dim:22s} "
                      f"{want:11s} -> {got}")
                if r["verdict"] == "FAIL":
                    print(f"          {r['why']}")
    finally:
        cur.close()
        conn.close()

    scored = [r for r in all_rows if r["expect"] is not None]
    passed = [r for r in scored if r["verdict"] == "PASS"]
    hit = [r for r in scored if r["expect"] is True]
    silent = [r for r in scored if r["expect"] is False]
    print(f"\n{'='*66}")
    print(f"độ nhạy   {sum(1 for r in hit if r['verdict']=='PASS')}/{len(hit)}  "
          f"(nhãn phải phát hiện)")
    print(f"độ đặc hiệu {sum(1 for r in silent if r['verdict']=='PASS')}/{len(silent)}  "
          f"(nhãn phải im lặng)")
    print(f"tổng      {len(passed)}/{len(scored)}")
    return 0 if len(passed) == len(scored) else 1


if __name__ == "__main__":
    sys.exit(main())
