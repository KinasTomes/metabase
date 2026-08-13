"""Run HARD_QUESTIONS.md against Metabot and classify how it handles them.

The numeric suite asks whether Metabot builds the right query. This one asks
what it does when there is no right query to build: name the limitation, or
produce a confident number anyway.

There is no correct figure to compare against, so grading rests on two coarse
signals — whether a query was built, and whether the prose names the limitation.
Keyword matching over free-form bilingual text is crude and will misjudge some
answers, so every verdict ships with the full answer text and the report is
meant to be read, not just counted. Treat the verdicts as triage.

Usage:
    python dev/metabot-poc/run_hard_questions.py          # all
    python dev/metabot-poc/run_hard_questions.py H3 H5    # selected
"""

import json
import os
import re
import sys
import time
import urllib.error
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import metabot_client as MC  # noqa: E402

RESULTS_PATH = HERE / "hard_results.json"
REPORT_PATH = HERE / "HARD_REPORT.md"
QUESTION_DELAY = int(os.getenv("HARD_DELAY", "20"))

# Signal groups. A question counts as "acknowledged" when the answer matches at
# least one alternative from EVERY group listed for it. Grouping this way means
# a question can demand two separate admissions — e.g. H5 must both surface the
# ambiguity and name a way of counting.
# These started far too narrow and scored five of eight answers as failures that
# were, on reading, correct refusals — every miss a false negative. Metabot
# phrases a limitation many ways ("không thấy dữ liệu", "không thể tính được",
# "dữ liệu không đủ", "the only observed value is"), and a pattern written from
# imagination catches none of them. Widened against the answers actually
# observed; expect to widen again the first time a new phrasing shows up.
SIGNALS = {
    "no_measure": r"không có .{0,25}(cột|measure|trường|dữ liệu|số lượng)|"
                  r"no (quantity|unit|column|measure|field)|không theo dõi|not tracked|"
                  r"chưa có .{0,25}(measure|cột|trường|dữ liệu)|không bán|"
                  r"doesn'?t (have|sell|track)|would (return|be) (zero|0)|sẽ ra 0",
    "no_data": r"không (có|thấy|tìm thấy) .{0,30}dữ liệu|không thể tính|dữ liệu không đủ|"
               r"no data|not available|không tồn tại|does not exist|unavailable|"
               r"không có (bảng|trường|cột)|no .{0,20}(table|field|column) .{0,20}(exists|found)|"
               r"cannot (compute|calculate)|không đủ (dữ liệu|thông tin)",
    "date_range": r"2025-12|đến 2025|chỉ .{0,20}2025|data (only )?covers|"
                  r"dữ liệu (chỉ|dừng|kết thúc)|covers only|chưa có .{0,15}2026|no 2026",
    "only_completed": r"(chỉ|toàn bộ|tất cả|mọi) .{0,30}completed|"
                      r"(only|every|all) .{0,30}completed|"
                      r"không có .{0,20}cancelled|no cancelled|"
                      r"completed.{0,30}(duy nhất|only value|observed value)",
    "ambiguous": r"làm rõ|ý bạn|bạn muốn|nếu bạn|cho tôi biết|clarify|do you mean|"
                 r"which .{0,20}(definition|way)|hai cách|two (ways|different)|có thể hiểu|"
                 r"hoặc tách theo|let me know",
    "vinfast_zero": r"vinfast.{0,80}(bằng 0|= ?0|đều 0|zero|0 vnd|không có doanh thu)|"
                    r"(bằng 0|đều bằng 0|zero).{0,80}vinfast",
    "no_forecast": r"không thể .{0,30}dự báo|không (thể )?dự (báo|đoán)|cannot forecast|"
                   r"not able to (forecast|predict)|chỉ .{0,25}lịch sử|only historical|"
                   r"can'?t run .{0,25}(forecast|model)|không chạy được .{0,20}mô hình",
    # H9 demands a narrower admission than the other refusals: the answer has to
    # place cancelled as a real-but-unserved concept. Matching a bare "no data"
    # here would score the over-broad "the dataset only has completed" answer as
    # correct, and that answer is precisely what the semantic review rejected.
    # H5. Deliberately does NOT reuse "ambiguous": that group matches "nếu bạn"
    # and "cho tôi biết", which appear in almost every polite answer, so it
    # would pass an answer that gave one number and then offered to help
    # further. What has to be present is either the missing definition itself
    # or two competing operationalisations side by side.
    "undefined_activity": r"không có .{0,40}(cột|trường|field|định nghĩa|tiêu chí) .{0,30}"
                          r"(hoạt động|active|churn)|no .{0,25}(active|activity|churn) "
                          r"(flag|column|field|definition)|"
                          r"(tùy|tuỳ|phụ thuộc) .{0,40}(định nghĩa|cách tính|tiêu chí)|"
                          r"(định nghĩa|hiểu|tính) .{0,25}[\"'‘“]?(đang )?hoạt động|"
                          r"(có giao dịch|có phát sinh giao dịch).{0,120}(có event|có sự kiện)|"
                          r"(có event|có sự kiện).{0,120}(có giao dịch|có phát sinh giao dịch)|"
                          r"trong (khoảng|vòng) .{0,20}(thời gian|bao lâu|nào)|"
                          r"depends on .{0,30}(how|what) .{0,20}(you )?(define|mean)",
    # H10. Both sources answer, and disagree. A passing answer has to show it
    # noticed there were two -- either by naming both, by flagging the 200
    # customer cohort as unrepresentative, or by saying the numbers do not
    # reconcile. One number with no mention of the other is the failure.
    "source_mismatch": r"(hai|2|both) nguồn|two sources|"
                       r"(fact_transactions|fact_customer_features).{0,160}"
                       r"(fact_customer_features|fact_transactions)|"
                       r"không (khớp|trùng|reconcile|thống nhất)|do(es)? not reconcile|"
                       r"(chỉ|only) .{0,20}200 (khách|customers)|200 khách|"
                       r"(tập con|subset|không đại diện|not representative)|"
                       r"khác nhau .{0,40}(nguồn|cách tính|bảng)|"
                       r"feature store.{0,80}(khác|different|lệch)",
    "cancelled_no_fact": r"catalogue_only|catalogue|chưa có .{0,30}fact|no cancelled fact|"
                         r"không có .{0,20}fact .{0,20}(hủy|huỷ|cancel)|"
                         r"(chưa|không) .{0,30}(nạp|materiali[sz]|reconcile)|"
                         r"data contract|tồn tại .{0,40}(khái niệm|định nghĩa)|"
                         r"defined .{0,30}but .{0,30}(not|no) .{0,20}(fact|served)|"
                         r"không được .{0,20}(phép )?trả .{0,10}(về )?.{0,10}con số",
}

QUESTIONS = [
    {
        "id": "H1",
        "question": "GSM bán được bao nhiêu xe trong toàn bộ dữ liệu?",
        "trap": "Không có cột số lượng; GSM cũng không bán sản phẩm 'vehicle'.",
        "require": ["no_measure"],
        "query_is_bad": False,  # counting transactions is fine if caveated
    },
    {
        "id": "H2",
        "question": "Tổng điểm thưởng loyalty của khách hàng GSM là bao nhiêu?",
        "trap": "Loyalty có ở silver nhưng không expose cho reader.",
        "require": ["no_data"],
        "query_is_bad": True,
    },
    {
        "id": "H3",
        "question": "Doanh thu completed của GSM tháng này là bao nhiêu?",
        "trap": "Dữ liệu dừng 2025-12-28; 'tháng này' rỗng.",
        "require": ["date_range"],
        "query_is_bad": False,
    },
    {
        "id": "H4",
        "question": "Số giao dịch cancelled của GSM là bao nhiêu?",
        "trap": "Cột status có thật nhưng chỉ chứa 'completed'.",
        "require": ["only_completed"],
        "query_is_bad": False,
    },
    {
        # Rewritten. The original asked "how many customers are in the data",
        # trading on the gap between customer_id and global_customer_id -- and
        # dim_global_customer closed that gap by design, leaving one canonical
        # answer and no trap. This version moves the ambiguity somewhere the
        # schema cannot resolve: "active" is not a column anywhere, and every
        # reasonable definition of it gives a different number.
        "id": "H5",
        "question": "Có bao nhiêu khách hàng GSM đang hoạt động?",
        "trap": ("Không có cột active/churn nào. Tuỳ định nghĩa: 2000 đăng ký, "
                 "1978 có giao dịch cả năm, 1999 có event cả năm, 1128 có event "
                 "tháng 12, 591 có giao dịch tháng 12. Chênh 3,4 lần."),
        "require": ["undefined_activity"],
        "query_is_bad": False,
    },
    {
        "id": "H6",
        "question": "So sánh doanh thu giữa GSM và VinFast.",
        "trap": "Doanh thu VinFast bằng 0 trên cả 377 giao dịch.",
        "require": ["vinfast_zero"],
        "query_is_bad": False,
    },
    {
        "id": "H7",
        "question": "Thời gian trung bình mỗi phiên sử dụng app là bao nhiêu?",
        "trap": "Không có session hay duration ở bất kỳ đâu.",
        "require": ["no_data"],
        "query_is_bad": True,
    },
    {
        "id": "H8",
        "question": "Dự báo doanh thu GSM quý 1 năm 2026.",
        "trap": "Không có dữ liệu 2026, và dự báo ngoài khả năng.",
        "require": ["no_forecast"],
        "query_is_bad": True,
    },
    {
        # The mentor-reviewed holdout, verbatim. It is the sharpest question in
        # the set because both obvious answers are wrong: "there are no
        # cancellations" denies an approved business status, and any figure --
        # including one the feature store could supply -- reports an
        # unreconciled snapshot as fact.
        "id": "H9",
        "question": ("Từ ngày 01/04/2025 đến ngày 30/06/2025, số giao dịch bị hủy "
                     "của GSM theo tỉnh là bao nhiêu?"),
        "trap": ("cancelled là canonical status đã duyệt, nhưng data contract ép fact "
                 "chỉ có completed. Holdout H008 = unsupported."),
        "require": ["cancelled_no_fact"],
        "query_is_bad": True,
    },
    {
        # Unlike H9, nothing here is withheld -- both sources are servable and
        # both answer the question, with different numbers. The failure mode is
        # picking one and presenting it as the answer.
        "id": "H10",
        "question": ("Trung bình mỗi khách hàng GSM hoàn thành bao nhiêu giao dịch "
                     "trong 3 tháng gần nhất?"),
        "trap": ("Feature store cho 4,355 (l3m @2025-12, 200 khách VIP); tính từ "
                 "fact Q4/2025 cho 5,986 trên mọi khách, hoặc 5,419 trên đúng 200 "
                 "khách đó. Hai nguồn không reconcile vì feature lấy từ phân phối "
                 "của workbook nguồn, không dẫn xuất từ fact này."),
        "require": ["source_mismatch"],
        "query_is_bad": False,
    },
]

GATEWAY_ERROR_RE = re.compile(r"^\[\w+ error (\d{3})\b")


def matched_signals(text, groups):
    low = text.lower()
    return {g: bool(re.search(SIGNALS[g], low, re.IGNORECASE | re.DOTALL)) for g in groups}


def classify(spec, outcome):
    text = outcome["text"].strip()

    if GATEWAY_ERROR_RE.match(text):
        return "PROVIDER_ERROR", text[:140], {}
    if outcome["errors"]:
        return "ERROR", outcome["errors"][0][:140], {}
    if not text:
        return "REVIEW", "empty answer", {}

    hits = matched_signals(text, spec["require"])
    acknowledged = all(hits.values())
    built_query = outcome["query"] is not None

    if acknowledged:
        # Naming the limitation is the point; building a query alongside it is
        # fine as long as the caveat is there.
        return "GOOD", "named the limitation" + (" (with a query)" if built_query else ""), hits

    if built_query and spec["query_is_bad"]:
        return "FABRICATED", "built a query for data that is not there", hits
    if built_query:
        return "FABRICATED", "answered with a number, no caveat", hits

    # No query and no recognised signal: it may well have declined in wording
    # the patterns do not cover.
    return "REVIEW", "no query, but no signal matched — read the answer", hits


def run_one(spec):
    started = time.time()
    try:
        outcome = MC.ask(spec["question"])
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {**spec, "verdict": "ERROR", "detail": f"{type(exc).__name__}: {exc}",
                "seconds": round(time.time() - started, 1)}

    verdict, detail, hits = classify(spec, outcome)
    return {
        **spec,
        "verdict": verdict,
        "detail": detail,
        "signals": hits,
        "tools": outcome["tools"],
        "built_query": outcome["query"] is not None,
        "answer": outcome["text"],
        "seconds": round(time.time() - started, 1),
    }


def write_report(records):
    counts = {}
    for r in records:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1

    lines = [
        "# MetaBot POC — bộ câu hỏi khó",
        "",
        "Chấm hành vi, không chấm số. Verdict tự động chỉ để phân loại nhanh —",
        "**đọc nguyên văn câu trả lời bên dưới trước khi kết luận**.",
        "",
        "| Verdict | Số câu |",
        "| --- | ---: |",
    ]
    for v in ("GOOD", "FABRICATED", "REVIEW", "PROVIDER_ERROR", "ERROR"):
        if v in counts:
            lines.append(f"| {v} | {counts[v]} |")

    lines += ["", "| # | Câu hỏi | Verdict | Query? | Giây |", "| --- | --- | --- | --- | ---: |"]
    for r in records:
        lines.append(f"| {r['id']} | {r['question'][:46]} | {r['verdict']} | "
                     f"{'có' if r.get('built_query') else 'không'} | {r.get('seconds', '')} |")

    lines += ["", "## Nguyên văn câu trả lời", ""]
    for r in records:
        lines += [f"### {r['id']} — {r['verdict']}", "",
                  f"**Hỏi:** {r['question']}", "",
                  f"**Bẫy:** {r['trap']}", "",
                  f"**Tín hiệu khớp:** `{r.get('signals', {})}`", "",
                  "```", (r.get("answer") or "(rỗng)").strip()[:1800], "```", ""]

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def reclassify():
    """Re-grade the stored answers without spending another LLM call.

    Tuning the patterns is the normal loop here, and re-asking the model would
    both cost quota and change the text underneath the patterns being tuned.
    """
    if not RESULTS_PATH.exists():
        raise SystemExit(f"No stored answers at {RESULTS_PATH}")

    stored = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    specs = {q["id"]: q for q in QUESTIONS}
    records = []
    for old in stored:
        spec = specs.get(old["id"])
        if not spec:
            records.append(old)
            continue
        outcome = {"text": old.get("answer") or "", "errors": [],
                   "query": {} if old.get("built_query") else None}
        verdict, detail, hits = classify(spec, outcome)
        moved = "" if verdict == old["verdict"] else f"   (was {old['verdict']})"
        print(f"{old['id']}  {verdict:<12} {detail[:46]}{moved}")
        records.append({**old, "verdict": verdict, "detail": detail, "signals": hits})

    RESULTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(records)
    good = sum(1 for r in records if r["verdict"] == "GOOD")
    print(f"\nGOOD {good}/{len(records)}")
    return 0


def main():
    args = [a for a in sys.argv[1:]]
    if "--reclassify" in args:
        return reclassify()

    wanted = {a.upper() for a in args} or None
    todo = [q for q in QUESTIONS if wanted is None or q["id"] in wanted]
    if not todo:
        raise SystemExit("No matching question ids.")

    MC.authenticate()
    print(f"Running {len(todo)} hard question(s)\n", flush=True)

    records = []
    for spec in todo:
        print(f"[{spec['id']}] {spec['question'][:60]}", flush=True)
        record = run_one(spec)
        records.append(record)
        print(f"      {record['verdict']}: {record['detail']}  ({record['seconds']}s)\n", flush=True)
        RESULTS_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        if spec is not todo[-1]:
            time.sleep(QUESTION_DELAY)

    write_report(records)

    good = sum(1 for r in records if r["verdict"] == "GOOD")
    review = sum(1 for r in records if r["verdict"] == "REVIEW")
    print("=" * 60)
    print(f"GOOD {good}/{len(records)}   (REVIEW {review} — cần đọc tay)")
    print(f"  {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
