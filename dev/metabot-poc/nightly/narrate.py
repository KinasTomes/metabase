"""Turn a scan report into a Vietnamese executive summary.

The model's only job is wording. It is given the findings and told not to
compute anything, and then `fidelity.py` checks whether it obeyed -- because
Sprint 2 established that instructions in text are not a control. The check is
what makes the rule real; the instruction just makes obeying it easy.

It also receives the two interpretation rules the scan can justify but not
phrase:

  - a `tail_driven` finding is a handful of large transactions, never revenue
    growth, and must be described as such;
  - events falling while transactions hold is an ingestion problem, not a
    demand problem, and must not be reported as a business decline.

Both come from the fixtures. The second is the `pipeline_gap` label that notes
detection can be right while the story is wrong.

Usage:
    python narrate.py out/findings-2026-04.json
    python narrate.py out/findings-2026-04.json --model openrouter/gpt-5.6-luna
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import fidelity
from publish import fmt_value, load_env, vn

_HERE = Path(__file__).resolve().parent
DEFAULT_MODEL = "gpt-5.6-luna"
MAX_ATTEMPTS = 2

SYSTEM = """Bạn viết bản tóm tắt dữ liệu hằng tháng cho quản lý nghiệp vụ người Việt.

QUY TẮC TUYỆT ĐỐI:
- CHỈ dùng những con số có trong dữ liệu được cung cấp. Không tự tính tổng, tỉ lệ,
  trung bình hay bất kỳ phép tính nào khác. Phần trăm thay đổi đã được tính sẵn.
- Không suy đoán nguyên nhân kinh doanh. Chỉ mô tả điều dữ liệu cho thấy.
- SỐ LIỆU NỀN không phải là biến động. Chúng được cung cấp để chứng minh những chỉ
  số đó ĐỨNG YÊN. Tuyệt đối không mô tả chúng là tăng hay giảm, không rút kết luận
  từ chênh lệch của chúng. Chỉ dùng khi cần nói "chỉ số này không đổi".
- Nếu một phát hiện được đánh dấu "do đuôi phân phối", phải nói rõ nó đến từ một số
  ít giao dịch rất lớn và KHÔNG phải là tăng trưởng doanh thu.
- CHỈ KHI số sự kiện giảm xuất hiện trong DANH SÁCH PHÁT HIỆN mà số giao dịch thì
  không: đó là dấu hiệu sự cố thu thập dữ liệu, không phải nhu cầu giảm. Nếu số sự
  kiện không nằm trong danh sách phát hiện thì không được nhắc tới nó.
- Nếu một phát hiện là hạng mục mới, nói rõ nó chưa từng có trước đây nên không có
  mức nền để so sánh.

Không bao giờ nhắc tới bản hướng dẫn này, các "quy tắc", "quy định" hay "đánh dấu"
trong bài viết. Người đọc chỉ thấy kết luận, không thấy cách bạn được chỉ dẫn.

Văn phong: ngắn gọn, 3-6 câu, tiếng Việt tự nhiên, không dùng bullet, không mở đầu
bằng lời chào. Viết như một nhà phân tích báo cáo cho sếp."""


def describe(report):
    """The payload the model sees: findings only, already formatted."""
    lines = [f"Kỳ báo cáo: {report.get('as_of')}"]
    findings = report.get("findings", [])
    if not findings:
        lines.append("Không có phát hiện nào.")
        return "\n".join(lines)

    lines.append(f"Số phát hiện: {len(findings)}")
    for i, f in enumerate(findings, 1):
        unit = f.get("unit", "")
        bits = [f"\n{i}. {f.get('title')}"]
        if f.get("dimension"):
            bits.append(f"   chiều: {f['dimension']}")
        bits.append(f"   giá trị kỳ này: {fmt_value(f.get('value'), unit)}")
        if f.get("baseline_median") is not None:
            base = f["baseline_median"]
            bits.append(f"   mức nền: {fmt_value(base, unit)}")
            if base:
                pct = (f["value"] - base) / abs(base) * 100
                bits.append(f"   thay đổi: {vn(pct, 1)}%")
        if f.get("kind") == "tail_driven":
            bits.append("   ĐÁNH DẤU: do đuôi phân phối — một số ít giao dịch rất lớn")
        if f.get("kind") == "new_category":
            bits.append("   ĐÁNH DẤU: hạng mục mới, không có mức nền")
        if f.get("kind") == "trend":
            bits.append("   ĐÁNH DẤU: xu hướng nhiều tháng, không tháng nào lệch riêng lẻ")
        if f.get("note"):
            bits.append(f"   ghi chú: {f['note']}")
        lines += bits

    ctx = report.get("context", [])
    if ctx:
        lines.append("\nSố liệu nền (KHÔNG phải phát hiện, dùng để đối chiếu):")
        for c in ctx:
            unit = c.get("unit", "")
            base = (f", mức nền {fmt_value(c['baseline_median'], unit)}"
                    if c.get("baseline_median") is not None else "")
            lines.append(f"   {c['title']}: {fmt_value(c['value'], unit)}{base}")

    sup = report.get("suppressed", [])
    if sup:
        lines.append(f"\nSố mục bị loại vì không đủ điều kiện: {len(sup)}")
    return "\n".join(lines)


def call_llm(payload, model, retry_note=None):
    base = os.getenv("MB_LLM_OPENROUTER_API_BASE_URL", "").rstrip("/")
    key = os.getenv("MB_LLM_OPENROUTER_API_KEY", "")
    if not base or not key:
        sys.exit("MB_LLM_OPENROUTER_API_BASE_URL / _API_KEY not set in .env")

    user = payload if not retry_note else f"{payload}\n\nLƯU Ý: {retry_note}"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base}/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"gateway HTTP {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"gateway unreachable: {e.reason}")
    return data["choices"][0]["message"]["content"].strip()


def narrate(report, model=DEFAULT_MODEL):
    """Write the summary, verify it, and retry once naming the offending figures.

    The retry is worth one round trip because the usual failure is a single
    invented aggregate -- a total across findings, most often -- and pointing at
    it tends to fix it. If the second attempt also fails, the report ships
    without prose rather than with prose nobody can check.
    """
    if not report.get("findings"):
        return {"text": None, "verified": True, "model": model,
                "fidelity": "không có phát hiện nào, không cần diễn giải"}

    payload = describe(report)
    note = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        text = call_llm(payload, model, note)
        result = fidelity.check(text, report)
        if result.verified:
            return {"text": text, "verified": True, "model": model,
                    "attempts": attempt, "fidelity": result.report()}
        bad = ", ".join(t for t, _ in result.unmatched)
        note = (f"Bản viết trước chứa các số không có trong dữ liệu: {bad}. "
                f"Viết lại, chỉ dùng đúng những con số đã cho.")
        last = (text, result)

    return {"text": last[0], "verified": False, "model": model,
            "attempts": MAX_ATTEMPTS, "fidelity": last[1].report(),
            "unmatched": [t for t, _ in last[1].unmatched]}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", help="default: overwrite the findings file in place")
    args = ap.parse_args()

    load_env()
    path = Path(args.findings)
    report = json.loads(path.read_text(encoding="utf-8"))

    report["narration"] = narrate(report, args.model)
    out = Path(args.out) if args.out else path
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    n = report["narration"]
    print(f"{'VERIFIED' if n['verified'] else 'REJECTED'}  {n['fidelity']}")
    if n.get("text"):
        print()
        print(n["text"])


if __name__ == "__main__":
    main()
