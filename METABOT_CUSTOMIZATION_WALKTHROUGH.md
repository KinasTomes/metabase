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

### Phase 1 — Chạy nền tảng

Hai việc đầu (đọc luồng provider/model, xác định feature gate) đã xong — kết quả ở mục "Hiện trạng upstream" phía trên. Còn lại:

- Dựng Metabase local với metadata database tách biệt.
- Set `MB_LLM_METABOT_PROVIDER` và API key của provider đã chọn qua env.
- Nạp database/warehouse chứa các Gold/serving tables.

**Kết quả mong đợi:** đăng nhập được Metabase local, thấy model/metric/collection mẫu và MetaBot trả lời được một câu hỏi bất kỳ, chưa đụng production.

### Phase 2 — Semantic layer cho dữ liệu BI

- Chuẩn hóa tên bảng, cột, mô tả và quan hệ trong Metabase.
- Tạo models/questions/metrics từ Gold và serving datasets.
- Gom nội dung đáng tin cậy vào collection dành cho chatbot.
- Viết bộ câu hỏi kiểm thử bằng tiếng Việt và tiếng Anh.

**Kết quả mong đợi:** MetaBot hiểu business terms và sinh câu trả lời đúng từ dữ liệu đã kiểm duyệt.

### Phase 3 — Tùy biến chatbot

Phần lớn không cần code, nhưng **cần license `:ai-controls`** (xem bảng feature gate).

- System prompt: set `metabot-chat-system-prompt`, `metabot-nlq-system-prompt`, `metabot-sql-system-prompt`.
- Branding: `metabot-name`, `metabot-icon`, `metabot-show-illustrations`.
- Giới hạn phạm vi dữ liệu và suggested prompts.
- Thêm policy rõ ràng cho SQL generation, chart/table response và fallback khi không đủ dữ liệu.
- Ghi nhận feedback, query đã dùng và token usage để đánh giá chất lượng — `src/metabase/metabot/feedback.clj` và `usage.clj` đã có sẵn.

Nếu không có license, phải sửa trực tiếp trong `src/metabase/metabot/` (prompt template ở `tmpl.clj`, context ở `context.clj`) và tự build image.

**Kết quả mong đợi:** chatbot trả lời ổn định cho nhóm câu hỏi BI ưu tiên, không lộ dữ liệu ngoài quyền người dùng.

### Phase 4 — Tool/API ngoài (chỉ khi có use case cụ thể)

- Xác định API và action được phép.
- Xây tool service riêng, server-side only.
- Định nghĩa request/response schema, authentication, audit log, timeout và rate limit.
- Đăng ký tool với MetaBot; test tool isolation và permission boundaries.

**Kết quả mong đợi:** chatbot chỉ gọi được API đã duyệt, có trace đầy đủ và không nhận endpoint/API key từ prompt người dùng.

## Definition of done cho POC đầu tiên

- Chạy được Metabase local bằng source/image tự build.
- Có một provider LLM test key qua biến môi trường/secret store.
- Nạp được một tập Gold/serving data vào database phù hợp.
- Có ít nhất 10 câu hỏi acceptance test và kết quả mong đợi.
- MetaBot trả lời đúng dữ liệu, tôn trọng quyền đọc và không sinh action ghi dữ liệu.
- Không có data local hoặc secret trong `git status`/commit.

## Quyết định cần chốt trước khi code tính năng

1. **Có license EE (`:ai-controls`) không?** Quyết định Phase 3 làm bằng setting hay phải fork code và tự build image.
2. Database/warehouse nào sẽ là data source cho POC? `local-context/integration/` đã có `docker-compose.yml` và `scripts__sql__04_init_metabase_views.sql`, cần xem lại trước khi dựng mới.
3. Provider LLM nào dùng cho môi trường test? (8 provider đã hỗ trợ sẵn, chọn 1.)
4. Nhóm câu hỏi BI ưu tiên đầu tiên là gì?
5. Có cần API/tool ngoài ngay POC hay chỉ chatbot trên dữ liệu Metabase?

