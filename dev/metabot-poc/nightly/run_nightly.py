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


LAST_SENT = OUT / ".last-published.json"


def finding_signatures(report):
    """Stable data claims used to decide whether a report is new."""
    fields = ("id", "direction", "value", "baseline_median", "z", "n", "kind")
    return sorted(
        ({key: finding.get(key) for key in fields} for finding in report.get("findings", [])),
        key=lambda finding: finding.get("id") or "",
    )


def already_sent(report):
    """Has this exact set of findings gone out before?

    Nothing new arrives in this warehouse, so an unguarded schedule reports the
    same December spike every night until the channel learns to ignore it -- and
    a channel that ignores the reporter is worse than no reporter. The signature
    contains the measured claims, but not narration or links: rewording and URL
    changes are not news, while a corrected value in the same month is.
    """
    if not report.get("findings"):
        return False
    if not LAST_SENT.exists():
        return False
    try:
        previous = json.loads(LAST_SENT.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if not isinstance(previous, dict):
        return False
    return (
        previous.get("schema") == report.get("schema")
        and previous.get("as_of") == report.get("as_of")
        and previous.get("findings") == finding_signatures(report)
    )


def remember_sent(report):
    LAST_SENT.parent.mkdir(parents=True, exist_ok=True)
    state = json.dumps({
        "schema": report.get("schema"),
        "as_of": report.get("as_of"),
        "findings": finding_signatures(report),
        "sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2)
    temporary = LAST_SENT.with_suffix(".tmp")
    temporary.write_text(state, encoding="utf-8")
    temporary.replace(LAST_SENT)


def one_cycle(schema, as_of, model, sinks, quiet_empty, link=True,
              allow_repeat=False):
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

    # Scheduled runs suppress a report only after a successful Slack delivery.
    # Manual runs pass allow_repeat=True so they remain useful for demos and QA.
    if "slack" in sinks and not allow_repeat and already_sent(report):
        print("  publish  bỏ qua — các phát hiện này đã gửi Slack")
        return report

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

    # Run local output separately so a Slack error cannot hide the file result or
    # terminate the long-lived scheduler. publish.py keeps its fail-fast CLI.
    local_sinks = sinks - {"slack"}
    results = publish.publish(report, local_sinks, OUT, quiet_empty=quiet_empty)
    if "slack" in sinks:
        try:
            results.update(publish.publish(
                report, {"slack"}, OUT, quiet_empty=quiet_empty))
        except SystemExit as exc:
            results["slack"] = f"FAILED — {exc}"

    slack_result = results.get("slack", "")
    if (report.get("findings") and slack_result
            and not slack_result.startswith(("skipped", "FAILED"))):
        remember_sent(report)
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
                  args.quiet_empty, link=not args.no_link, allow_repeat=True)
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
