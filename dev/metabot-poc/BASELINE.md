# Baseline — bộ 13 câu số

Ba lượt chạy trên image build từ HEAD, prompt gốc chưa sửa gì, model
`openai/qd/qmodel_38max` qua gateway local.

Đây là mốc so sánh cho mọi thay đổi sau này. Ghi lại vì một lượt chạy đơn lẻ
không phân biệt được cải thiện thật với việc gateway hôm đó ổn hơn — sai lầm đã
mắc khi thêm metric (8/13 → 12/13 trông như metric có tác dụng, thực ra phần lớn
là gateway).

## Kết quả

| Câu | Lượt 1 | Lượt 2 | Lượt 3 |
| ---: | --- | --- | --- |
| 1 | PASS | PASS | PASS |
| 2 | PASS | PASS | PASS |
| 3 | PASS | PASS | PASS |
| 4 | PASS | PASS | PASS |
| 5 | PASS | PASS | PASS |
| 6 | PASS | PASS | PASS |
| 7 | PASS | **WRONG** | PASS |
| 8 | PASS | PASS | PASS |
| 9 | PASS | **NO_QUERY** | PASS |
| 10 | PASS | PASS | *provider* |
| 11 | PASS | PASS | *provider* |
| 12 | PASS | PASS | *provider* |
| 13 | PASS | PASS | *provider* |
| **Tổng** | **13/13** | **11/13** | **9/13** |

## Con số để so sánh

**33/35 = 94%** trên các lần thực sự đo được.

Bốn câu cuối lượt 3 bị loại khỏi mẫu: gateway trả `403 code 112` kèm
`pricingUrl`, tức hết credit chứ không phải model sai. Đã retry 30s/60s/120s
đều không qua. Đó là lỗi hạ tầng, không phải tín hiệu về chất lượng MetaBot.

## Câu chập chờn

Chỉ **Q7** và **Q9** từng hỏng, mỗi câu một lần trên ba lượt.

- **Q7** (so sánh GSM và VinFast theo tháng) một lần trả về 1 dòng thay vì 24 —
  dựng query tổng thay vì group theo tháng và company.
- **Q9** (giao dịch VinFast theo sản phẩm) một lần không dựng nổi query.

Chín câu còn lại pass 100% số lần đo được. Không câu nào từng ra **sai số** —
mọi thất bại đều là không dựng được query hoặc dựng sai hình dạng, chưa bao giờ
là con số sai lặng lẽ.

## Cách tái tạo

```powershell
python dev\metabot-poc\run_acceptance.py
Copy-Item dev\metabot-poc\acceptance_results.json dev\metabot-poc\baseline-runN.json
```

Harness gộp kết quả theo số câu nên chạy nhiều lượt sẽ đè lên nhau — phải copy
ra file riêng sau mỗi lượt nếu muốn thống kê.

## Giới hạn của mốc này

- Ba lượt là ít. Q7 và Q9 hỏng 1/3 lần, nhưng khoảng tin cậy quanh con số đó rất
  rộng.
- Cả ba lượt cùng một model. Đổi model là baseline vô giá trị.
- Chỉ đo được tính đúng của con số, không đo cách trình bày, độ trễ hay chất
  lượng tiếng Việt. Bộ `HARD_QUESTIONS.md` bù cho phần hành vi.
