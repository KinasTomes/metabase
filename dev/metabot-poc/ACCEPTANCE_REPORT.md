# MetaBot POC — acceptance run

Provider: `openrouter/gpt-5.6-luna`

Mỗi câu được chấm bằng cách chạy chính MBQL mà MetaBot sinh ra rồi đối chiếu
số với `EXPECTED_RESULTS.md`, không chấm bằng câu chữ.

| Verdict | Số câu |
| --- | ---: |
| PASS | 14 |
| WRONG | 2 |

## Chi tiết

| # | Câu hỏi | Verdict | Ghi chú | Giây |
| ---: | --- | --- | --- | ---: |
| 1 | Doanh thu completed của GSM trong toàn bộ dữ liệu là bao n... | PASS | 866341052.35 | 24.3 |
| 2 | Doanh thu completed của GSM theo tháng trong toàn bộ dữ li... | PASS | 12 groups all matching | 32.0 |
| 3 | Doanh thu completed của GSM theo tỉnh trong toàn bộ dữ liệ... | PASS | 8 groups all matching | 22.2 |
| 4 | Doanh thu completed của GSM theo sản phẩm trong toàn bộ dữ... | PASS | 4 groups all matching | 21.7 |
| 5 | Số giao dịch completed của GSM trong toàn bộ dữ liệu là ba... | PASS | 31308 | 22.7 |
| 6 | Số giao dịch completed của VinFast trong toàn bộ dữ liệu l... | PASS | 377 | 33.1 |
| 7 | So sánh số giao dịch completed của GSM và VinFast theo thá... | PASS | 24 rows (12 months x 2 companies) | 20.2 |
| 8 | Số giao dịch completed của GSM theo tỉnh trong toàn bộ dữ ... | PASS | 8 groups all matching | 24.2 |
| 9 | Số giao dịch completed của VinFast theo sản phẩm trong toà... | PASS | 3 groups all matching | 21.3 |
| 10 | Số event của GSM trong toàn bộ dữ liệu là bao nhiêu? | WRONG | got 33961, expected 20049 | 19.7 |
| 11 | Số event của VinFast theo tháng trong toàn bộ dữ liệu. | PASS | 12 groups all matching | 24.0 |
| 12 | Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu. | WRONG | view_product: got 5678, want 3381; booking_completed: got 5718, want 3370; support_contact | 26.0 |
| 13 | Số event của VinFast theo tỉnh trong toàn bộ dữ liệu. | PASS | 8 groups all matching | 21.5 |
| 14 | Doanh thu completed của GSM theo khách hàng VIP và không V... | PASS | 2 groups all matching | 37.2 |
| 15 | Doanh thu completed của GSM từ những khách hàng dùng cả GS... | PASS | 601336757.89 | 50.1 |
| 16 | Doanh thu completed của GSM theo giới tính khách hàng. | PASS | 3 groups all matching | 93.5 |
