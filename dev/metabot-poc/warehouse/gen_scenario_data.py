"""Generate labelled scenario datasets for the nightly shift scanner.

WHY THIS EXISTS
---------------
The real dummy warehouse has no trend to find. Monthly transaction counts sit
within +/-8% while revenue swings +/-25%, because 64% of transactions have
amount 0 and the top 1% of rows carry 37% of revenue -- roughly 27 rows a month
decide a third of the total. Every month-over-month move in it is tail noise.

So the scanner cannot be validated against it directly: on real data the only
correct behaviour is silence, which proves the scanner is quiet but not that it
can see. This module supplies the other half -- months with known, labelled
shifts -- so sensitivity and specificity can both be measured.

WHERE IT MUST NOT GO
--------------------
Scenario rows are fabricated. They are not facts, and they never enter the
`analytics` schema. If they did, MetaBot would answer "which month dropped the
most" with an event that never happened -- the same failure as serving the
`cancelled` feature columns, arriving through a different door. Each scenario
loads into its own `scenario_<name>` schema, outside the connection's inclusion
filter, so Metabase cannot see it at all. Only the scanner harness reads them.

HOW SHIFTS ARE CHOSEN
---------------------
From business scenarios, never from the detector's thresholds. Tuning the
injection to the detector would make the test prove itself. Magnitudes span a
range on purpose, and three fixtures MUST NOT fire:

  - `food_churn`    a slow bleed no single month-over-month step can see
  - `vinfast_push`  a real campaign on a sample too small to speak about
  - `null`          six more months of the same distribution

The first of those is the interesting one: it is the most realistic business
risk in this list and the month-over-month detector is blind to it by
construction. That gap is a finding, not an oversight to hide.

BASELINE
--------
Months 2025-01..2025-12 are the real rows, copied through untouched, so MAD
calibration runs against a genuine distribution. Injected months are
2026-01..2026-06, resampled with replacement from the real rows -- which
preserves the amount distribution, product mix and province mix exactly -- and
then perturbed by the scenario's effects.

Usage:
    python gen_scenario_data.py                  # all scenarios
    python gen_scenario_data.py --only tet_surge null
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
_SILVER = _REPO / "local-context" / "data" / "pipeline" / "silver"
_SERVING = _REPO / "local-context" / "data" / "pipeline" / "serving"
OUT_DIR = _HERE / "scenarios"

SEED = 20260813
BASELINE_MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]
INJECTED_MONTHS = [f"2026-{m:02d}" for m in range(1, 7)]

# Tet 2026 falls on 17 February.
TET_DAY = date(2026, 2, 17)


# --------------------------------------------------------------------------
# Loading the real rows
# --------------------------------------------------------------------------

def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_source():
    tx = read_csv(_SILVER / "transactions.csv")
    ev = read_csv(_SILVER / "events.csv")
    fv = read_csv(_SERVING / "feature_values_monthly_v1_0_0.csv")
    return tx, ev, fv


def month_days(month):
    y, m = (int(p) for p in month.split("-"))
    return calendar.monthrange(y, m)[1]


def monthly_counts(rows, date_key):
    c = Counter(r[date_key][:7] for r in rows)
    return [c[m] for m in BASELINE_MONTHS]


# --------------------------------------------------------------------------
# Scenario effects
#
# An effect is a callable (rng, month, rows) -> rows. It runs after the base
# resample for that month, so it sees a realistic month and perturbs it.
# --------------------------------------------------------------------------

def eff_scale_product(product, factor, months):
    """Multiply the row count for one product in the given months."""
    def apply(rng, month, rows):
        if month not in months:
            return rows
        hit = [r for r in rows if r["product"] == product]
        rest = [r for r in rows if r["product"] != product]
        target = int(round(len(hit) * factor))
        if target <= len(hit):
            kept = rng.sample(hit, target)
        else:
            kept = hit + [dict(rng.choice(hit)) for _ in range(target - len(hit))]
        return rest + kept
    return apply


def eff_tet_shape(months):
    """Pull rides forward into the fortnight before Tet, empty the holiday week.

    A monthly total can hide this entirely, which is the point: the shape moves
    far more than the level does.
    """
    def apply(rng, month, rows):
        if month not in months:
            return rows
        out = []
        for r in rows:
            d = date.fromisoformat(r["transaction_date"])
            delta = (d - TET_DAY).days
            if -14 <= delta < 0:
                weight = 1.9 if r["product"] in ("taxi", "express") else 1.2
            elif 0 <= delta <= 6:
                weight = 0.35
            else:
                weight = 1.0
            keep = int(weight)
            if rng.random() < (weight - keep):
                keep += 1
            out.extend(dict(r) for _ in range(keep))
        return out
    return apply


def eff_new_province(name, share_by_month):
    """A province that did not exist starts taking share."""
    def apply(rng, month, rows):
        share = share_by_month.get(month)
        if not share:
            return rows
        n = int(round(len(rows) * share))
        for r in rng.sample(rows, min(n, len(rows))):
            r["province"] = name
        return rows
    return apply


def eff_whale(months, count, lo, hi, product="express"):
    """A corporate account books a handful of very large jobs.

    Revenue jumps, volume does not. Winsorised revenue should be unmoved, which
    is what separates a tail event from a trend.
    """
    def apply(rng, month, rows):
        if month not in months:
            return rows
        pool = [r for r in rows if r["product"] == product] or rows
        whale_cust = "C000042"
        for _ in range(count):
            r = dict(rng.choice(pool))
            r["customer_id"] = whale_cust
            r["global_customer_id"] = "GC000042"
            r["amount"] = f"{rng.uniform(lo, hi):.2f}"
            rows.append(r)
        return rows
    return apply


def eff_event_gap(months, start_day, days, factor):
    """An ingestion incident: events stop arriving, transactions do not."""
    def apply(rng, month, rows):
        if month not in months:
            return rows
        out = []
        for r in rows:
            day = int(r["event_date"][8:10])
            if start_day <= day < start_day + days and rng.random() > factor:
                continue
            out.append(r)
        return out
    return apply


def eff_scale_company(company, factor, months):
    def apply(rng, month, rows):
        if month not in months:
            return rows
        hit = [r for r in rows if r["company"] == company]
        rest = [r for r in rows if r["company"] != company]
        target = int(round(len(hit) * factor))
        if target <= len(hit):
            kept = rng.sample(hit, target) if hit else []
        else:
            kept = hit + [dict(rng.choice(hit)) for _ in range(target - len(hit))]
        return rest + kept
    return apply


def eff_feature_shift(feature, factor, months):
    """Move a feature-store column without touching the facts underneath.

    Nothing in this warehouse propagates a fact-level event into the feature
    store -- feature values are sampled per snapshot, not derived from the
    facts -- so this is the only way to exercise the feature-store arm of the
    scanner at all. See the note in labels.json.
    """
    def apply(rng, month, rows):
        if month not in months:
            return rows
        for r in rows:
            if r["feature_name"] == feature:
                try:
                    r["feature_value"] = str(int(round(float(r["feature_value"]) * factor)))
                except ValueError:
                    pass
        return rows
    return apply


# --------------------------------------------------------------------------
# Scenario definitions
# --------------------------------------------------------------------------

def gradual(base, step, months):
    """Compounding month-on-month multiplier, e.g. -4% a month."""
    return {m: base * (step ** i) for i, m in enumerate(months)}


SCENARIOS = {
    "null": {
        "description": "Six more months drawn from the same distribution. Nothing happens.",
        "tx_effects": [],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [{
            "id": "N1",
            "month": None,
            "metric": "any",
            "expect_detect": False,
            "why": "No effect applied anywhere. Any finding here is a false positive, and "
                   "the count across all six months is the scanner's false-positive rate.",
        }],
    },

    "tet_surge": {
        "description": "Tet 2026 (17 Feb). Rides pull forward into the fortnight before, "
                       "the holiday week empties out.",
        "tx_effects": [
            eff_tet_shape(["2026-02"]),
            eff_scale_product("taxi", 1.28, ["2026-02"]),
        ],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [
            {
                "id": "T1", "month": "2026-02", "metric": "transaction_count",
                "dimension": "product=taxi", "direction": "up", "expect_detect": True,
                "why": "A real seasonal peak, the largest in the Vietnamese calendar.",
            },
            {
                "id": "T2", "month": "2026-02", "metric": "transaction_count",
                "dimension": "overall", "expect_detect": None,
                "why": "Borderline on purpose. The intra-month shape moves far more than "
                       "the monthly total, so a monthly aggregate may miss it. Whichever "
                       "way it lands, it is evidence about the aggregation window, not a "
                       "pass or a fail.",
            },
        ],
    },

    "province_expansion": {
        "description": "Launch in Khanh Hoa. Share ramps 0 -> 5% -> 9% -> 12% over three months.",
        "tx_effects": [
            eff_new_province("Khánh Hòa", {"2026-03": 0.05, "2026-04": 0.09,
                                           "2026-05": 0.12, "2026-06": 0.12}),
        ],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [{
            "id": "P1", "month": "2026-03", "metric": "province_mix",
            "dimension": "province=Khánh Hòa", "direction": "new", "expect_detect": True,
            "why": "A category that did not exist before. Detecting it needs a "
                   "new-category rule, not a z-score -- there is no baseline to compare "
                   "against, so a purely numeric detector will divide by zero or skip it.",
        }],
    },

    "food_churn": {
        "description": "A competitor takes food-delivery share. -4% a month, compounding, "
                       "for six months.",
        "tx_effects": [
            eff_scale_product("food", 0.96, INJECTED_MONTHS[:1]),
            eff_scale_product("food", 0.92, INJECTED_MONTHS[1:2]),
            eff_scale_product("food", 0.885, INJECTED_MONTHS[2:3]),
            eff_scale_product("food", 0.85, INJECTED_MONTHS[3:4]),
            eff_scale_product("food", 0.815, INJECTED_MONTHS[4:5]),
            eff_scale_product("food", 0.78, INJECTED_MONTHS[5:6]),
        ],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [
            {
                "id": "F1", "month": "2026-06", "metric": "transaction_count",
                "dimension": "product=food", "direction": "down", "expect_detect": False,
                "why": "MUST NOT fire on the month-over-month detector. Each step is ~4%, "
                       "far inside the monthly noise band. This is the most realistic "
                       "business risk in the whole set and the step detector cannot see "
                       "it -- the gap is the finding.",
            },
            {
                "id": "F2", "month": "2026-06", "metric": "transaction_count_trend",
                "dimension": "product=food", "direction": "down", "expect_detect": True,
                "why": "A trend test over the trailing six months (Mann-Kendall or a "
                       "slope on the monthly series) should catch a 22% cumulative fall. "
                       "This label is what justifies building one.",
            },
        ],
    },

    "corporate_whale": {
        "description": "A corporate account books four very large express jobs in April.",
        # Sized against the real distribution, not plucked out of the air: p99 is
        # 479,908 and the historical maximum is 8,673,968, so 8-14M is a large but
        # possible corporate job. Four of them add ~44M to a ~72M month.
        "tx_effects": [
            eff_whale(["2026-04"], count=4, lo=8.0e6, hi=14.0e6),
        ],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [
            {
                "id": "W1", "month": "2026-04", "metric": "revenue_total",
                "direction": "up", "expect_detect": True,
                "why": "Four rows move the monthly total by more than half.",
            },
            {
                "id": "W2", "month": "2026-04", "metric": "revenue_winsorised_p99",
                "expect_detect": False,
                "why": "MUST NOT fire once the tail is clipped. The pair W1/W2 is the "
                       "whole test: a finding that survives W1 and dies at W2 has to be "
                       "reported as 'four large jobs', not as revenue growth.",
            },
            {
                "id": "W3", "month": "2026-04", "metric": "transaction_count",
                "expect_detect": False,
                "why": "Volume is untouched. Revenue up with volume flat is the signature "
                       "the narration must carry.",
            },
        ],
    },

    "pipeline_gap": {
        "description": "Event ingestion drops 70% for nine days in May. Transactions unaffected.",
        "tx_effects": [],
        "ev_effects": [
            eff_event_gap(["2026-05"], start_day=8, days=9, factor=0.30),
        ],
        "fv_effects": [],
        "labels": [
            {
                "id": "G1", "month": "2026-05", "metric": "event_count",
                "direction": "down", "expect_detect": True,
                "why": "Roughly -20% on the month.",
            },
            {
                "id": "G2", "month": "2026-05", "metric": "transaction_count",
                "expect_detect": False,
                "why": "MUST NOT fire. Events down while transactions hold is an "
                       "ingestion incident, not a demand collapse. The summary calling "
                       "this a business decline is a content failure even though the "
                       "detection was right.",
            },
        ],
    },

    "vinfast_push": {
        "description": "VinFast runs a vehicle campaign. Volume up 80% -- on 31 rows a month.",
        "tx_effects": [
            eff_scale_company("VinFast", 1.8, ["2026-06"]),
        ],
        "ev_effects": [],
        "fv_effects": [],
        "labels": [{
            "id": "V1", "month": "2026-06", "metric": "transaction_count",
            "dimension": "company=VinFast", "direction": "up", "expect_detect": False,
            "why": "MUST NOT fire. The effect is real and large in percentage terms, but "
                   "VinFast averages 31 transactions a month, so the sample-size gate "
                   "should reject it. Suppressing a true effect is the correct call here "
                   "and the limitation belongs in the runbook, not in a bug list.",
        }],
    },

    "feature_store_shift": {
        "description": "A feature-store column moves without any fact-level cause.",
        "tx_effects": [],
        "ev_effects": [],
        # 1.9x, not the 1.35x tried first. These columns are heavy-tailed integers
        # whose median is 2, so the median cannot move at all; the workable
        # statistic is the p95-winsorised mean, whose real monthly band is already
        # 3.45..5.41 -- a 44% spread. 1.35x lands inside that band and would have
        # tested nothing.
        "fv_effects": [
            eff_feature_shift("gsm_transaction_completed_txn_count_l3m", 1.9,
                              ["2026-04", "2026-05", "2026-06"]),
        ],
        "labels": [{
            "id": "S1", "month": "2026-04",
            "metric": "feature_median:gsm_transaction_completed_txn_count_l3m",
            "direction": "up", "expect_detect": True,
            "why": "Exercises the feature-store arm of the scanner, which no other "
                   "scenario can reach. Feature values in this warehouse are sampled per "
                   "snapshot rather than derived from the facts, so a fact-level event "
                   "cannot propagate into them -- injecting directly is the only way. "
                   "That disconnect is itself worth reporting: today the feature store "
                   "cannot corroborate a fact-level shift.",
        }],
    },
}


# --------------------------------------------------------------------------
# Generation
# --------------------------------------------------------------------------

def resample_month(rng, pool, month, target_n, date_key, month_key=None):
    """Draw `target_n` rows from `pool`, redated into `month`."""
    ndays = month_days(month)
    out = []
    for _ in range(target_n):
        r = dict(rng.choice(pool))
        r[date_key] = f"{month}-{rng.randint(1, ndays):02d}"
        if month_key:
            r[month_key] = month
        out.append(r)
    return out


def wobble(rng, mean, spread, lo, hi):
    """Monthly counts wobble -- but never outside the range the real months show.

    Clamping matters most for VinFast, whose real months run 12..51. An unclamped
    Gaussian drew 58 for one month, and the campaign multiplier on top of it
    produced a 3.4x jump where 1.8x was intended: the fixture would then have
    been testing the draw, not the effect.
    """
    return max(lo, min(hi, int(round(rng.gauss(mean, spread)))))


def build_transactions(rng, source, effects):
    by_company = defaultdict(list)
    for r in source:
        by_company[r["company"]].append(r)

    counts = defaultdict(list)
    for r in source:
        counts[r["company"]].append(r["transaction_date"][:7])
    stats = {}
    for comp, months in counts.items():
        c = Counter(months)
        vals = [c[m] for m in BASELINE_MONTHS]
        mean = sum(vals) / len(vals)
        spread = (max(vals) - min(vals)) / 4.0
        stats[comp] = (mean, spread, min(vals), max(vals))

    rows = []
    for month in INJECTED_MONTHS:
        month_rows = []
        for comp, pool in by_company.items():
            mean, spread, lo, hi = stats[comp]
            n = wobble(rng, mean, spread, lo, hi)
            month_rows.extend(
                resample_month(rng, pool, month, n, "transaction_date", "transaction_month")
            )
        for eff in effects:
            month_rows = eff(rng, month, month_rows)
        rows.extend(month_rows)

    for i, r in enumerate(rows, start=900_000_001):
        r["transaction_id"] = f"TX{i:09d}"
    return rows


def build_events(rng, source, effects):
    counts = Counter(r["event_date"][:7] for r in source)
    vals = [counts[m] for m in BASELINE_MONTHS]
    mean = sum(vals) / len(vals)
    spread = (max(vals) - min(vals)) / 4.0

    rows = []
    for month in INJECTED_MONTHS:
        n = wobble(rng, mean, spread, min(vals), max(vals))
        month_rows = resample_month(rng, source, month, n, "event_date")
        for eff in effects:
            month_rows = eff(rng, month, month_rows)
        rows.extend(month_rows)

    for i, r in enumerate(rows, start=90_000_001):
        r["event_id"] = f"EV{i:09d}"
    return rows


def build_feature_values(rng, source, scenario_name, effects):
    """Resample each feature's empirical 2025 values into the injected months.

    Sampling, not deriving -- matching how the real snapshots were produced, so
    the 2025/2026 boundary shows no artificial step. A derived feature layer
    would sit ~24% above the sampled one (the 4,355 vs 5,419 gap documented in
    ARCHITECTURE.md) and every scenario would open with a false positive at
    2026-01.
    """
    latest = max(r["snapshot_month"] for r in source)
    template = [r for r in source if r["snapshot_month"] == latest]

    by_feature = defaultdict(list)
    for r in source:
        by_feature[r["feature_name"]].append(r["feature_value"])

    snap_hash = hashlib.sha256(f"scenario:{scenario_name}".encode()).hexdigest()

    rows = []
    for month in INJECTED_MONTHS:
        month_rows = []
        for t in template:
            r = dict(t)
            r["snapshot_month"] = month
            r["source_snapshot_hash"] = snap_hash
            pool = by_feature[r["feature_name"]]
            r["feature_value"] = rng.choice(pool)
            month_rows.append(r)
        for eff in effects:
            month_rows = eff(rng, month, month_rows)
        rows.extend(month_rows)
    return rows


def write_csv(path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def summarise(rows, date_key, amount_key=None):
    c = Counter(r[date_key][:7] for r in rows)
    out = {}
    for m in sorted(c):
        entry = {"rows": c[m]}
        if amount_key:
            entry["revenue"] = round(
                sum(float(r[amount_key]) for r in rows if r[date_key][:7] == m), 2
            )
        out[m] = entry
    return out


def generate(name, spec, source, out_root):
    tx_src, ev_src, fv_src = source
    rng = random.Random(f"{SEED}:{name}")

    tx = build_transactions(rng, tx_src, spec["tx_effects"])
    ev = build_events(rng, ev_src, spec["ev_effects"])
    fv = build_feature_values(rng, fv_src, name, spec["fv_effects"])

    out = out_root / name
    write_csv(out / "transactions.csv", tx_src + tx, list(tx_src[0].keys()))
    write_csv(out / "events.csv", ev_src + ev, list(ev_src[0].keys()))
    write_csv(out / "feature_values_monthly.csv", fv_src + fv, list(fv_src[0].keys()))

    labels = {
        "scenario": name,
        "description": spec["description"],
        "seed": SEED,
        "baseline_months": BASELINE_MONTHS,
        "injected_months": INJECTED_MONTHS,
        "baseline_is_real": True,
        "schema": f"scenario_{name}",
        "expectations": spec["labels"],
        "injected_summary": {
            "transactions": summarise(tx, "transaction_date", "amount"),
            "events": summarise(ev, "event_date"),
        },
    }
    (out / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return labels


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="*", help="generate a subset of scenarios")
    ap.add_argument("--out", default=str(OUT_DIR))
    args = ap.parse_args()

    names = args.only or list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        sys.exit(f"unknown scenario(s): {', '.join(unknown)}")

    print("loading real rows ...", flush=True)
    source = load_source()
    tx_src, ev_src, fv_src = source
    print(f"  {len(tx_src):,} transactions  {len(ev_src):,} events  "
          f"{len(fv_src):,} feature values")

    out_root = Path(args.out)
    index = []
    for name in names:
        labels = generate(name, SCENARIOS[name], source, out_root)
        inj = labels["injected_summary"]["transactions"]
        rows = sum(v["rows"] for v in inj.values())
        must = sum(1 for e in labels["expectations"] if e.get("expect_detect") is True)
        must_not = sum(1 for e in labels["expectations"] if e.get("expect_detect") is False)
        print(f"  {name:22s} +{rows:6,d} tx over {len(inj)} months   "
              f"expect {must} hit / {must_not} silent")
        index.append({"scenario": name, "schema": f"scenario_{name}",
                      "description": labels["description"],
                      "expectations": labels["expectations"]})

    (out_root / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {len(names)} scenario(s) to {out_root}")


if __name__ == "__main__":
    main()
