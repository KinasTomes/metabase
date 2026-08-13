"""Check that every number in the narration came from the findings.

The whole nightly design rests on one rule -- the LLM does not do arithmetic --
and this is what makes that rule enforceable rather than a line in a prompt.
Sprint 2 measured the alternative: a warning written into a column description
saying "do not use this flag to filter by company" did not stop the model doing
exactly that, and the two affected answers came back with the same wrong figures
as before the warning existed.

So the narration is treated as untrusted text. Every numeric token in it must be
traceable to `findings.json`, either directly or through one of a small set of
derivations declared here in advance. Anything else and the prose does not ship;
`publish.py` sends the findings table on its own instead.

WHAT COUNTS AS TRACEABLE
------------------------
- a value, baseline, z-score or row count from any finding, within a rounding
  tolerance
- the percentage change between a finding's value and its baseline, which is
  the one piece of arithmetic a summary genuinely needs
- the difference between them, and the value expressed in millions, since VND
  figures read better that way
- the number of findings, and the year and month being reported on
- the `context` block: series the scan publishes precisely because a summary
  needs to say they did not move

Deliberately not included: sums across findings, ratios between findings, or
anything involving a figure the scan did not produce. If a summary needs those,
the scan should compute them and label them, not the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# 1.234,5 (Vietnamese) and 1,234.5 (English) both appear in practice -- the
# gateway models do not reliably honour a locale instruction -- so both are
# parsed and compared numerically. Percent signs are handled by the caller.
NUMBER_RE = re.compile(r"-?\d[\d.,]*")

REL_TOLERANCE = 0.015   # 1.5%: covers one-decimal rounding on any magnitude
ABS_TOLERANCE = 0.51    # and integers rounded to the nearest whole unit


def parse_number(token):
    """'1.234,5' -> 1234.5, '1,234.5' -> 1234.5, '45' -> 45.0. None if unclear."""
    t = token.strip().rstrip(".,")
    if not t or not any(c.isdigit() for c in t):
        return None

    has_dot, has_comma = "." in t, "," in t
    if has_dot and has_comma:
        # Whichever separator comes last is the decimal point.
        dec = "," if t.rfind(",") > t.rfind(".") else "."
        grp = "." if dec == "," else ","
        t = t.replace(grp, "").replace(dec, ".")
    elif has_comma:
        # A lone comma is a decimal separator only when it is not grouping
        # three digits: 2,677 is two thousand; 117,0 is a hundred and seventeen.
        tail = t.rsplit(",", 1)[1]
        t = t.replace(",", "" if len(tail) == 3 else ".")
    elif has_dot:
        tail = t.rsplit(".", 1)[1]
        if len(tail) == 3:
            t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def close(a, b):
    if a == b:
        return True
    return abs(a - b) <= max(ABS_TOLERANCE, REL_TOLERANCE * max(abs(a), abs(b)))


def allowed_values(report):
    """Every figure the narration is permitted to contain, with its provenance."""
    allowed = {}

    def add(value, source):
        if value is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        allowed.setdefault(round(v, 6), source)

    findings = report.get("findings", [])
    add(len(findings), "số lượng phát hiện")
    add(len(report.get("suppressed", [])), "số mục bị loại")

    as_of = report.get("as_of", "")
    if re.match(r"\d{4}-\d{2}", as_of):
        year, month = as_of.split("-")
        add(int(year), "năm kỳ báo cáo")
        add(int(month), "tháng kỳ báo cáo")

    for f in findings + report.get("context", []):
        tag = f"{f.get('metric')}/{f.get('dimension') or 'overall'}"
        value, base = f.get("value"), f.get("baseline_median")
        add(value, f"{tag}: giá trị")
        add(base, f"{tag}: mức nền")
        add(f.get("z"), f"{tag}: z")
        add(f.get("n"), f"{tag}: số dòng")

        if value is not None:
            add(value / 1e6, f"{tag}: giá trị (triệu)")
            add(value / 1e9, f"{tag}: giá trị (tỉ)")
        # Anything the scan itself wrote is by definition traceable, including
        # figures inside free text: the new-category note carries "chiếm 5,0%",
        # the trend note "xu hướng 7 tháng", and a feature dimension is spelled
        # `..._l3m`. Quoting those back is exactly the behaviour wanted, so
        # rejecting them made the gate punish obedience.
        for text_field in (f.get("note"), f.get("title"), f.get("dimension")):
            for tok in NUMBER_RE.findall(text_field or ""):
                add(parse_number(tok), f"{tag}: trích từ ghi chú của bản quét")

        if value is not None and base:
            change = (value - base) / abs(base)
            add(change * 100, f"{tag}: % thay đổi")
            add(abs(change) * 100, f"{tag}: % thay đổi (trị tuyệt đối)")
            add(value - base, f"{tag}: chênh lệch tuyệt đối")
            add(abs(value - base), f"{tag}: chênh lệch tuyệt đối")
            add(base / 1e6, f"{tag}: mức nền (triệu)")
    return allowed


@dataclass
class Result:
    verified: bool
    checked: int = 0
    unmatched: list = field(default_factory=list)
    matched: list = field(default_factory=list)

    def report(self):
        if self.verified:
            return f"{self.checked} số, tất cả đối chiếu được."
        bad = ", ".join(f"{t!r}" for t, _ in self.unmatched)
        return (f"{self.checked} số, {len(self.unmatched)} không đối chiếu được: {bad}")


def check(text, report):
    """Verify prose against a scan report."""
    allowed = allowed_values(report)
    result = Result(verified=True)

    for match in NUMBER_RE.finditer(text or ""):
        token = match.group(0)
        value = parse_number(token)
        if value is None:
            continue
        # Dates and ordinals inside a month label are not claims about data.
        window = text[max(0, match.start() - 6):match.end() + 6]
        if re.search(r"\d{4}-\d{2}", window):
            continue

        result.checked += 1
        hit = next((src for v, src in allowed.items() if close(v, value)), None)
        if hit:
            result.matched.append((token, hit))
        else:
            result.verified = False
            result.unmatched.append((token, value))

    return result
