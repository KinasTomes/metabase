# MetaBot POC — acceptance run

Provider: `anthropic/claude-opus-4-8`

Mỗi câu được chấm bằng cách chạy chính MBQL mà MetaBot sinh ra rồi đối chiếu
số với `EXPECTED_RESULTS.md`, không chấm bằng câu chữ.

| Verdict | Số câu |
| --- | ---: |
| PASS | 9 |
| PROVIDER_ERROR | 4 |

## Chi tiết

| # | Câu hỏi | Verdict | Ghi chú | Giây |
| ---: | --- | --- | --- | ---: |
| 1 | Doanh thu completed của GSM trong toàn bộ dữ liệu là bao n... | PASS | 866341052.35 | 52.6 |
| 2 | Doanh thu completed của GSM theo tháng trong toàn bộ dữ li... | PASS | 12 groups all matching | 48.5 |
| 3 | Doanh thu completed của GSM theo tỉnh trong toàn bộ dữ liệ... | PASS | 8 groups all matching | 21.5 |
| 4 | Doanh thu completed của GSM theo sản phẩm trong toàn bộ dữ... | PASS | 4 groups all matching | 22.7 |
| 5 | Số giao dịch completed của GSM trong toàn bộ dữ liệu là ba... | PASS | 31308 | 20.3 |
| 6 | Số giao dịch completed của VinFast trong toàn bộ dữ liệu l... | PASS | 377 | 47.9 |
| 7 | So sánh số giao dịch completed của GSM và VinFast theo thá... | PASS | 24 rows (12 months x 2 companies) | 35.1 |
| 8 | Số giao dịch completed của GSM theo tỉnh trong toàn bộ dữ ... | PASS | 8 groups all matching | 18.4 |
| 9 | Số giao dịch completed của VinFast theo sản phẩm trong toà... | PASS | 3 groups all matching | 33.0 |
| 10 | Số event của GSM trong toàn bộ dữ liệu là bao nhiêu? | PROVIDER_ERROR | qoder error 403: [qoder error 403: {"code":"112","message":"{\"pricingUrl\":\"https://qode | 213.4 |
| 11 | Số event của VinFast theo tháng trong toàn bộ dữ liệu. | PROVIDER_ERROR | qoder error 403: [qoder error 403: {"code":"112","message":"{\"pricingUrl\":\"https://qode | 213.0 |
| 12 | Số event của GSM theo tên sự kiện trong toàn bộ dữ liệu. | PROVIDER_ERROR | qoder error 403: [qoder error 403: {"code":"112","message":"{\"pricingUrl\":\"https://qode | 213.0 |
| 13 | Số event của VinFast theo tỉnh trong toàn bộ dữ liệu. | PROVIDER_ERROR | qoder error 403: [qoder error 403: {"code":"112","message":"{\"pricingUrl\":\"https://qode | 213.5 |
