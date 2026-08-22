# MetaBot POC — acceptance run

Provider: `openrouter/gpt-5.6-luna`

Mỗi câu được chấm bằng cách chạy chính MBQL mà MetaBot sinh ra rồi đối chiếu
số với `EXPECTED_RESULTS.md`, không chấm bằng câu chữ.

| Verdict | Số câu |
| --- | ---: |
| PASS | 15 |
| WRONG | 1 |

## Chi tiết

| # | Câu hỏi | Verdict | Ghi chú | Giây |
| ---: | --- | --- | --- | ---: |
| 1 | Doanh thu completed của GSM trong toàn bộ dữ liệu là bao n... | PASS | 866341052.35 | 61.4 |
| 2 | Doanh thu completed của GSM theo tháng trong toàn bộ dữ li... | PASS | 12 groups all matching | 44.6 |
| 3 | Doanh thu completed của GSM theo tỉnh trong toàn bộ dữ liệ... | PASS | 8 groups all matching | 22.5 |
| 4 | Doanh thu completed của GSM theo sản phẩm trong toàn bộ dữ... | PASS | 4 groups all matching | 25.6 |
| 5 | Số giao dịch completed của GSM trong toàn bộ dữ liệu là ba... | PASS | 31308 | 29.0 |
| 6 | Số giao dịch completed của VinFast trong toàn bộ dữ liệu l... | PASS | 377 | 29.6 |
| 7 | So sánh số giao dịch completed của GSM và VinFast theo thá... | PASS | 24 rows (12 months x 2 companies) | 36.4 |
| 8 | Số giao dịch completed của GSM theo tỉnh trong toàn bộ dữ ... | PASS | 8 groups all matching | 34.1 |
| 9 | Số giao dịch completed của VinFast theo sản phẩm trong toà... | PASS | 3 groups all matching | 26.9 |
| 10 | Số event của GSM trong toàn bộ dữ liệu là bao nhiêu? | PASS | PASS | 160.7 |
| 11 | Số event của VinFast theo tháng trong toàn bộ dữ liệu. | PASS | 12 groups all matching | 23.5 |
| 12 | Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu. | PASS | 6 groups all matching | 57.8 |
| 13 | Số event của VinFast theo tỉnh trong toàn bộ dữ liệu. | PASS | 8 groups all matching | 22.9 |
| 14 | Doanh thu completed của GSM theo khách hàng VIP và không V... | PASS | 2 groups all matching | 44.0 |
| 15 | Doanh thu completed của GSM từ những khách hàng dùng cả GS... | PASS | 601336757.89 | 46.3 |
| 16 | Doanh thu completed của GSM theo giới tính khách hàng. | WRONG | got 0 groups, expected 3 | 33.7 |
