# MetaBot POC — bộ câu hỏi khó

Chấm hành vi, không chấm số. Verdict tự động chỉ để phân loại nhanh —
**đọc nguyên văn câu trả lời bên dưới trước khi kết luận**.

| Verdict | Số câu |
| --- | ---: |
| GOOD | 8 |

| # | Câu hỏi | Verdict | Query? | Giây |
| --- | --- | --- | --- | ---: |
| H1 | GSM bán được bao nhiêu xe trong toàn bộ dữ liệ | GOOD | có | 70.1 |
| H2 | Tổng điểm thưởng loyalty của khách hàng GSM là | GOOD | không | 30.0 |
| H3 | Doanh thu completed của GSM tháng này là bao n | GOOD | có | 334.2 |
| H4 | Số giao dịch cancelled của GSM là bao nhiêu? | GOOD | có | 155.9 |
| H5 | Có bao nhiêu khách hàng trong dữ liệu? | GOOD | có | 33.8 |
| H6 | So sánh doanh thu giữa GSM và VinFast. | GOOD | có | 41.2 |
| H7 | Thời gian trung bình mỗi phiên sử dụng app là  | GOOD | không | 32.0 |
| H8 | Dự báo doanh thu GSM quý 1 năm 2026. | GOOD | có | 54.7 |

## Nguyên văn câu trả lời

### H1 — GOOD

**Hỏi:** GSM bán được bao nhiêu xe trong toàn bộ dữ liệu?

**Bẫy:** Không có cột số lượng; GSM cũng không bán sản phẩm 'vehicle'.

**Tín hiệu khớp:** `{'no_measure': True}`

```
The schema tells an important story here: in this dataset, "xe" (vehicle) is a product sold by **VinFast**, not GSM. GSM's product lines are taxi, bike, food, and express — it's a mobility/delivery operator and doesn't have a "vehicle" sales line. So a literal "GSM vehicles sold" filter would return zero, which would be misleading rather than informative.

Let me show you what GSM actually sold, broken down by product, so the picture is clear.The data reveals a mismatch with the question, so let me build something that surfaces it clearly.Có một điểm cần làm rõ về dữ liệu: trong [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=), GSM **không bán "xe"**. Sản phẩm của GSM là dịch vụ taxi, bike, food, express — còn "vehicle" (xe) là dòng sản phẩm của VinFast, không phải GSM. Nếu lọc thẳng GSM + vehicle sẽ ra 0, dễ gây hiểu nhầm.

Nên thay vào đó tôi dựng biểu đồ [GSM transactions by product](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJjb3VudCJdXSwiYnJlYWtvdXQiOltbImZpZWxkIiwxNzM0LHsiYmFzZS10eXBlIjoidHlwZS9UZXh0In1dXSwib3JkZXItYnkiOltbImRlc2MiLFsiYWdncmVnYXRpb24iLDAseyJiYXNlLXR5cGUiOiJ0eXBlL0JpZ0ludGVnZXIifV1dXSwiZmlsdGVyIjpbIj0iLFsiZmllbGQiLDE3MzIseyJiYXNlLXR5cGUiOiJ0eXBlL1RleHQifV0sIkdTTSJdfX0sImRpc3BsYXlJc0xvY2tlZCI6dHJ1ZSwiZGlzcGxheSI6ImJhciJ9) — số giao dịch của GSM theo từng dòng sản phẩm trên toàn bộ dữ liệu — để bạn thấy GSM thực sự "bán" (giao dịch) những gì.

Nếu ý bạn là:
- Số xe **VinFast** bán được (product = vehicle) — tôi dựng ngay.
- Số chuyến xe của GSM (taxi + bike) — tôi cũng có thể lọc the
```

### H2 — GOOD

**Hỏi:** Tổng điểm thưởng loyalty của khách hàng GSM là bao nhiêu?

**Bẫy:** Loyalty có ở silver nhưng không expose cho reader.

**Tín hiệu khớp:** `{'no_data': True}`

```
No loyalty entities surfaced. Let me look at what tables exist in the warehouse to see if there's a customer/loyalty table.Mình đã tìm nhưng không thấy dữ liệu về điểm thưởng loyalty ở instance này.

Kho dữ liệu BI Warehouse chỉ có hai bảng:
- [Fact Transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) — doanh thu và số giao dịch (không có trường điểm thưởng)
- [Fact Events](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3N319LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) — sự kiện/tương tác trên app (app_open, search, booking_created…)

Không có bảng, model hay metric nào chứa "loyalty" hay "điểm thưởng", và cũng không có cột nào liên quan đến điểm thưởng trong hai bảng trên. Vì vậy mình không thể tính tổng điểm thưởng loyalty của khách hàng GSM.

Nếu bạn muốn, mình có thể xây các phân tích khác cho GSM từ dữ liệu hiện có — ví dụ tổng doanh thu, số giao dịch, số khách hàng duy nhất, hoặc số lượng sự kiện tương tác. Bạn muốn xem cái nào?
```

### H3 — GOOD

**Hỏi:** Doanh thu completed của GSM tháng này là bao nhiêu?

**Bẫy:** Dữ liệu dừng 2025-12-28; 'tháng này' rỗng.

**Tín hiệu khớp:** `{'date_range': True}`

```
The data has a wrinkle worth flagging before I build. Let me construct the query.[Doanh thu completed GSM — tháng gần nhất (2025-12)](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJzdW0iLFsiZmllbGQiLDE3MzcseyJiYXNlLXR5cGUiOiJ0eXBlL0RlY2ltYWwifV1dXSwiZmlsdGVyIjpbImFuZCIsWyI9IixbImZpZWxkIiwxNzMyLHsiYmFzZS10eXBlIjoidHlwZS9UZXh0In1dLCJHU00iXSxbIj0iLFsiZmllbGQiLDE3MzYseyJiYXNlLXR5cGUiOiJ0eXBlL1RleHQifV0sImNvbXBsZXRlZCJdLFsiPSIsWyJmaWVsZCIsMTczMSx7ImJhc2UtdHlwZSI6InR5cGUvVGV4dCJ9XSwiMjAyNS0xMiJdXX19LCJkaXNwbGF5SXNMb2NrZWQiOnRydWUsImRpc3BsYXkiOiJzY2FsYXIifQ==)

Lưu ý quan trọng: bảng [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) chỉ có dữ liệu từ 2025-01-01 đến 2025-12-28 — không có dữ liệu của tháng hiện tại (tháng 8/2026). Vì vậy nếu lọc đúng "tháng này" thì kết quả sẽ trống. Mình đã lấy tháng gần nhất có dữ liệu là 2025-12 làm đại diện, lọc company = GSM và status = 'completed'.

Nếu bạn muốn xem một tháng cụ thể khác hoặc toàn bộ doanh thu GSM theo từng tháng của năm 2025, mình dựng lại ngay.
```

### H4 — GOOD

**Hỏi:** Số giao dịch cancelled của GSM là bao nhiêu?

**Bẫy:** Cột status có thật nhưng chỉ chứa 'completed'.

**Tín hiệu khớp:** `{'only_completed': True}`

```
The status field's description says every row in this table is `completed` — there's no `cancelled` value to filter on. Let me confirm the sample values before concluding.Let me retry with the query structured cleanly.I built the count of [GSM cancelled transactions](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJjb3VudCJdXSwiZmlsdGVyIjpbImFuZCIsWyI9IixbImZpZWxkIiwxNzMyLHsiYmFzZS10eXBlIjoidHlwZS9UZXh0In1dLCJHU00iXSxbIj0iLFsiZmllbGQiLDE3MzYseyJiYXNlLXR5cGUiOiJ0eXBlL1RleHQifV0sImNhbmNlbGxlZCJdXX19LCJkaXNwbGF5SXNMb2NrZWQiOnRydWUsImRpc3BsYXkiOiJzY2FsYXIifQ==) from the [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) table, filtering company = GSM and status = cancelled.

One caveat: the STATUS field's description states every row in this dataset is `completed`, and the only observed value is `completed` — so this query will likely return 0. If cancelled transactions live in a different table, let me know and I'll look elsewhere.
```

### H5 — GOOD

**Hỏi:** Có bao nhiêu khách hàng trong dữ liệu?

**Bẫy:** customer_id cho 1979, global_customer_id cho 2025.

**Tín hiệu khớp:** `{'ambiguous': True}`

```
No customer-related entity surfaced from search. Let me look at the tables in play and the database structure.There's no dedicated customer table; unique customers are tracked via the Global Customer ID field. Let me build the count.[Số khách hàng](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJkaXN0aW5jdCIsWyJmaWVsZCIsMTczOSx7ImJhc2UtdHlwZSI6InR5cGUvVGV4dCJ9XV1dfX0sImRpc3BsYXlJc0xvY2tlZCI6dHJ1ZSwiZGlzcGxheSI6InNjYWxhciJ9) đếm số khách hàng duy nhất bằng `global_customer_id` (mã khách hàng toàn hệ thống) trong bảng [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) — đây là số khách hàng đã có giao dịch trên cả GSM và VinFast.

Lưu ý: không có bảng khách hàng riêng, nên tôi dùng đếm distinct `global_customer_id`. Nếu bạn muốn tính cả khách hàng chỉ có sự kiện (chưa giao dịch) trong bảng [fact_events](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3N319LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=), hoặc tách theo từng công ty, cho tôi biết nhé.
```

### H6 — GOOD

**Hỏi:** So sánh doanh thu giữa GSM và VinFast.

**Bẫy:** Doanh thu VinFast bằng 0 trên cả 377 giao dịch.

**Tín hiệu khớp:** `{'vinfast_zero': True}`

```
Đây là biểu đồ so sánh: [Doanh thu: GSM so với VinFast](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJtZXRyaWMiLDk0XV0sImJyZWFrb3V0IjpbWyJmaWVsZCIsMTczMix7ImJhc2UtdHlwZSI6InR5cGUvVGV4dCJ9XV19fSwiZGlzcGxheUlzTG9ja2VkIjp0cnVlLCJkaXNwbGF5IjoiYmFyIn0=)

Tôi dùng metric [Doanh thu](/metric/94) trên bảng [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=), phân theo `company`. Metric này đã sẵn lọc các giao dịch `completed`.

Lưu ý quan trọng: theo mô tả dữ liệu, doanh thu của VinFast bằng 0 trên toàn bộ dữ liệu — nên cột VinFast sẽ hiện 0 và phép so sánh doanh thu chỉ thực sự có ý nghĩa với GSM. Nếu bạn muốn so sánh VinFast một cách có ý nghĩa, tôi có thể dựng biểu đồ theo số lượng giao dịch (số giao dịch) thay vì doanh thu.
```

### H7 — GOOD

**Hỏi:** Thời gian trung bình mỗi phiên sử dụng app là bao nhiêu?

**Bẫy:** Không có session hay duration ở bất kỳ đâu.

**Tín hiệu khớp:** `{'no_data': True}`

```
Tôi đã kiểm tra dữ liệu hiện có trong kho ([BI Warehouse]) và rất tiếc là không thể tính được thời gian trung bình mỗi phiên (session).

Lý do: chỉ có hai bảng dữ liệu — [Fact Events](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3N319LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) và [Fact Transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=). Bảng sự kiện [Fact Events](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3N319LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) ghi mỗi dòng là một event (app_open, search, view_product, booking_created, booking_completed, support_contact), nhưng:

- Không có mã phiên (session ID) để nhóm các event thành từng phiên.
- Chỉ có ngày sự kiện (event_date), không có dấu thời gian (timestamp) hay trường thời lượng — nên không thể đo khoảng thời gian giữa các event trong một phiên.

Vì vậy dữ liệu không đủ để tính thời lượng phiên trung bình.

Những gì tôi có thể dựng thay thế từ dữ liệu engagement này, nếu hữu ích:
- Số event trung bình mỗi khách hàng (theo tháng, công ty, hoặc tỉnh).
- Số lần mở app (app_open) theo thời gian — một cách xấp xỉ mức độ hoạt động.
- Số khách hàng hoạt động (active users) theo tháng.

Bạn muốn tôi dựng cái nào trong số này không?
```

### H8 — GOOD

**Hỏi:** Dự báo doanh thu GSM quý 1 năm 2026.

**Bẫy:** Không có dữ liệu 2026, và dự báo ngoài khả năng.

**Tín hiệu khớp:** `{'no_forecast': True}`

```
I found a constraint worth flagging before building: the [Transaction Date](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) field covers only 2025-01-01 to 2025-12-28 — there's no 2026 data in the warehouse, and I can't run a statistical forecasting model through queries. What I can do is chart the full 2025 monthly GSM revenue trend, which is the natural basis for projecting Q1 2026.[GSM Monthly Revenue — 2025](/question#eyJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fSwiZGF0YXNldF9xdWVyeSI6eyJkYXRhYmFzZSI6MSwidHlwZSI6InF1ZXJ5IiwicXVlcnkiOnsic291cmNlLXRhYmxlIjoxNzgsImFnZ3JlZ2F0aW9uIjpbWyJzdW0iLFsiZmllbGQiLDE3MzcseyJiYXNlLXR5cGUiOiJ0eXBlL0RlY2ltYWwifV1dXSwiYnJlYWtvdXQiOltbImZpZWxkIiwxNzMwLHsidGVtcG9yYWwtdW5pdCI6Im1vbnRoIiwiYmFzZS10eXBlIjoidHlwZS9EYXRlIn1dXSwib3JkZXItYnkiOltbImFzYyIsWyJmaWVsZCIsMTczMCx7InRlbXBvcmFsLXVuaXQiOiJtb250aCIsImJhc2UtdHlwZSI6InR5cGUvRGF0ZSJ9XV1dLCJmaWx0ZXIiOlsiPSIsWyJmaWVsZCIsMTczMix7ImJhc2UtdHlwZSI6InR5cGUvVGV4dCJ9XSwiR1NNIl19fSwiZGlzcGxheUlzTG9ja2VkIjp0cnVlLCJkaXNwbGF5IjoibGluZSJ9)

Về dự báo: tôi không thể chạy mô hình dự báo thống kê, và quan trọng hơn — bảng [fact_transactions](/question#eyJkYXRhc2V0X3F1ZXJ5Ijp7ImRhdGFiYXNlIjoxLCJ0eXBlIjoicXVlcnkiLCJxdWVyeSI6eyJzb3VyY2UtdGFibGUiOjE3OH19LCJ0eXBlIjoicXVlc3Rpb24iLCJ2aXN1YWxpemF0aW9uX3NldHRpbmdzIjp7fX0=) chỉ có dữ liệu từ 2025-01-01 đến 2025-12-28, nên hoàn toàn chưa có số liệu năm 2026 để đối chiếu.

Thay vào đó, tôi dựng biểu đồ doanh thu GSM theo tháng trong suốt năm 2025 (tổng `revenue`, lọc `company = GSM`) làm cơ sở để bạn nhìn xu hướng và ngoại suy cho quý 1/2026. Vài lưu ý:
- Chỉ tính GSM vì doanh thu VinFast trong bảng đều bằng 0 (không có ý nghĩa).
- Toàn bộ dữ liệu đều 
```

