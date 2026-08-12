# MetaBot POC — bộ câu hỏi demo

Sử dụng bộ câu hỏi này sau khi đã kết nối Metabase với các view `analytics`
chứa dữ liệu Gold từ project BI cũ. Đây là acceptance suite cho demo thủ công,
không phải holdout benchmark.

## Phạm vi dữ liệu

- Dữ liệu giao dịch và event: `2025-01-01` đến `2025-12-28`.
- Measure giao dịch chỉ tính giao dịch `completed`.
- Dùng cụm **trong toàn bộ dữ liệu** để không phụ thuộc ngày chạy demo.
- Luôn nêu rõ `GSM`, `VinFast`, hoặc cả hai.

## Câu hỏi copy-paste vào MetaBot

### Doanh thu

1. Doanh thu completed của GSM trong toàn bộ dữ liệu là bao nhiêu?
2. Doanh thu completed của GSM theo tháng trong toàn bộ dữ liệu.
3. Doanh thu completed của GSM theo tỉnh trong toàn bộ dữ liệu.
4. Doanh thu completed của GSM theo sản phẩm trong toàn bộ dữ liệu.

### Giao dịch completed

5. Số giao dịch completed của GSM trong toàn bộ dữ liệu là bao nhiêu?
6. Số giao dịch completed của VinFast trong toàn bộ dữ liệu là bao nhiêu?
7. So sánh số giao dịch completed của GSM và VinFast theo tháng trong toàn bộ dữ liệu.
8. Số giao dịch completed của GSM theo tỉnh trong toàn bộ dữ liệu.
9. Số giao dịch completed của VinFast theo sản phẩm trong toàn bộ dữ liệu.

### Event

10. Số event của GSM trong toàn bộ dữ liệu là bao nhiêu?
11. Số event của VinFast theo tháng trong toàn bộ dữ liệu.
12. Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu.
13. Số event của VinFast theo tỉnh trong toàn bộ dữ liệu.

## Kết quả đã từng kiểm tra live ở agent cũ

| Câu hỏi | Kết quả mong đợi |
| --- | --- |
| Doanh thu completed của GSM theo tháng trong toàn bộ dữ liệu. | 12 tháng và biểu đồ đường |
| Số giao dịch completed của VinFast theo sản phẩm trong toàn bộ dữ liệu. | 3 nhóm: `vehicle`, `accessories`, `service` |
| Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu. | 6 loại event và biểu đồ cột |

## Mapping semantic dự kiến

| Nhóm câu hỏi | Measure chính | Dimension có thể dùng |
| --- | --- | --- |
| Doanh thu completed | `Transactions.revenue` | `company`, `product`, `province`, `transactionDate` |
| Giao dịch completed | `Transactions.transactionCount` | `company`, `product`, `province`, `transactionDate` |
| Event | `Events.eventCount` | `eventName`, `province`, `eventDate` |

Khi cấu hình Metabase, chuyển mapping này thành tên, mô tả và metric/model
tương ứng trong semantic layer; MetaBot không dùng trực tiếp Cube member names.

## Không dùng trong demo đầu tiên

- “Số xe bán ra”, “số sản phẩm bán ra”: chưa có measure số lượng unit/vehicle.
- `finished`: chưa có business meaning được duyệt.
- `cancelled`: Cube cũ chưa hỗ trợ.
- Loyalty, điểm thưởng, session duration, daytime và weekday: semantics chưa chốt.
- “Khách hàng” phải nói rõ khách đã đăng ký hay khách có giao dịch completed.
- “Gần nhất”, “tháng này”, “năm nay” có thể trả về 0 vì dữ liệu demo dừng ở năm 2025.
- Không dùng doanh thu VinFast làm demo kết quả kinh doanh: trường `amount` cũ bằng 0 cho toàn bộ 377 giao dịch.
