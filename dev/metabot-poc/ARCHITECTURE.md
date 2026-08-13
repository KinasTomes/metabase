# MetaBot POC — kiến trúc

Tài liệu này mô tả hệ thống đang chạy: các thành phần, luồng một câu hỏi đi qua,
và **lý do** của những quyết định không hiển nhiên. Phần "vì sao" quan trọng hơn
phần "là gì" — sơ đồ thì đọc code cũng ra, còn lý do thì không.

## 1. Tổng thể

```
      người dùng (tiếng Việt)
              │
              ▼
   ┌──────────────────────┐        ┌────────────────────┐
   │  Metabase + MetaBot  │───────▶│  LLM qua gateway   │
   │  (fork, build EE)    │◀───────│  (gorouter/9router)│
   └──────────┬───────────┘        └────────────────────┘
              │ metabase_reader (chỉ SELECT trên analytics)
              ▼
   ┌──────────────────────────────────────────────────┐
   │  Postgres warehouse                              │
   │                                                  │
   │  analytics/       ← bề mặt DUY NHẤT Metabase thấy │
   │  silver/ gold/ feature_store/  ← bị chặn          │
   └──────────────────────────────────────────────────┘
              ▲
              │ load_warehouse.py
   CSV pipeline + feature registry (local-context/, không commit)
```

Ba container: `metabase`, `warehouse` (Postgres 16, dữ liệu BI), `metabot-app-db`
(Postgres 16, dữ liệu nội bộ Metabase). Tách app DB khỏi warehouse để Metabase
không bao giờ có đường ghi vào kho dữ liệu.

## 2. Vì sao chọn Metabase thay vì tự viết text-to-SQL

Đề bài nói "text to SQL engine". Chúng tôi không sinh SQL — MetaBot sinh **MBQL**,
một cây truy vấn có cấu trúc, rồi Metabase biên dịch xuống SQL.

Đổi lại được ba thứ mà một pipeline sinh SQL thô phải tự làm:

- **Không có SQL injection và không có truy vấn sai cú pháp.** MBQL không hợp lệ
  thì fail lúc dựng, không phải lúc chạy.
- **Phân quyền được ép ở tầng dưới.** Kể cả MetaBot có dựng truy vấn trỏ vào
  `silver`, kết nối cũng bị Postgres từ chối.
- **Kết quả tự render thành bảng/biểu đồ**, và người dùng bấm vào sửa được —
  đúng yêu cầu "chat interface" của Sprint 2 mà không phải viết frontend.

Cái mất: không kiểm soát trực tiếp SQL sinh ra, và bị giới hạn trong những gì
MBQL biểu diễn được.

## 3. Kênh duy nhất để tác động lên model

POC này **không có license `:ai-controls`**, nên không sửa được system prompt.
Điều đó nghe như một hạn chế, nhưng nó ép ra kiến trúc tốt hơn: mọi tri thức
nghiệp vụ phải nằm trong **metadata của dữ liệu**, không nằm trong prompt.

Đường đi cụ thể:

```
COMMENT ON COLUMN  →  Postgres catalog  →  Metabase sync  →  field.description
                                                                    │
                                              tool get-tables ──────┘
                                                    │
                                                    ▼
                                            context của LLM
```

Kiểm chứng bằng `provision_metabase.py`, bước `verify_descriptions()`: script
**thoát mã 1** nếu còn bất kỳ bảng hay field nào chưa có mô tả. Hiện 68/68 field
đều có.

Lưu ý một cái bẫy đã xác minh: đường context còn lại — `format-table-ddl` — chỉ
mang **tên cột và kiểu**, không mang mô tả. Nếu comment không sync được, model
vẫn chạy bình thường, chỉ là mù. Hỏng im lặng, nên phải có bước verify.

### Hệ quả: prompt engineering hoá ra là thứ yếu

Đã đo: MetaBot tự nêu ra doanh thu VinFast bằng 0, khoảng dữ liệu 2025, và
`status` toàn `completed` — **chỉ nhờ column comment**, không cần một dòng prompt
nào. Kết luận này là lý do Phase 3 (sửa prompt qua fork) bị bỏ.

## 4. Tầng ngữ nghĩa: `analytics`

Sáu view, là toàn bộ những gì Metabase nhìn thấy.

| View | Grain | Dòng | Vai trò |
| --- | --- | ---: | --- |
| `fact_transactions` | giao dịch | 31.685 | doanh thu, số giao dịch |
| `fact_events` | sự kiện | 40.000 | tương tác app |
| `fact_customer_features` | (global_customer, tháng) | 2.400 | 20 feature servable |
| `dim_customer` | (customer_id, pnl) | 4.000 | nhân khẩu học |
| `dim_global_customer` | global_customer_id | 2.600 | **đích join** |
| `dim_feature_catalogue` | feature_name | 34 | định nghĩa, không phải dữ liệu |

### 4.1 Vì sao có hai dimension khách hàng

Metabase chỉ khai được **FK một cột**. Mọi khoá tự nhiên còn lại đều ghép:
`(customer_id, pnl)` cho fact, `(global_customer_id, snapshot_month)` cho feature.
Trỏ FK vào `dim_customer.customer_id` sẽ join một dòng ra nhiều dòng và **nhân đôi
doanh thu** — sai âm thầm, không có lỗi nào báo.

`dim_global_customer` tồn tại vì nó là khoá đơn duy nhất thật sự unique. Cả bốn FK
đều trỏ về nó.

Nó **cố tình không mang nhân khẩu học**. Hai hồ sơ PnL của cùng một người mâu
thuẫn nhau quá nhiều: trong 2.600 người, 1.400 khác ngày sinh, 1.219 khác tỉnh,
929 khác giới tính. Chọn một bên là bịa dữ liệu, mà giá trị dimension bịa thì model
không có cách nào biết là sai. Chỉ `is_vip` nhất quán nên chỉ nó được đưa lên.

### 4.2 Vì sao feature store bị pivot

Bảng serving là **EAV**: 163.200 dòng, mỗi dòng một cặp `feature_name`/`feature_value`.
Để trả lời "khách này hoàn thành bao nhiêu chuyến GSM trong 3 tháng", model phải
đoán đúng từng ký tự chuỗi `gsm_transaction_completed_txn_count_l3m`.

Pivot thành 20 cột số, mỗi cột một `COMMENT ON` **sinh tự động từ registry** nên
mô tả không thể lệch khỏi metadata đã duyệt.

Grain là `(global_customer_id, snapshot_month)`, không phải `(customer_id, pnl, month)`.
Bảng serving lưu mỗi người hai lần — một lần dưới mỗi PnL — và điền NULL cho
feature của đơn vị kia. Đã kiểm chứng trên nguồn: **không key nào có hai giá trị
non-null**, nên gộp bằng `MAX` là lossless và cho ra thứ tốt hơn cả hai nửa: một
dòng chứa cả feature GSM lẫn VinFast. Nhờ vậy **so sánh cross-unit không cần join**.

Chỉ snapshot mới nhất được phơi ra. Bảng serving là content-addressed, snapshot mới
*append* chứ không ghi đè, nên pivot không lọc sẽ âm thầm trộn hai snapshot.

### 4.3 Ranh giới catalogue / executable fact

Đây là quyết định kiến trúc quan trọng nhất trong tầng ngữ nghĩa.

Registry là danh mục những gì đã được **định nghĩa**; nó không phải bằng chứng rằng
một chỉ số **trả lời được**. Hai thứ đó tách nhau ở `cancelled`:

- `transaction_status_semantics_v1` (mentor duyệt) coi `cancelled` là business
  status thật, báo cáo tách khỏi `completed`.
- `data_contract.json` ép `transactions.status` chỉ nhận `["completed"]` → chưa
  dòng cancelled nào được materialize vào fact.
- Holdout `H008` vì thế mang `expected_status: unsupported`.

Registry vẫn có 14 feature `cancelled` **kèm giá trị** trong serving. Pivot chúng
thành cột truy vấn được thì agent sẽ trả lời H008 bằng một con số tự tin lấy từ
snapshot chưa reconcile — đúng thất bại mà bản review sinh ra để ngăn, chỉ khác là
nó đi vào qua tầng ngữ nghĩa thay vì qua prompt.

Nên phân tách là **cấu trúc**, không phải văn bản:

- `fact_customer_features` — 20 feature servable, có cột, truy vấn được.
- `dim_feature_catalogue` — đủ 34, kèm `serving_status` và `not_servable_reason`.

Lý do từ chối trở thành **dữ liệu** để model trích dẫn, thay vì một câu nó phải tự
nghĩ ra.

Đo hai lần, và kết quả khác nhau ở chỗ đáng chú ý. Lần đầu MetaBot mở catalogue,
trích `catalogue_only` và dẫn đúng ràng buộc data contract. Lần thứ hai nó **không**
mở catalogue, thậm chí còn tin nhầm rằng `fact_customer_features` vẫn chứa cột hủy —
nhưng vẫn từ chối, vì cột đó thực sự không tồn tại để mà truy vấn. Nó còn tự tìm ra
một lý do mình chưa hề viết vào metadata: feature hủy là cửa sổ trượt nên không cộng
dồn được theo khoảng ngày mà không đếm trùng.

Rút ra: **phần chặn hiệu quả là việc rút cột, không phải câu chữ trong catalogue.**
Catalogue cải thiện *chất lượng lời giải thích* khi model chịu đọc, nhưng thứ bảo
đảm không có con số nào lọt ra là cấu trúc. Đúng như dự đoán, chỉ là bằng chứng đến
theo đường vòng.

Bài học rút ra khi làm phần này: bản đầu tôi *mô tả* mâu thuẫn trong comment rồi coi
là xong. **Mô tả cái bẫy không phải là đóng nó lại** — cột vẫn truy vấn được, và
MetaBot vẫn trả 7.712 nếu bị hỏi.

### 4.4 Nguồn gốc dữ liệu, và vì sao chỉ có 34 feature

Phần này quan trọng khi đọc mọi con số trong POC.

Dữ liệu đầu vào của cả dự án chỉ gồm **hai file**: `features_list_20260719.xlsx`
(danh mục feature) và `global_txn_v3_20251101.xlsx` (thống kê phân phối, sheet
`nullrate`). Toàn bộ dữ liệu giao dịch, sự kiện, khách hàng là **dummy sinh ra từ
hai file đó**, seed `20260722`. Không có bản ghi thật nào.

Hệ quả trực tiếp, đọc từ `dummy_distribution/manifest.json`:

| | Số |
| --- | ---: |
| Feature trong scope dự án | 839 → 824 duy nhất |
| **Có profile phân phối thật** | **163** |
| Sinh bằng heuristic theo kiểu dữ liệu | 661 |

Phân phối chỉ phủ 163 feature, nên 80% giá trị trong feature snapshot là do một
heuristic bịa ra. Ranh giới đó **không tôn trọng registry**: trong 20 feature đang
phục vụ, **12 là heuristic** — gồm toàn bộ 6 feature event và mọi cửa sổ ngắn hơn
một tháng. Chỉ feature giao dịch với cửa sổ ≥ 1 tháng mới có phân phối thật.

Điều này giải thích một chênh lệch từng làm mình bối rối: `l3m` completed cho 4,355
từ feature store nhưng 5,419 khi tính từ fact trên **đúng cùng 200 khách**. Không
phải bug — feature `PROFILED` được lấy mẫu từ phân phối của workbook nguồn, chưa bao
giờ dẫn xuất từ bảng fact này. Khác nguồn gốc, không phải sai số.

Cách xử lý: thêm `distribution_status` vào catalogue, **trực giao** với
`serving_status`, và gắn cảnh báo vào mô tả của đúng 12 cột đó — sinh từ manifest
nên không lệch được.

**Vì sao không rút chúng đi như đã rút `cancelled`.** Hai thứ khác loại. `cancelled`
là một **lệnh cấm** có căn cứ: quyết định mentor duyệt, data contract, và H008 đánh
dấu `unsupported`. Heuristic là một **cảnh báo chất lượng**: không luật nào cấm phục
vụ, và chính đợt engineering review đã cố ý đưa chúng vào kèm giả định ghi rõ. Cấm
tuyệt đối thì ép bằng cấu trúc; không chắc chắn thì mô tả. Rút chúng đi sẽ xoá sạch
mảng event và là bê nguyên bài học cũ sang một tình huống khác loại.

**Vì sao đúng 34 feature.** Không phải tập tuỳ tiện. Chúng khớp chính xác ba review
group trong `metadata/feature_store/reviews/engineering_mvp_v1.json` — GSM
transaction status counts (14), VinFast transaction status counts (14), GSM event
total counts (6) — mỗi group có `review_basis` riêng, ký ngày 2026-08-03.

Scope P0 thật ra có **540** feature, trong đó **147 cái có phân phối thật** đang nằm
ngoài registry, kể cả những đo lường tiền tệ (`completed_original_price_sum`) mà
feature store hiện hoàn toàn thiếu — nó chỉ có count.

Không thêm được. Mỗi dòng registry mang `review_decision_hash` băm từ một quyết định
review có thật, và DDL có `CHECK (semantic_status = 'engineering_reviewed')`. Thêm
147 feature kia nghĩa là **đúc hash cho một cuộc review chưa từng diễn ra**. Ràng
buộc đó chính là câu trả lời: bảng từ chối, và nó đúng khi từ chối.

Đường mở rộng hợp lệ là một đợt review mới sinh ra registry `1.1.0`. Đó là việc của
con người, không phải của engineering — và generator ở đây đã sẵn sàng cho nó.

## 5. Bảo mật và cô lập

Phòng thủ theo lớp, mỗi lớp độc lập:

| Lớp | Cơ chế | Đã kiểm chứng |
| --- | --- | --- |
| Role | `metabase_reader`, chỉ `SELECT` trên `analytics` | `permission denied` ở silver/gold/bronze/feature_store |
| Kết nối | `schema-filters-type: inclusion` = `analytics` | sync không chạm schema khác |
| `search_path` | ghim `analytics` cho role | |
| Schema | `REVOKE ALL ... FROM PUBLIC` | |
| App DB | tách container, khác credential | |

Kiểm chứng lại bằng một lệnh, chạy từ đúng đường mạng mà Metabase dùng:

```bash
docker run --rm --network metabot-poc_default -e PGPASSWORD=... postgres:16-alpine \
  psql -h warehouse -U metabase_reader -d bi_warehouse -tAc "select count(*) from silver.transactions"
# ERROR:  permission denied for schema silver
```

> **Cạm bẫy.** Đừng test qua `psql -h 127.0.0.1` trong container: `pg_hba.conf` của
> image postgres có `host all all 127.0.0.1/32 trust` **đứng trước** dòng scram, nên
> nó báo thành công kể cả khi mật khẩu sai. Đã suýt kết luận ngược vì lỗi này.

## 6. Đo lường

Hai bộ, đo hai thứ khác nhau. Cả hai đều **chấm bằng cách thực thi truy vấn
MetaBot dựng ra**, không chấm văn bản — văn bản muốn diễn đạt kiểu gì cũng được,
còn truy vấn thì hoặc đúng cột đúng filter hoặc không.

**`run_acceptance.py` — 16 câu, chấm số.** Lấy MBQL từ stream, chạy qua
`/api/dataset`, so với `EXPECTED_RESULTS.md`. Câu trả lời nghe hợp lý mà không có
truy vấn nào phía sau bị chấm `NO_QUERY`, không phải PASS.

Câu 1–13 đo truy vấn một bảng. Câu 14–16 mới thêm, bắt buộc join — vì 13/13 của bộ
cũ **không nói gì** về khả năng join, đúng thứ Sprint 2 đòi.

**`run_hard_questions.py` — 9 câu, chấm hành vi.** Khi không có đáp án đúng, model
nêu giới hạn hay bịa số. Chấm bằng regex nên **thô**; báo cáo luôn in nguyên văn để
đọc lại. Ngoại lệ là H9, có nhóm tín hiệu hẹp đã kiểm chứng phân biệt được câu đúng
với câu nói quá rộng.

## 7. Vòng lặp phát triển

Build lại image mất 17–40 phút, nên có `patch_prompts.py`: chép jar gốc ra
`.cache/`, thay resource, đẩy ngược vào container, restart — **~80 giây**.

Giới hạn phải biết: nó chỉ thay được **file resource**. Hằng số đã biên dịch thì
không. Ví dụ đã gặp: `security.clj` khai `inline-js-hashes` là `^:const`, AOT nội
tuyến digest thẳng vào bytecode, nên vá file JS không đổi được header CSP — bắt buộc
rebuild.

## 8. Những cái đã cắn, ghi lại để khỏi cắn lại

**CRLF, hai lần.** Lần một: shebang `run_metabase.sh` thành `#!/bin/bash\r`,
container chết với `no such file or directory`. Lần hai, tinh vi hơn: `security.clj`
hash **bytes file**, còn trình duyệt hash nội dung **sau khi HTML parser chuẩn hoá
CRLF→LF**, nên CSP chặn sạch script inline và trang trắng tinh — không request nào
lỗi, không log nào báo. `.gitattributes` giờ ép LF cho cả hai nhóm file.

**Bài học đắt hơn:** toàn bộ test đều gọi API, chưa từng render HTML, nên lỗi này
vô hình suốt nhiều ngày "xanh". Một chiều chưa test là một chiều chưa biết.

**Timezone.** `transaction_date` là `TIMESTAMPTZ`; `::DATE` trần sẽ resolve theo
session zone. Dưới `America/Los_Angeles` cho ra **13 bucket tháng** và rò 59 event
sang 2024-12. Mọi phép ép kiểu ngày giờ đều ghim `AT TIME ZONE 'UTC'`.

**Mật khẩu app DB.** Postgres chỉ đọc `POSTGRES_PASSWORD` lúc initdb. Sửa `.env` sau
đó không có tác dụng lên volume đã tồn tại, và triệu chứng là một stack trace
`ExceptionInInitializerError` dài loằng ngoằng che mất nguyên nhân thật.

**Protocol stream đổi giữa hai bản build.** Từ dòng có tiền tố (`0:`, `9:`) sang SSE
`data: {"type":...}`, và truy vấn dời từ base64 trong `navigate_to` sang
`data-state.queries` dạng pMBQL. Harness im lặng thấy rỗng. Giờ parse cả hai.

**Lỗi gateway đến qua kênh text, không qua kênh error.** Quota hết bị chấm thành
`NO_QUERY` — tức chấm nhầm lỗi hạ tầng thành model trả lời sai. Giờ có
`GATEWAY_ERROR_RE` và verdict `PROVIDER_ERROR` riêng.

## 9. Còn thiếu

- Baseline đã chạy lại: **16/16** acceptance, **5/9** hard (đọc tay 6/9).
  Ba câu FABRICATED/REVIEW đã phân tích trong `HARD_QUESTIONS.md`.
- Câu 14–16 đã PASS — khả năng join **đã có bằng chứng**.
- H5 cần viết lại: `dim_global_customer` đã xoá mất sự mơ hồ mà câu đó dùng để bẫy.
- Sprint 3 (quét chủ động, đẩy summary lên kênh) chưa bắt đầu.
