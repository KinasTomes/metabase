# MetaBot POC — kết quả mong đợi

Ground truth cho `DEMO_QUESTIONS.md`, tính trực tiếp từ `pipeline/silver/*.csv`
bằng đúng logic của `analytics.fact_transactions` và `analytics.fact_events`.

Đối chiếu chéo: doanh thu GSM theo tháng tính từ Silver trùng khít
`gold.gold_monthly_pnl` (2025-01 = 66.774.708,90 ở cả hai nguồn). View mới ở
grain giao dịch không làm lệch số so với Gold aggregate cũ.

## Lưu ý khi chấm điểm

- **`status` không phân biệt được gì.** 31.685/31.685 giao dịch đều `completed`.
  MetaBot bỏ quên filter `completed` vẫn ra đúng số. Đừng coi các câu này là
  bằng chứng nó hiểu "completed".
- **Doanh thu VinFast luôn bằng 0** trên cả 377 giao dịch. Câu hỏi doanh thu chỉ
  dùng cho GSM; với VinFast chỉ hỏi số giao dịch.
- Đơn vị tiền là VND. Sai lệch làm tròn dưới 0,01 chấp nhận được.

## Tổng hợp

| Câu | Nội dung | Kết quả |
| --- | --- | --- |
| 1 | Doanh thu completed GSM | **866.341.052,35** |
| 5 | Số giao dịch completed GSM | **31.308** |
| 6 | Số giao dịch completed VinFast | **377** |
| 10 | Số event GSM | **20.049** |

## Câu 2 — Doanh thu GSM theo tháng

12 dòng, biểu đồ đường.

| Tháng | Doanh thu | Số GD |
| --- | ---: | ---: |
| 2025-01 | 66.774.708,90 | 2.789 |
| 2025-02 | 75.483.632,93 | 2.740 |
| 2025-03 | 64.385.485,32 | 2.498 |
| 2025-04 | 68.188.872,80 | 2.791 |
| 2025-05 | 76.862.281,36 | 2.648 |
| 2025-06 | 82.873.312,14 | 2.515 |
| 2025-07 | 96.239.839,78 | 2.335 |
| 2025-08 | 64.659.370,85 | 2.338 |
| 2025-09 | 58.280.960,75 | 2.710 |
| 2025-10 | 78.767.244,38 | 2.696 |
| 2025-11 | 74.973.414,54 | 2.555 |
| 2025-12 | 58.851.928,60 | 2.693 |

Tháng cao nhất là 2025-07, thấp nhất là 2025-09.

## Câu 3 và 8 — GSM theo tỉnh

8 tỉnh. Câu 3 hỏi doanh thu, câu 8 hỏi số giao dịch — thứ hạng hai bên **khác
nhau**, đây là chỗ tốt để phát hiện MetaBot trả nhầm measure.

| Tỉnh | Doanh thu (câu 3) | Số GD (câu 8) |
| --- | ---: | ---: |
| Hải Phòng | 121.109.777,51 | 4.003 |
| Bình Dương | 118.078.617,09 | 3.708 |
| Đà Nẵng | 112.299.135,96 | 4.002 |
| Cần Thơ | 110.759.950,99 | 3.933 |
| Hà Nội | 109.254.431,47 | 4.207 |
| TP Hồ Chí Minh | 106.720.963,65 | 3.905 |
| Đồng Nai | 98.866.597,60 | 3.513 |
| Quảng Ninh | 89.251.578,08 | 4.037 |

Doanh thu cao nhất: Hải Phòng. Số giao dịch cao nhất: Hà Nội.

## Câu 4 — Doanh thu GSM theo sản phẩm

4 sản phẩm. GSM không bán `vehicle`, `accessories`, `service`.

| Sản phẩm | Doanh thu | Số GD |
| --- | ---: | ---: |
| food | 230.289.239,17 | 7.797 |
| express | 224.218.523,54 | 7.934 |
| bike | 212.103.203,48 | 7.833 |
| taxi | 199.730.086,16 | 7.744 |

## Câu 7 — GSM và VinFast theo tháng

12 tháng, 2 series. GSM xem bảng câu 2. VinFast dao động 20–47 giao dịch/tháng,
tổng 377. Chênh lệch quy mô khoảng 80 lần nên trục đơn sẽ ép series VinFast sát
đáy — đây là câu kiểm tra MetaBot chọn cách trình bày.

## Câu 9 — Số giao dịch VinFast theo sản phẩm

3 nhóm. VinFast không bán sản phẩm của GSM.

| Sản phẩm | Số GD |
| --- | ---: |
| service | 128 |
| accessories | 127 |
| vehicle | 122 |

## Câu 11 — Số event VinFast theo tháng

12 tháng, tổng 19.951.

| Tháng | Event | Tháng | Event |
| --- | ---: | --- | ---: |
| 2025-01 | 1.670 | 2025-07 | 1.592 |
| 2025-02 | 1.721 | 2025-08 | 1.669 |
| 2025-03 | 1.731 | 2025-09 | 1.632 |
| 2025-04 | 1.699 | 2025-10 | 1.664 |
| 2025-05 | 1.603 | 2025-11 | 1.646 |
| 2025-06 | 1.605 | 2025-12 | 1.719 |

Phân bố gần như phẳng, không có mùa vụ.

## Câu 12 — Số event GSM theo tên sự kiện

6 loại, biểu đồ cột.

| Sự kiện | Số lượng |
| --- | ---: |
| view_product | 3.381 |
| booking_completed | 3.370 |
| support_contact | 3.364 |
| search | 3.313 |
| app_open | 3.311 |
| booking_created | 3.310 |

Chênh lệch giữa cao nhất và thấp nhất chỉ 2%. Đừng chấp nhận câu trả lời diễn
giải đây là khác biệt có ý nghĩa.

## Câu 13 — Số event VinFast theo tỉnh

8 tỉnh, tổng 19.951.

| Tỉnh | Event |
| --- | ---: |
| Bình Dương | 2.851 |
| Quảng Ninh | 2.753 |
| Đà Nẵng | 2.513 |
| TP Hồ Chí Minh | 2.508 |
| Cần Thơ | 2.479 |
| Hải Phòng | 2.407 |
| Hà Nội | 2.319 |
| Đồng Nai | 2.121 |

## Câu 14–16 — bắt buộc join

Ba câu này thêm vào sau khi có `dim_customer` / `dim_global_customer`. Câu 1–13
đều trả lời được từ một bảng duy nhất, nên **không câu nào chứng minh MetaBot
join được** — mục tiêu chính của Sprint 2. Ở đây cột dùng để nhóm chỉ tồn tại
trong dimension, nên join là bắt buộc chứ không phải tuỳ chọn.

### 14 — Doanh thu GSM theo VIP / không VIP

`fact_transactions` ⋈ `dim_global_customer` trên `global_customer_id` (FK đã khai).

| is_vip | Doanh thu |
| --- | ---: |
| true | **81.523.640,19** |
| false | **784.817.412,16** |

Tổng hai nhóm = 866.341.052,35, đúng bằng câu 1 — nếu lệch thì join đã fan-out.

### 15 — Doanh thu GSM từ khách dùng cả hai công ty

`fact_transactions` ⋈ `dim_global_customer`, lọc `has_gsm AND has_vinfast`.

**601.336.757,89** (1.400/2.600 khách dùng cả hai).

### 16 — Doanh thu GSM theo giới tính

`fact_transactions` ⋈ `dim_customer` trên **cả** `customer_id` và `pnl`.

| Giới tính | Doanh thu |
| --- | ---: |
| other | **302.013.474,46** |
| female | **291.061.399,00** |
| male | **273.266.178,89** |

Đây là câu bẫy nặng nhất: `dim_customer` có grain `(customer_id, pnl)` và
`customer_id` lặp giữa hai PnL, nên **join thiếu `pnl` sẽ nhân đôi mọi con số**.
Tổng ba nhóm phải bằng 866.341.052,35.

## Vài sự thật của dữ liệu, dễ hiểu nhầm

Phát hiện trong lúc soạn câu 14–16, ghi lại để khỏi dựng nhầm câu hỏi:

- **Tập VIP trùng khít tập feature store** — đúng 200 người, không hơn không kém.
  Nên "doanh thu từ khách VIP" và "doanh thu từ khách có trong feature store" là
  **cùng một con số**. Feature store được xây trên đúng nhóm VIP.
- **Toàn bộ 200 khách feature store đều có VinFast**, nên không có nhóm nào để so
  bên trong feature store theo `has_vinfast` hay `is_vip`.
- **Tỉnh giao dịch luôn bằng tỉnh cư trú của khách.** Nhóm doanh thu theo
  `dim_customer.province` ra y hệt câu 3. Câu hỏi kiểu này *không* kiểm được join,
  vì bỏ join vẫn ra đúng số.

## Cách tái tạo

Sau khi warehouse chạy, chạy lại bằng SQL để xác nhận view khớp bảng trên:

```sql
SELECT transaction_month, SUM(revenue), COUNT(*)
FROM analytics.fact_transactions
WHERE company = 'GSM' AND status = 'completed'
GROUP BY transaction_month ORDER BY transaction_month;
```
