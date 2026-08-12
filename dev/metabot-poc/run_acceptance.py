"""Run DEMO_QUESTIONS.md against Metabot and grade the answers.

For each question: send it to /api/metabot/agent-streaming, pull the MBQL that
Metabot built out of the stream, execute that query, and compare the numbers to
the ground truth in EXPECTED_RESULTS.md.

Grading the generated query rather than the prose is deliberate. The prose is
free to phrase a number any way it likes, but the query either aggregates the
right column over the right filter or it does not, and executing it gives an
exact figure to compare. A question that gets a plausible-sounding answer with
no query behind it is reported as NO_QUERY, not as a pass.

Results stream to acceptance_results.json as each question finishes, so a run
can be inspected while it is still going and a crash does not lose the work
already done.

Usage:
    python dev/metabot-poc/run_acceptance.py            # all questions
    python dev/metabot-poc/run_acceptance.py 1 5 12     # only these
"""

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import provision_metabase as P  # noqa: E402  (needs sys.path set first)

RESULTS_PATH = HERE / "acceptance_results.json"
REPORT_PATH = HERE / "ACCEPTANCE_REPORT.md"

# Revenue figures carry cents, so compare with a small absolute tolerance
# instead of exact equality; counts are integers and compare exactly.
MONEY_TOLERANCE = 0.01

# One question drives roughly six to eight LLM round-trips through the tool
# loop, which is enough to exhaust a free-tier quota partway through a run.
# Pace the run and retry rather than reporting a metered refusal as a wrong
# answer. Override with ACCEPTANCE_DELAY / ACCEPTANCE_RETRIES.
QUESTION_DELAY = int(os.getenv("ACCEPTANCE_DELAY", "15"))
RATE_LIMIT_RETRIES = int(os.getenv("ACCEPTANCE_RETRIES", "3"))
RATE_LIMIT_BACKOFF = 30

MONTHS = [f"2025-{m:02d}" for m in range(1, 13)]

Q2_REVENUE = dict(zip(MONTHS, [
    66774708.90, 75483632.93, 64385485.32, 68188872.80, 76862281.36, 82873312.14,
    96239839.78, 64659370.85, 58280960.75, 78767244.38, 74973414.54, 58851928.60,
]))

Q3_REVENUE = {
    "Hải Phòng": 121109777.51, "Bình Dương": 118078617.09, "Đà Nẵng": 112299135.96,
    "Cần Thơ": 110759950.99, "Hà Nội": 109254431.47, "TP Hồ Chí Minh": 106720963.65,
    "Đồng Nai": 98866597.60, "Quảng Ninh": 89251578.08,
}

Q4_REVENUE = {
    "food": 230289239.17, "express": 224218523.54,
    "bike": 212103203.48, "taxi": 199730086.16,
}

Q8_COUNTS = {
    "Hà Nội": 4207, "Quảng Ninh": 4037, "Hải Phòng": 4003, "Đà Nẵng": 4002,
    "Cần Thơ": 3933, "TP Hồ Chí Minh": 3905, "Bình Dương": 3708, "Đồng Nai": 3513,
}

Q11_COUNTS = dict(zip(MONTHS, [
    1670, 1721, 1731, 1699, 1603, 1605, 1592, 1669, 1632, 1664, 1646, 1719,
]))

Q12_COUNTS = {
    "view_product": 3381, "booking_completed": 3370, "support_contact": 3364,
    "search": 3313, "app_open": 3311, "booking_created": 3310,
}

Q13_COUNTS = {
    "Bình Dương": 2851, "Quảng Ninh": 2753, "Đà Nẵng": 2513, "TP Hồ Chí Minh": 2508,
    "Cần Thơ": 2479, "Hải Phòng": 2407, "Hà Nội": 2319, "Đồng Nai": 2121,
}

QUESTIONS = [
    (1, "Doanh thu completed của GSM trong toàn bộ dữ liệu là bao nhiêu?",
     {"kind": "scalar", "value": 866341052.35}),
    (2, "Doanh thu completed của GSM theo tháng trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q2_REVENUE}),
    (3, "Doanh thu completed của GSM theo tỉnh trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q3_REVENUE}),
    (4, "Doanh thu completed của GSM theo sản phẩm trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q4_REVENUE}),
    (5, "Số giao dịch completed của GSM trong toàn bộ dữ liệu là bao nhiêu?",
     {"kind": "scalar", "value": 31308}),
    (6, "Số giao dịch completed của VinFast trong toàn bộ dữ liệu là bao nhiêu?",
     {"kind": "scalar", "value": 377}),
    (7, "So sánh số giao dịch completed của GSM và VinFast theo tháng trong toàn bộ dữ liệu.",
     {"kind": "rowcount", "expected_rows": {12, 24}, "note": "12 months x 2 companies"}),
    (8, "Số giao dịch completed của GSM theo tỉnh trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q8_COUNTS}),
    (9, "Số giao dịch completed của VinFast theo sản phẩm trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": {"service": 128, "accessories": 127, "vehicle": 122}}),
    (10, "Số event của GSM trong toàn bộ dữ liệu là bao nhiêu?",
     {"kind": "scalar", "value": 20049}),
    (11, "Số event của VinFast theo tháng trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q11_COUNTS}),
    (12, "Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q12_COUNTS}),
    (13, "Số event của VinFast theo tỉnh trong toàn bộ dữ liệu.",
     {"kind": "grouped", "expected": Q13_COUNTS}),
]


def ask(question, timeout=420):
    """Send one question and pull the interesting parts out of the SSE stream."""
    body = {
        "message": question,
        "context": {},
        # These belong at the top level of the body, not inside `context` --
        # the endpoint rejects the request without them.
        "history": [],
        "state": {},
        "conversation_id": str(uuid.uuid4()),
    }
    req = urllib.request.Request(
        P.BASE_URL + "/api/metabot/agent-streaming",
        data=json.dumps(body).encode(),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Metabase-Session", P._session_token)

    text, tools, navs, errors = "", [], [], []
    queries, preferred = {}, None

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp:
            line = raw.decode(errors="replace").rstrip()
            if not line:
                continue

            if line.startswith("data: "):
                # Current protocol: SSE frames carrying typed parts.
                try:
                    ev = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                kind = ev.get("type")
                if kind == "text-delta":
                    text += ev.get("delta", "")
                elif kind == "tool-input-available":
                    tools.append(ev.get("toolName"))
                elif kind == "data-state":
                    # Where the built query now lives, in MBQL lib (pMBQL) shape.
                    queries.update((ev.get("data") or {}).get("queries") or {})
                elif kind == "data-generated_entity":
                    # Names which of the queries in state the answer is about.
                    preferred = ((ev.get("data") or {}).get("query") or {}).get("id")
                elif kind == "error":
                    errors.append(json.dumps(ev))
                continue

            # Legacy protocol, kept so older builds still grade: prefixed lines
            # `0:"text"`, `9:{tool}`, `2:{data}`, `3:error`.
            tag, _, payload = line.partition(":")
            try:
                value = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if tag == "0":
                text += value
            elif tag == "9":
                tools.append(value.get("toolName"))
            elif tag == "2" and isinstance(value, dict) and value.get("type") == "navigate_to":
                navs.append(value.get("value"))
            elif tag == "3":
                # The agent loop reports provider failures in-band: the HTTP
                # response is already a 202 by the time the LLM call is made, so
                # a 429 arrives here rather than as an HTTP status.
                errors.append(value if isinstance(value, str) else json.dumps(value))

    query = None
    if queries:
        query = queries.get(preferred) or list(queries.values())[-1]
    elif navs:
        query = decode_query(navs[-1])

    return {"text": text, "tools": tools, "errors": errors, "query": query}


# Some gateways report their own failures as assistant text rather than on the
# stream's error channel, e.g. `[qoder error 504: upstream model timeout]`.
# Left undetected these look exactly like a model that declined to answer, which
# blames Metabot for an upstream outage.
GATEWAY_ERROR_RE = re.compile(r"^\[\w+ error (\d{3})\b")


def gateway_error(outcome):
    match = GATEWAY_ERROR_RE.match(outcome["text"].strip())
    return match.group(0).strip("[") + ": " + outcome["text"].strip()[:160] if match else None


def is_retryable(outcome):
    """Rate limits, upstream queueing, and gateway timeouts are all worth a retry."""
    blob = (" ".join(outcome["errors"]) + " " + outcome["text"][:400]).lower()
    if any(s in blob for s in ("429", "rate limit", "usagelimit")):
        return True
    match = GATEWAY_ERROR_RE.match(outcome["text"].strip())
    return bool(match and match.group(1) in {"403", "429", "500", "502", "503", "504"})


def decode_query(nav_url):
    """The navigate_to link carries the built question as base64 in its fragment."""
    if not nav_url or "#" not in nav_url:
        return None
    fragment = nav_url.split("#", 1)[1]
    try:
        # Padding is stripped from the URL fragment; '==' is always enough.
        decoded = json.loads(base64.b64decode(fragment + "=="))
    except Exception:
        return None
    return decoded.get("dataset_query")


def close_enough(actual, expected):
    if isinstance(expected, float):
        return abs(float(actual) - expected) <= MONEY_TOLERANCE
    return int(actual) == int(expected)


def grade(rows, spec):
    """Compare executed query output to the ground truth. Returns (verdict, detail)."""
    kind = spec["kind"]

    if kind == "scalar":
        if len(rows) != 1 or len(rows[0]) != 1:
            return "WRONG", f"expected a single scalar, got {len(rows)} rows x {len(rows[0]) if rows else 0} cols"
        if close_enough(rows[0][0], spec["value"]):
            return "PASS", f"{rows[0][0]}"
        return "WRONG", f"got {rows[0][0]}, expected {spec['value']}"

    if kind == "rowcount":
        if len(rows) in spec["expected_rows"]:
            return "PASS", f"{len(rows)} rows ({spec['note']})"
        return "WRONG", f"got {len(rows)} rows, expected one of {sorted(spec['expected_rows'])}"

    # grouped: first column is the label, last is the measure.
    expected = spec["expected"]
    if len(rows) != len(expected):
        return "WRONG", f"got {len(rows)} groups, expected {len(expected)}"

    actual = {str(r[0]).strip(): r[-1] for r in rows}
    # Month buckets can come back as full dates; keep only the YYYY-MM prefix.
    if all(k.startswith("2025-") for k in expected):
        actual = {k[:7]: v for k, v in actual.items()}

    missing = [k for k in expected if k not in actual]
    if missing:
        return "WRONG", f"missing groups: {missing[:4]}"

    bad = [
        f"{k}: got {actual[k]}, want {expected[k]}"
        for k in expected
        if not close_enough(actual[k], expected[k])
    ]
    if bad:
        return "WRONG", "; ".join(bad[:3])
    return "PASS", f"{len(rows)} groups all matching"


def run_one(num, question, spec, retries=RATE_LIMIT_RETRIES):
    started = time.time()

    for attempt in range(retries + 1):
        try:
            outcome = ask(question)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {"n": num, "question": question, "verdict": "ERROR",
                    "detail": f"{type(exc).__name__}: {exc}",
                    "seconds": round(time.time() - started, 1)}

        if not is_retryable(outcome) or attempt == retries:
            break
        # Free tiers meter over a window, so back off rather than hammering.
        wait = RATE_LIMIT_BACKOFF * (2 ** attempt)
        reason = gateway_error(outcome) or "rate limited"
        print(f"     {reason[:70]} — retrying in {wait}s "
              f"(attempt {attempt + 1}/{retries})", flush=True)
        time.sleep(wait)

    record = {
        "n": num,
        "question": question,
        "tools": outcome["tools"],
        "answer": outcome["text"],
        "errors": outcome["errors"],
        "query": outcome["query"],
        "seconds": round(time.time() - started, 1),
    }

    upstream = gateway_error(outcome)
    if upstream:
        record["verdict"] = "PROVIDER_ERROR"
        record["detail"] = upstream[:160]
        return record

    if is_retryable(outcome):
        record["verdict"] = "RATE_LIMITED"
        record["detail"] = "provider refused after retries — model quota exhausted"
        return record

    if outcome["errors"]:
        record["verdict"] = "ERROR"
        record["detail"] = outcome["errors"][0][:200]
        return record

    if not outcome["query"]:
        record["verdict"] = "NO_QUERY"
        record["detail"] = "Metabot answered without building a query"
        return record

    try:
        result = P.call("POST", "/dataset", outcome["query"])
        rows = result.get("data", {}).get("rows", [])
    except P.ProvisionError as exc:
        record["verdict"] = "QUERY_FAILED"
        record["detail"] = str(exc)[:300]
        return record

    record["rows"] = rows[:30]
    record["verdict"], record["detail"] = grade(rows, spec)
    return record


def write_report(records):
    verdicts = {}
    for r in records:
        verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1

    lines = [
        "# MetaBot POC — acceptance run",
        "",
        f"Provider: `{P.call('GET', '/session/properties').get('llm-metabot-provider')}`",
        "",
        "Mỗi câu được chấm bằng cách chạy chính MBQL mà MetaBot sinh ra rồi đối chiếu",
        "số với `EXPECTED_RESULTS.md`, không chấm bằng câu chữ.",
        "",
        "| Verdict | Số câu |",
        "| --- | ---: |",
    ]
    for v in ("PASS", "WRONG", "NO_QUERY", "PROVIDER_ERROR", "RATE_LIMITED", "QUERY_FAILED", "ERROR"):
        if v in verdicts:
            lines.append(f"| {v} | {verdicts[v]} |")

    lines += ["", "## Chi tiết", "",
              "| # | Câu hỏi | Verdict | Ghi chú | Giây |",
              "| ---: | --- | --- | --- | ---: |"]
    for r in sorted(records, key=lambda x: x["n"]):
        q = r["question"][:58] + ("..." if len(r["question"]) > 58 else "")
        detail = str(r.get("detail", "")).replace("|", "\\|")[:90]
        lines.append(f"| {r['n']} | {q} | {r['verdict']} | {detail} | {r.get('seconds', '')} |")

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_previous():
    """Keep earlier results so re-running a subset does not discard the rest.

    Reruns are the normal way to work through gateway flakiness, and losing the
    passes from the full run every time would make the report useless.
    """
    if not RESULTS_PATH.exists():
        return {}
    try:
        return {r["n"]: r for r in json.loads(RESULTS_PATH.read_text(encoding="utf-8"))}
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def main():
    wanted = {int(a) for a in sys.argv[1:]} or None
    todo = [q for q in QUESTIONS if wanted is None or q[0] in wanted]

    P.authenticate()
    print(f"Running {len(todo)} question(s)\n", flush=True)

    merged = load_previous()
    records = []
    for num, question, spec in todo:
        print(f"[{num:>2}] {question[:66]}", flush=True)
        record = run_one(num, question, spec)
        records.append(record)
        merged[num] = record
        print(f"     {record['verdict']}: {record.get('detail', '')}  ({record['seconds']}s)\n", flush=True)
        ordered = [merged[k] for k in sorted(merged)]
        RESULTS_PATH.write_text(json.dumps(ordered, ensure_ascii=False, indent=2), encoding="utf-8")

    all_records = [merged[k] for k in sorted(merged)]
    write_report(all_records)

    passed = sum(1 for r in records if r["verdict"] == "PASS")
    overall = sum(1 for r in all_records if r["verdict"] == "PASS")
    print("=" * 60)
    print(f"this run: {passed}/{len(records)} PASS")
    print(f"overall:  {overall}/{len(all_records)} PASS")
    print(f"  {RESULTS_PATH}")
    print(f"  {REPORT_PATH}")
    return 0 if passed == len(records) else 1


if __name__ == "__main__":
    sys.exit(main())
