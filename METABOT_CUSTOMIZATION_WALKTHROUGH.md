# MetaBot customization walkthrough

## Mục tiêu

Biến Metabase thành giao diện phân tích dữ liệu có chatbot: người dùng hỏi bằng ngôn ngữ tự nhiên, MetaBot dùng mô hình AI để hiểu câu hỏi, truy vấn các dữ liệu đã được quản trị trong Metabase, rồi trả lời bằng số liệu, bảng hoặc biểu đồ.

Mục tiêu ban đầu là **đọc và phân tích dữ liệu hiện có**. Các action thay đổi dữ liệu hoặc gọi API nghiệp vụ bên ngoài sẽ không được bật mặc định.

## Workspace và phiên bản

- Repository: `D:\Code\metabase`
- Branch làm việc: `master` (một người làm, không tách branch)
- Fork cá nhân: `git@github.com:KinasTomes/metabase.git` (`origin`); upstream là `metabase/metabase`
- Upstream: Metabase `v0.63.1.6` (`21a3686`)
- Local data và tài liệu: `local-context/` (cố ý không được Git theo dõi)

Không dùng image `rouki1210/metabase-custom` làm nền phát triển vì image đó không có commit/source provenance rõ ràng.

## Hiện trạng upstream (đã đối chiếu với code)

MetaBot **không nằm trong enterprise**. Phần lõi là OSS:

- `src/metabase/metabot/` — agent, tools, context, prompts, provider adapters, schema.
- `src/metabase/llm/` — settings và client cho từng provider.
- `enterprise/backend/src/metabase_enterprise/metabot/` chỉ có usage limit và advanced permissions.

### Provider LLM đã hỗ trợ sẵn

`src/metabase/metabot/self/` có adapter cho: `claude` (Anthropic), `openai`, `azure`, `bedrock`, `mistral`, `moonshot`, `openrouter`, `zai`. Không cần viết integration mới.

Cấu hình bằng setting/env, không sửa code:

| Setting | Env var | Ghi chú |
| --- | --- | --- |
| `llm-metabot-provider` | `MB_LLM_METABOT_PROVIDER` | Format `provider/model`, ví dụ `anthropic/claude-haiku-4-5` |
| `llm-anthropic-api-key` | `MB_LLM_ANTHROPIC_API_KEY` | Bắt buộc prefix `sk-ant-` |
| `llm-max-tokens` | `MB_LLM_MAX_TOKENS` | Mặc định 4096 |
| `llm-request-timeout-ms` | `MB_LLM_REQUEST_TIMEOUT_MS` | |
| `llm-rate-limit-per-user` | `MB_LLM_RATE_LIMIT_PER_USER` | |

Các provider khác dùng cùng quy ước: `llm-openai-api-key`, `llm-openrouter-api-key`, `llm-bedrock-access-key-id`, v.v. Xem `src/metabase/llm/settings.clj`.

### Cái gì chạy được không cần license

`ai-features-enabled?` và `metabot-enabled?` đều mặc định `true` và không bị feature-gate. API key trực tiếp (`llm-*-api-key`) cũng không bị gate. Nghĩa là **MetaBot mặc định chạy được trên OSS với API key tự cung cấp**.

### Cái gì cần license

| Tính năng | Feature flag |
| --- | --- |
| Sửa system prompt (`metabot-chat-system-prompt`, `metabot-nlq-system-prompt`, `metabot-sql-system-prompt`) | `:ai-controls` |
| Đổi tên/icon MetaBot (`metabot-name`, `metabot-icon`, `metabot-show-illustrations`) | `:ai-controls` |
| Ưu tiên verified content | `:content-verification` |
| Semantic search trong tool | `:semantic-search` |
| Transform tools | `:transforms-basic`, `:transforms-python` |
| Metabase-managed AI proxy (`llm-proxy-base-url`) | `:metabase-ai-managed` hoặc `:metabot-v3` |

Không có license thì Phase 3 phải làm bằng cách fork code trong `src/metabase/metabot/`, không dùng được setting.

## Context dữ liệu hiện có

`local-context/data/` là bản sao local của data project BI trước đó, gồm:

- Source workbook và feature list.
- Pipeline Bronze, Silver, Gold.
- Serving dataset `feature_values_monthly_v1_0_0.csv`.
- Các Gold tables như customer snapshot, feature snapshot, monthly P&L và global monthly.

Các tài liệu quan trọng nằm trong `local-context/docs/`:

- `project_architecture_specification.md`: kiến trúc dữ liệu tổng thể.
- `medallion_cube_and_embedding_guide.md`: mô hình Medallion/cube và semantic context.
- `column_description.md`: data dictionary.
- `Feature Store Query and Reporting Agent.md`: mục tiêu agent và kiểu câu hỏi.
- `end_to_end_pipeline_flow.md`: luồng xử lý dữ liệu.

`local-context/integration/` có Docker Compose, script setup Metabase, agent/test hiện có, SQL tạo views và tài liệu AgentRouter. Không có `.env` hay secret trong thư mục này.

## Kiến trúc đích

```text
Người dùng
  -> MetaBot UI trong Metabase
  -> MetaBot backend + policy/permissions
  -> LLM provider (OpenAI, Anthropic, OpenRouter hoặc Bedrock)
  -> Metabase semantic layer (models, metrics, collections, permissions)
  -> Database/warehouse chứa Bronze-Silver-Gold data
```

Khi cần API nghiệp vụ ngoài, không để chatbot gọi trực tiếp endpoint bất kỳ. Bổ sung một backend tool service có xác thực, allowlist endpoint, rate limit và audit log:

```text
MetaBot tool -> internal tool service -> approved external API
```

## Nguyên tắc an toàn

1. Không đưa API key vào frontend, dashboard, collection metadata hoặc Git.
2. Chỉ dùng metadata database bản sao khi thử migration/image custom lần đầu.
3. MetaBot mặc định chỉ có quyền đọc các collection/model đã kiểm duyệt.
4. Bật/ưu tiên verified content; không tự động thực thi SQL hoặc action thay đổi dữ liệu ngoài phạm vi cho phép.
5. `local-context/` là local-only; không commit data, workbook, `.env` hoặc tài liệu nhạy cảm.

## Kế hoạch thực hiện

Toàn bộ code và tài liệu của POC nằm ở [dev/metabot-poc/](dev/metabot-poc/).

### Phase 1 — Chạy nền tảng — XONG

- `dev/metabot-poc/compose.yml`: Metabase build từ source (EE, không license), app DB
  riêng, warehouse Postgres riêng.
- Provider cấu hình qua env; đã chạy thử `openai/qd/qmodel_38max` và
  `anthropic/claude-opus-4-8` qua gateway tương thích.
- `dev/metabot-poc/warehouse/`: DDL, loader từ CSV Silver/Gold, và role read-only
  `metabase_reader` chỉ thấy schema `analytics`.

### Phase 2 — Semantic layer cho dữ liệu BI — XONG

- Hai view fact-grain `analytics.fact_transactions` (31.685 dòng) và
  `analytics.fact_events` (40.000 dòng), thay hai view monthly-aggregate cũ vốn chỉ
  đáp ứng 5/13 câu hỏi demo.
- Mọi view và cột đều có `COMMENT ON` mang thuật ngữ tiếng Việt. Metabase sync thành
  field description, và MetaBot đọc được qua tool `get-tables`.
- Collection `BI Analytics` với 3 metric: Doanh thu, Số giao dịch, Số event.
- `dev/metabot-poc/provision_metabase.py` làm toàn bộ việc này, idempotent.

**Bằng chứng:** [BASELINE.md](dev/metabot-poc/BASELINE.md) — 33/35 lượt đo đạt.

### Phase 3 — Tùy biến chatbot — QUYẾT ĐỊNH KHÔNG LÀM

Cần license `:ai-controls` cho `metabot-*-system-prompt`, `metabot-name`,
`metabot-icon`. Đường vòng hợp lệ duy nhất là sửa Selmer template trong
`resources/metabot/prompts/` rồi tự build — **không** gỡ `:feature` khỏi
`defsetting`, vì đó là vô hiệu hoá license check.

Đã dựng công cụ cho đường này (`dev/metabot-poc/patch_prompts.py`, vòng lặp ~70 giây
thay vì rebuild 17 phút) và lên plan chi tiết
([PLAN_PHASE3_FORK.md](dev/metabot-poc/PLAN_PHASE3_FORK.md)), nhưng **dừng lại**:

- Bộ 13 câu số đã 13/13 nên không còn chỗ đo cải thiện.
- Bộ 8 câu khó cũng 8/8 — MetaBot vốn đã nêu giới hạn đúng mà không cần prompt riêng.

**Kết luận của Phase 3: với dataset này, semantic layer quan trọng hơn prompt
engineering.** `COMMENT ON` trên view và cột làm được gần hết việc mà system prompt
tuỳ biến định làm — MetaBot tự phát hiện doanh thu VinFast bằng 0, tự nêu khoảng dữ
liệu 2025, tự cảnh báo mọi dòng đều `completed`, đều chỉ nhờ mô tả cột.

### Phase 4 — Tool/API ngoài — KHÔNG THỰC HIỆN

Chưa có use case cụ thể. Giữ lại phần dưới đây làm ghi chú cho lần sau.

- Xác định API và action được phép.
- Xây tool service riêng, server-side only.
- Định nghĩa request/response schema, authentication, audit log, timeout và rate limit.
- Đăng ký tool với MetaBot; test tool isolation và permission boundaries.

**Kết quả mong đợi:** chatbot chỉ gọi được API đã duyệt, có trace đầy đủ và không nhận endpoint/API key từ prompt người dùng.

## Definition of done cho POC đầu tiên — ĐẠT

| Tiêu chí | Trạng thái |
| --- | --- |
| Chạy Metabase local bằng image tự build | ✅ `dev/metabot-poc/compose.yml`, build từ source EE |
| Provider LLM qua biến môi trường | ✅ `MB_LLM_METABOT_PROVIDER` + `MB_LLM_*_API_KEY` |
| Nạp Gold/serving data | ✅ 97.085 dòng Silver/Gold, expose qua 2 view `analytics` |
| ≥10 câu acceptance test có kết quả mong đợi | ✅ 13 câu số + 8 câu khó, ground truth ở [EXPECTED_RESULTS.md](dev/metabot-poc/EXPECTED_RESULTS.md) |
| Trả lời đúng, tôn trọng quyền đọc, không ghi dữ liệu | ✅ 33/35 lượt đo đạt; `metabase_reader` bị từ chối trên `silver`/`gold`/`bronze` và mọi thao tác ghi |
| Không có data hoặc secret trong commit | ✅ `local-context/` ngoài Git, `.env` gitignore |

## Quyết định đã chốt

1. **License EE:** không có. Phase 3 vì thế bị chặn, và cuối cùng quyết định không làm.
2. **Data source:** Postgres riêng, nạp từ `local-context/data/pipeline/` (Silver + Gold).
   View cũ trong `scripts__sql__04_init_metabase_views.sql` bị thay vì chỉ đáp ứng 5/13
   câu hỏi.
3. **Provider:** gateway tương thích OpenAI/Anthropic chạy local. Đã dùng
   `openai/qd/qmodel_38max` rồi `anthropic/claude-opus-4-8`.
4. **Nhóm câu hỏi ưu tiên:** doanh thu, số giao dịch, số event — theo tháng, tỉnh,
   sản phẩm, tên sự kiện.
5. **Tool/API ngoài:** không cần. Phase 4 không thực hiện.

## Tài liệu POC

| File | Nội dung |
| --- | --- |
| [dev/metabot-poc/README.md](dev/metabot-poc/README.md) | Dựng và chạy stack |
| [BUILD_GUIDE.md](dev/metabot-poc/BUILD_GUIDE.md) | Build image từ source |
| [warehouse/README.md](dev/metabot-poc/warehouse/README.md) | Warehouse, view, phân quyền |
| [DEMO_QUESTIONS.md](dev/metabot-poc/DEMO_QUESTIONS.md) | 13 câu demo |
| [EXPECTED_RESULTS.md](dev/metabot-poc/EXPECTED_RESULTS.md) | Ground truth |
| [BASELINE.md](dev/metabot-poc/BASELINE.md) | Baseline 3 lượt |
| [HARD_QUESTIONS.md](dev/metabot-poc/HARD_QUESTIONS.md) | 8 câu khó, chấm hành vi |
| [NEXT_STEPS.md](dev/metabot-poc/NEXT_STEPS.md) | Việc còn lại |
| [PLAN_PHASE3_FORK.md](dev/metabot-poc/PLAN_PHASE3_FORK.md) | Plan fork prompt (chưa thực hiện) |

