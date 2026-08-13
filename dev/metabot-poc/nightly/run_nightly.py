"""Run one nightly cycle: scan, link, narrate, publish.

    scan -> findings.json -> link -> narrate -> fidelity gate -> publish

Ordering is deliberate. Linking runs before narration so the model can see
nothing about it -- the drill-down URL is not a number and not a claim, and
keeping it out of the payload means the fidelity gate has less text to police.
Narration runs before publishing so a rejected summary is caught here rather
than in the channel.

Every step degrades rather than aborting, because a nightly job that dies
silently is worse than one that reports less. A gateway outage costs the prose,
not the report; a Metabase outage costs the links, not the report. Only a
warehouse failure stops the run, and it stops it loudly.

Usage:
    python run_nightly.py                                  # analytics, latest month
    python run_nightly.py --as-of 2025-12
    python run_nightly.py --schema scenario_tet_surge --as-of 2026-02
    python run_nightly.py --loop --at 02:00                # what the container runs
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import link_questions
import narrate
import publish
import scan

_HERE = Path(__file__).resolve().parent
OUT = _HERE / "out"


def one_cycle(schema, as_of, model, sinks, quiet_empty, link=True):
    scan.load_env()
    publish.load_env()

    conn = scan.connect()
    try:
        series = scan.fetch_series(conn.cursor(), schema)
    finally:
        conn.close()
    if not series:
        raise SystemExit(f"no data in schema {schema}")

    month = as_of or scan.latest_month(series)
    report = scan.build_report(series, schema, month)
    print(f"  scan     {len(report['findings'])} finding, "
          f"{len(report['suppressed'])} bị loại")

    if link:
        try:
            result = link_questions.link(report)
            print(f"  link     {result.get('linked', 0)} link"
                  if "linked" in result else f"  link     bỏ qua ({result['skipped']})")
        except Exception as exc:
            print(f"  link     BỎ QUA — {type(exc).__name__}: {exc}")

    try:
        report["narration"] = narrate.narrate(report, model)
        n = report["narration"]
        print(f"  narrate  {'đạt' if n['verified'] else 'BỊ CHẶN'} — {n['fidelity']}")
    except SystemExit as exc:
        # narrate exits on gateway failure; downgrade it to a missing summary.
        report["narration"] = {"text": None, "verified": False,
                               "fidelity": f"không gọi được LLM: {exc}"}
        print(f"  narrate  BỎ QUA — {exc}")

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"findings-{month}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    results = publish.publish(report, sinks, OUT, quiet_empty=quiet_empty)
    for sink, outcome in results.items():
        print(f"  {sink:8s} {outcome}")
    return report


def seconds_until(hhmm):
    hour, minute = (int(p) for p in hhmm.split(":"))
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", default="analytics")
    ap.add_argument("--as-of")
    ap.add_argument("--model", default=narrate.DEFAULT_MODEL)
    ap.add_argument("--sink", nargs="*", default=["file", "slack"],
                    choices=["file", "slack"])
    ap.add_argument("--quiet-empty", action="store_true",
                    help="skip Slack when there is nothing to report")
    ap.add_argument("--no-link", action="store_true")
    ap.add_argument("--loop", action="store_true", help="run daily and keep running")
    ap.add_argument("--at", default="02:00", help="UTC time of day for --loop")
    args = ap.parse_args()

    sinks = set(args.sink)
    if not args.loop:
        one_cycle(args.schema, args.as_of, args.model, sinks,
                  args.quiet_empty, link=not args.no_link)
        return

    print(f"scheduler: chạy hằng ngày lúc {args.at} UTC trên schema {args.schema}",
          flush=True)
    while True:
        wait = seconds_until(args.at)
        print(f"  ngủ {wait / 3600:.1f} giờ tới lần chạy kế tiếp", flush=True)
        time.sleep(wait)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"\n=== {stamp} ===", flush=True)
        try:
            one_cycle(args.schema, args.as_of, args.model, sinks,
                      args.quiet_empty, link=not args.no_link)
        except Exception:
            # One bad night must not end the schedule.
            traceback.print_exc()
        sys.stdout.flush()


if __name__ == "__main__":
    main()
