# MetaBot POC — các hướng tiếp theo

Ghi lại tại thời điểm POC đạt definition of done, để sau này quay lại không phải
dựng lại bối cảnh.

## Trạng thái khi ghi

- Warehouse Postgres với `analytics.fact_transactions` (31.685 dòng) và
  `analytics.fact_events` (40.000 dòng), mọi view/cột đều có `COMMENT ON`.
- Metabase build từ source (EE, **không có license**), kết nối bằng
  `metabase_reader` chỉ đọc schema `analytics`.
- Collection `BI Analytics` với 3 metric: Doanh thu, Số giao dịch, Số event.
- Acceptance suite 13 câu, chấm bằng cách chạy MBQL do MetaBot sinh ra.
- Lượt chạy sạch gần nhất: **12/13**, model `qd/qmodel_38max` qua gateway local.

Phase 1 và 2 của walkthrough đã xong. Phase 4 (tool/API ngoài) đã thống nhất là
chưa cần.

## Hướng 1 — Phase 3 bằng cách fork (đang làm)

Không có `:ai-controls` nên `metabot-chat-system-prompt`,
`metabot-nlq-system-prompt`, `metabot-sql-system-prompt`, `metabot-name`,
`metabot-icon` đều bị khoá. Đường vòng duy nhất là sửa thẳng
`src/metabase/metabot/` rồi tự build image.

Đây là hướng học được nhiều nhất về kiến trúc MetaBot, và là phần duy nhất còn
lại đụng vào source Metabase thật. Xem `PLAN_PHASE3_FORK.md`.

## Hướng 2 — Truy vụ Q11 loop

Câu 11 ("Số event của VinFast theo tháng") thỉnh thoảng gọi
`construct_notebook_query` bốn lần liên tiếp rồi bỏ cuộc, không sinh query, không
có lỗi nào trong stream. Không phải lỗi gateway.

Cần xem query bị reject vì lý do gì — nhiều khả năng lộ ra vấn đề ở schema
validation hoặc ở skill `construct-notebook-query-core`. Điểm bắt đầu:

- `src/metabase/metabot/tools/construct.clj`
- `debug/capture-stream` trong `src/metabase/metabot/self/claude.clj` và
  `openai.clj` (chỉ bật ở dev)
- `src/metabase/metabot/skills.clj`

Giá trị: đây là lỗi thật, có thể ảnh hưởng cả người dùng upstream.

## Hướng 3 — Đo flakiness cho tử tế

Hiện chỉ có một lượt chạy mỗi cấu hình, không đủ để kết luận gì về tỉ lệ pass.
Cụ thể **chưa** chứng minh được metric có cải thiện độ chính xác hay không:
chênh lệch 8/13 → 12/13 phần lớn do gateway ổn định hơn, vì cả 5 câu hỏng ở lượt
đầu đều là `403 isQueued` / `504 timeout`.

Cần chạy suite 3–5 lượt ở cả hai cấu hình (có metric / không metric) rồi thống kê
tỉ lệ pass từng câu. Tốn thời gian máy, không tốn công người.

Harness đã hỗ trợ sẵn: `ACCEPTANCE_DELAY`, `ACCEPTANCE_RETRIES`, và kết quả gộp
theo số câu qua nhiều lượt.

## Hướng 4 — Dùng thật trên UI

Suite mới chỉ chấm con số. Chưa ai kiểm tra chart render ra sao, streaming có mượt
không, tiếng Việt hiển thị đúng chưa, hay MetaBot gợi ý gì khi hỏi mơ hồ.

Cần cho demo. Mở `http://localhost:3000`, đăng nhập bằng thông tin trong
`dev/metabot-poc/.env`, chat thử bằng `DEMO_QUESTIONS.md`.

## Việc nhỏ còn nợ

- `local-context/integration/scripts__setup_metabase.py` chưa dùng tới; nếu muốn
  dashboard thì lấy lại phần `dashboard_card_specs` từ đó.
- Chưa có Model nào, chỉ có Metric. Chưa rõ Model có giúp gì thêm không.
- `METABOT_CUSTOMIZATION_WALKTHROUGH.md` vẫn ghi Phase 1/2 là việc phải làm; nên
  cập nhật lại thành đã xong.
