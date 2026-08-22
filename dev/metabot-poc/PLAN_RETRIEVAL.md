# Plan — Retrieval cho mô tả cột: đánh giá ý tưởng embedding và lộ trình thay thế

Ý tưởng đặt ra: tận dụng **embedding có sẵn của Metabase** (semantic search) để model
không phải đọc hết mọi description của các feature column — chỉ retrieve đúng phần cần.

Kết luận nhanh: **chưa làm**. Ba blocker nằm ở code (đã verify), trong đó một cái chặn
hẳn ý tưởng theo nghĩa đen của nó. Bốn hướng thay thế dưới đây theo đúng tinh thần
kiến trúc hiện tại: deterministic, verifiable, không qua mặt license.

---

## 1. Phát hiện từ code (đã verify trên tree này)

| # | Phát hiện | Bằng chứng |
| --- | --- | --- |
| 1 | Search index **ở cấp entity** (`table/model/metric/question/dashboard/document/indexed-entity`), thuộc tính được index chỉ là `name/display_name/collection_name/description` **của entity đó** | `src/metabase/search/impl.clj:178` |
| 2 | **Field không phải search entity** — description của feature column không nằm trong index nào. Cột chỉ tới được model qua `read_resource` → `metabase://table/{id}/fields` | `src/metabase/metabot/tools/resources.clj` (URI table) |
| 3 | Tham số `semantic_queries` trên tool `search` khai báo `{:feature :semantic-search}` — bị gate license EE | `src/metabase/metabot/tools/search.clj:575` |
| 4 | Capability `:feature-semantic-search` chỉ bật khi token có entitlement; engine là pgvector nằm ở enterprise module | `metabot/capabilities.clj:46`, `premium_features/settings.clj:279`, `enterprise/backend/src/metabase_enterprise/semantic_search/` |
| 5 | Keyword search chạy được **không license**, nhưng chỉ full-text tên + mô tả *bảng* | cùng chỗ |

## 2. Vì sao chưa làm

1. **Sai granularity.** Không tồn tại đường retrieve description của *cột* bằng semantic
   search có sẵn — nó index cấp bảng/model/metric. Ý tưởng theo nghĩa đen không có sẵn.
2. **License.** Bật `semantic_queries` cần entitlement `:semantic-search` — cùng loại rào
   `:ai-controls` mà Phase 3 đã quyết định **không** vượt qua mặt (xem
   [PLAN_PHASE3_FORK.md](PLAN_PHASE3_FORK.md), mục "Ranh giới quan trọng").
3. **Vấn đề chưa tồn tại.** Model không bao giờ đọc "hết tất cả" description trong một
   lần — mỗi iteration đọc fields của **một bảng** (~20–30 dòng text, vài KB cho bảng
   pivot hiện tại). Mức phải lo là registry 1.1.0 với 147+ feature, mà vẫn nhỏ.

Và rủi ro kiến trúc nếu làm sớm: bài học Sprint 2 — *"metadata đặt sự thật vào tầm với
của model"*. Retrieval biến "trong tầm với" thành "**tùy độ khớp ngữ nghĩa**": câu hỏi
tiếng Việt phải khớp vector với tên cột kiểu `gsm_transaction_completed_txn_count_l3m`.
Trượt là **mù im lặng** — đúng lớp lỗi hỏng im lặng mà push_descriptions, fidelity gate,
PROVIDER_ERROR đã dành nhiều sprint để diệt. Thêm dữ kiện gpt-5.6-luna phớt lờ cảnh báo
ngay cả khi nó *nằm trong context*: giấu sau retrieval chỉ tệ hơn.

## 3. Bốn hướng, theo thứ tự ưu tiên

### Hướng 1 — Đầu bảng thay vì đầu cột (làm khi cần)

Keyword search tool (OSS, free) đã match tên + mô tả ở cấp table/model/metric. Đầu tư
vào chất lượng **entry point**: model/metric trong collection `BI Analytics`, mô tả bảng
viết cho đúng cách người dùng hỏi. Model đổ đúng bảng rồi mới đọc fields — retrieval xảy
ra ở granularity an toàn, description cột vẫn full trong `read_resource`.

### Hướng 2 — Coi `dim_feature_catalogue` là retrieval layer có cấu trúc (đã có)

Catalogue chính là lớp tra cứu của kiến trúc này: 34 định nghĩa trong một bảng nhỏ,
model mở ra tìm định nghĩa rồi mới chọn cột ở `fact_customer_features`. Verifiable,
không license, không fork drift. Khi thêm feature (registry 1.1.0) thì catalogue tự lớn
theo — giữ flow "catalogue trước, cột sau" trong prompt snippet `data-sources.selmer`
nếu cần nhấn mạnh.

### Hướng 3 — Tách view theo domain khi field list phình

Nếu một bảng có quá nhiều cột với comment dài, tách thành nhiều view theo domain nghiệp
vụ (GSM / VinFast / event...) để field list mỗi bảng nhỏ lại. Cùng tinh thần với quyết
định pivot EAV → 20 cột có comment sinh từ registry: ranh giới bằng **cấu trúc**, không
bằng văn bản.

### Hướng 4 — Embedding thật sự, chỉ khi bài toán scale có thật

Điều kiện kích hoạt: registry ≥ ~100 feature đang phục vụ HOẶC model thực tế thất bại
vì context (đo được, không phải cảm tính). Khi đó:

- Làm **phía harness** hoặc tool riêng đọc thẳng metadata, deterministic;
- Bắt buộc kèm lớp verify: *"mọi field được tham chiếu trong MBQL phải có description
  đã fetch"* — fail loud, không im lặng;
- Ghi rõ giá: fork-drift khi đụng `src/metabase/metabot/`, chi phí duy trì index, và
  một kênh truy xuất nữa phải verify như push_descriptions đã làm.

## 4. Điều cần chốt khi quay lại mục này

- Con số kích hoạt cụ thể (bao nhiêu feature / bao nhiêu token context mỗi câu) đo từ
  acceptance suite, không bốc.
- Nếu đi Hướng 4, chọn embedder nào và index ở đâu (app DB pgvector vs ngoài Metabase)
  trước khi viết code — đừng lặp lại đường `:semantic-search` bị gate.
