"""Publish a nightly scan result to the team channel.

Sinks are additive: the file sink always runs so there is a local record even
when Slack is down or unconfigured, and Slack runs on top when a webhook is set.

TWO THINGS THIS REFUSES TO DO
-----------------------------
1. Publish unverified narration. `narrate.py` produces prose from findings.json
   and `fidelity.py` checks that every number in that prose came from the
   findings. If the check did not pass, this sends the findings table on its own
   rather than the story -- a report with no narrative is worth more than a
   fluent one carrying a number nobody can trace. Sprint 2 measured what happens
   without a gate: a warning written into a column description did not stop the
   model repeating the wrong figure.

2. Go quiet without saying so. On this data the correct nightly outcome is
   almost always "nothing notable", and a job that posts nothing on a quiet
   night is indistinguishable from a job that died. So silence is published as
   one line, including the count of candidates the gates rejected and why. Use
   --quiet-empty to suppress it if the channel gets noisy.

Usage:
    python publish.py findings.json
    python publish.py findings.json --sink file          # no Slack
    python publish.py findings.json --dry-run            # print, send nothing
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
DEFAULT_OUT = _HERE / "out"

# Slack caps a section block's text at 3000 characters and a message at 50
# blocks. Staying well inside both: a summary that needs more than this is a
# dashboard, not a notification.
MAX_BLOCK_CHARS = 2800
MAX_FINDING_BLOCKS = 20

DIRECTION_ICON = {"up": "▲", "down": "▼", "new": "✦"}


def load_env(path=_HERE.parent / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------

def vn(x, decimals=0):
    """Vietnamese number formatting: '.' groups thousands, ',' is the decimal.

    The narration is Vietnamese and writes 117,0. A findings table rendering the
    same figure as 117.0 in the same message reads like two different numbers,
    and the fidelity gate would have to know about both spellings.
    """
    s = f"{x:,.{decimals}f}"
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_value(value, unit=""):
    if not isinstance(value, (int, float)):
        return str(value)
    if unit == "VND":
        return f"{vn(value)} đ"
    if unit == "VND_million":
        return f"{vn(value, 1)} triệu đ"
    if float(value).is_integer():
        return vn(value)
    return vn(value, 2)


def fmt_finding(f, flavour="slack"):
    icon = DIRECTION_ICON.get(f.get("direction"), "•")
    title = f.get("title") or f.get("metric")
    head = f"{icon} **{title}**" if flavour == "markdown" else f"{icon} *{title}*"
    if f.get("dimension"):
        head += f"  ·  {f['dimension']}"

    unit = f.get("unit", "")
    line = f"   {fmt_value(f.get('value'), unit)}"
    if f.get("baseline_median") is not None:
        z = f", z={vn(f['z'], 1)}" if f.get("z") is not None else ""
        line += f"  (nền {fmt_value(f['baseline_median'], unit)}{z})"

    parts = [head, line]
    if f.get("kind") == "tail_driven":
        parts.append("   _Do một số ít giao dịch rất lớn — không phải xu hướng doanh thu._")
    if f.get("kind") == "new_category":
        parts.append("   _Hạng mục mới, chưa có nền để so._")
    if f.get("note"):
        parts.append(f"   {f['note']}")
    if f.get("drill_url"):
        url = f["drill_url"]
        parts.append(f"   [Xem chi tiết trong Metabase]({url})" if flavour == "markdown"
                     else f"   <{url}|Xem chi tiết trong Metabase>")
    return "\n".join(parts)


def suppressed_line(suppressed):
    if not suppressed:
        return None
    by_reason = {}
    for s in suppressed:
        by_reason[s.get("reason", "?")] = by_reason.get(s.get("reason", "?"), 0) + 1
    label = {
        "sample_size": "cỡ mẫu quá nhỏ",
        "below_threshold": "dưới ngưỡng",
        "non_distributed": "cột heuristic",
        "tail_only": "chỉ do đuôi",
    }
    bits = [f"{n} {label.get(k, k)}" for k, n in sorted(by_reason.items())]
    return "Đã loại: " + ", ".join(bits) + "."


def render_text(report, flavour="slack"):
    """Render the report. `flavour` picks Slack mrkdwn or real Markdown."""
    as_of = report.get("as_of", "?")
    findings = report.get("findings", [])
    narration = report.get("narration") or {}
    verified = bool(narration.get("verified"))
    b = "**" if flavour == "markdown" else "*"

    lines = [f"{b}Báo cáo dữ liệu — kỳ {as_of}{b}", ""]

    if not findings:
        lines.append("Không có biến động đáng chú ý.")
        sup = suppressed_line(report.get("suppressed"))
        if sup:
            lines.append(sup)
        return "\n".join(lines)

    if narration.get("text"):
        if verified:
            lines += [narration["text"].strip(), ""]
        else:
            lines += [
                ":warning: _Phần diễn giải bị giữ lại: có con số không đối chiếu được "
                "với dữ liệu quét. Dưới đây là số liệu thô._",
                "",
            ]

    lines.append(f"{b}{len(findings)} phát hiện{b}")
    for f in findings[:MAX_FINDING_BLOCKS]:
        lines += ["", fmt_finding(f, flavour)]
    if len(findings) > MAX_FINDING_BLOCKS:
        lines += ["", f"_... và {len(findings) - MAX_FINDING_BLOCKS} phát hiện nữa._"]

    sup = suppressed_line(report.get("suppressed"))
    if sup:
        lines += ["", f"_{sup}_"]
    return "\n".join(lines)


def render_blocks(report):
    text = render_text(report)
    blocks, buf = [], []
    size = 0
    for para in text.split("\n\n"):
        if size + len(para) > MAX_BLOCK_CHARS and buf:
            blocks.append({"type": "section",
                           "text": {"type": "mrkdwn", "text": "\n\n".join(buf)}})
            buf, size = [], 0
        buf.append(para)
        size += len(para) + 2
    if buf:
        blocks.append({"type": "section",
                       "text": {"type": "mrkdwn", "text": "\n\n".join(buf)}})

    src = report.get("schema", "analytics")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    context = f"{src} · {stamp}"
    if src != "analytics":
        context = f":test_tube: DỮ LIỆU THỬ NGHIỆM — {context}"
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": context}]})
    return blocks[:50]


# --------------------------------------------------------------------------
# Sinks
# --------------------------------------------------------------------------

def sink_file(report, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"summary-{report.get('as_of', 'unknown')}"
    md = out_dir / f"{stem}.md"
    md.write_text(render_text(report, flavour="markdown"), encoding="utf-8")
    (out_dir / f"{stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return md


def sink_slack(report, webhook, dry_run=False):
    blocks = render_blocks(report)
    payload = {
        "text": f"Báo cáo dữ liệu — kỳ {report.get('as_of', '?')}",  # notification fallback
        "blocks": blocks,
    }
    if dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return "dry-run"

    req = urllib.request.Request(
        webhook, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return f"{r.status} {r.read().decode().strip()}"
    except urllib.error.HTTPError as e:
        # Never echo the URL: it is the credential.
        raise SystemExit(f"Slack rejected the message: HTTP {e.code} "
                         f"{e.read().decode()[:200]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"Slack unreachable: {e.reason}")


def publish(report, sinks, out_dir, dry_run=False, quiet_empty=False):
    results = {}
    if "file" in sinks:
        results["file"] = str(sink_file(report, out_dir))

    if "slack" in sinks:
        if quiet_empty and not report.get("findings"):
            results["slack"] = "skipped (nothing to report)"
        else:
            webhook = os.getenv("SLACK_WEBHOOK_URL", "").strip()
            if not webhook:
                results["slack"] = "skipped (SLACK_WEBHOOK_URL not set)"
            else:
                results["slack"] = sink_slack(report, webhook, dry_run)
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings", help="path to findings.json produced by scan.py")
    ap.add_argument("--sink", nargs="*", default=["file", "slack"],
                    choices=["file", "slack"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--dry-run", action="store_true",
                    help="render and print the Slack payload without sending")
    ap.add_argument("--quiet-empty", action="store_true",
                    help="do not post to Slack when there is nothing to report")
    args = ap.parse_args()

    load_env()
    path = Path(args.findings)
    if not path.exists():
        sys.exit(f"no such file: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))

    results = publish(report, set(args.sink), Path(args.out),
                      dry_run=args.dry_run, quiet_empty=args.quiet_empty)
    for sink, outcome in results.items():
        print(f"  {sink:6s} {outcome}")


if __name__ == "__main__":
    main()
