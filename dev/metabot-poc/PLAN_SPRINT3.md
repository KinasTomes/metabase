# Sprint 3 — Autonomous Storytelling & Handoff, kế hoạch

Đề bài: *"A scheduled daily job that detects notable data shifts across the feature
store and publishes a plain English executive summary to a designated team channel.
Delivery of final documentation and a closing presentation."*

---

## 0. Ràng buộc quyết định toàn bộ thiết kế: dữ liệu này không có xu hướng

Trước khi lên kiến trúc, tôi đo phân phối thật của `silver/transactions.csv`. Kết quả
làm đổi hẳn hình dạng của sprint này.

**Số giao dịch theo tháng gần như phẳng, doanh thu thì nhảy loạn:**

| Tháng | Giao dịch | Doanh thu (triệu) |
| --- | ---: | ---: |
| 2025-06 | 2.537 | 82,9 |
| 2025-07 | 2.370 | **96,2** |
| 2025-08 | 2.367 | 64,7 |
| 2025-09 | 2.747 | **58,3** |
| 2025-10 | 2.727 | 78,8 |

Số giao dịch dao động ±8%. Doanh thu dao động ±25%, và tháng 9 thấp hơn tháng 7 **39%**
trong khi *số giao dịch lại tăng 16%*. Lý do:

```
median amount        = 0          (64% giao dịch có amount = 0)
p99                  = 479.908
top 1% giao dịch     = 37% tổng doanh thu
```

Khoảng **27 giao dịch mỗi tháng quyết định hơn một phần ba doanh thu tháng đó**. Đuôi
nặng cỡ này thì trung bình tháng không ổn định, và mọi "biến động" tháng qua tháng đều
là **nhiễu lấy mẫu**, không phải tín hiệu.

Thêm hai chỗ nữa không có tín hiệu:

- **VinFast: 377 giao dịch cả năm, doanh thu làm tròn ra 0.** Mọi tỉ lệ phần trăm trên
  mẫu này đều vô nghĩa.
- **12 trong 20 cột feature là `NON_DISTRIBUTED`** — mỗi snapshot tháng được *lấy mẫu
  lại* từ cùng một phân phối tĩnh. Chênh lệch tháng qua tháng ở đó không chỉ là nhiễu,
  nó là nhiễu **theo đúng thiết kế của generator**.

### Hệ quả

Một scanner ngây thơ chạy trên bộ dữ liệu này sẽ **đêm nào cũng tìm ra một câu chuyện,
và đêm nào cũng bịa**. Tệ hơn chatbot bịa: không ai ngồi đó để hỏi vặn lại.

Nên mục tiêu của Sprint 3 phải phát biểu lại cho đúng:

> Không phải "tìm cho ra biến động". Là **phân biệt được biến động thật với nhiễu**, và
> im lặng khi không có gì để nói.

Và cách chứng minh nó hoạt động cũng đảo lại: chạy trên 12 tháng dữ liệu thật phải cho
**gần như không phát hiện nào**; chỉ khi tiêm một cú sốc nhân tạo thì mới được kêu.

Đây là điểm nhấn của buổi trình bày cuối, giống hệt vai trò của câu H008 ở Sprint 2.

---

## 1. Kiến trúc

Nguyên tắc duy nhất, rút từ bài học Sprint 2 (*metadata là điều kiện cần, không đủ*):
**LLM không được làm số học.**

```mermaid
flowchart LR
    subgraph D["Deterministic — SQL/Python"]
        S["scan.py<br/>tính metric, dò shift"] --> F["findings.json<br/><i>mọi con số sinh ra ở đây</i>"]
    end
    F --> N["narrate.py<br/>LLM chỉ diễn đạt"]
    N --> G{"gate:<br/>số trong văn bản<br/>có trong findings?"}
    G -->|không| X["FAIL — không gửi"]
    G -->|có| P["publish.py"]
    P --> CH["#channel + summary.md"]
    F -.->|link drill-down| MB["saved question<br/>trong Metabase"]

    style X fill:#f8d7da,stroke:#dc3545
    style D fill:#d4edda,stroke:#28a745
```

LLM chỉ nhận `findings.json` và viết lại thành tiếng Việt. Nó **không** được cấp quyền
truy vấn, không tự chọn metric, không tự tính phần trăm. Cổng chặn ở giữa là thứ biến
nguyên tắc đó thành ràng buộc thi hành được, không phải một câu dặn trong prompt.

### Vì sao không dùng MetaBot cho phần này

Nói thẳng trong tài liệu: MetaBot là **on-demand analyst**, không phải **proactive
reporter**. Sprint 2 đo được rằng nó bỏ sót caveat khi không ai hỏi lại. Một báo cáo tự
động thì không có ai hỏi lại. Nên luồng đêm đi đường xác định, còn Metabase vẫn giữ vai
trò **đích drill-down**: mỗi finding kèm link tới một saved question thật để người đọc
bấm vào tự kiểm.

---

## 2. Thiết kế bộ dò

### 2.1 Metric quét

| Nhóm | Metric | Nguồn |
| --- | --- | --- |
| Khối lượng | số giao dịch, số event, số khách active | `fact_transactions`, `fact_events` |
| Doanh thu | tổng, trung vị, tổng đã winsorize p99 | `fact_transactions` |
| Cơ cấu | tỉ trọng theo product / province | `fact_transactions` |
| Khách hàng | số khách mới, số khách dùng cả hai PnL | `dim_global_customer` |
| Feature store | trung vị của **8 cột `PROFILED`** | `fact_customer_features` |

**12 cột `NON_DISTRIBUTED` bị loại khỏi bộ dò** — không phải vì kém quan trọng, mà vì
chênh lệch tháng của chúng là nhiễu do generator tạo ra. Đây là lần thứ hai
`distribution_status` được dùng làm ranh giới thi hành, sau `serving_status`.

### 2.2 Luật phát hiện

Ba tầng, một finding phải qua cả ba:

1. **Cỡ mẫu.** n ≥ 300 giao dịch/tháng. Loại VinFast tự động — 31 giao dịch/tháng không
   đủ để nói bất cứ điều gì.
2. **Robust z-score.** So tháng mới nhất với **trung vị + MAD** của 6 tháng trước, không
   phải mean ± sd. Đuôi nặng làm sd phồng lên và giấu mất shift thật. Ngưỡng |z| ≥ 3,5.
3. **Kiểm tra đuôi.** Với metric tiền tệ, tính lại sau khi winsorize p99. Nếu shift biến
   mất → **không phải finding về doanh thu**, mà là finding loại khác:
   *"doanh thu tháng 7 cao do 3 giao dịch lớn"* — vẫn đáng nói, nhưng nói đúng bản chất.

Ngưỡng chốt sau bước hiệu chuẩn ở mục 4.1, không bịa trước.

### 2.3 Ba luật nữa, do chính bộ fixture đòi

Dựng xong scenario (mục 4) thì lộ ra ba chỗ ba tầng trên không với tới:

**Luật xu hướng.** `food_churn` giảm 4%/tháng, cộng dồn −19%, nhưng bước tháng lớn nhất
chỉ −9% — nằm gọn trong nhiễu. Bộ dò bước nhảy **không thể** thấy nó, mà đây lại là dạng
rủi ro kinh doanh thật nhất trong cả bộ. Cần thêm test xu hướng trên chuỗi 6 tháng
(Mann-Kendall hoặc độ dốc hồi quy). Nhãn `F1` (phải im) và `F2` (phải kêu) trỏ vào đúng
cùng một hiện tượng — chênh nhau ở chỗ dùng bộ dò nào.

**Luật hạng mục mới.** `province_expansion` cho Khánh Hòa xuất hiện từ 0 → 123 → 340
giao dịch. Không có baseline thì z-score chia cho 0 hoặc bỏ qua. Hạng mục mới phải là
một loại finding riêng, không phải một con số lệch.

**Trung bình winsorize cho cột feature.** 8 cột `PROFILED` là số nguyên đuôi nặng,
trung vị chỉ bằng 2. Trung bình thô thì dải 12 tháng thật là 4,36–12,56, gần gấp ba —
vô dụng. Trung bình winsorize p95 cho dải 3,45–5,41 (±44%), đủ ổn định để so. Cùng lý do
đuôi nặng như doanh thu, nên cùng cách xử lý.

> **Cạm bẫy `least()` — sẽ giẫm phải nếu winsorize bằng SQL.** Trong Postgres,
> `least(NULL, 20)` trả về **20**, không phải NULL: hàm này bỏ qua NULL thay vì lan
> truyền nó. Cột feature chỉ có 119/400 dòng non-null (khách VinFast không có feature
> GSM), nên `avg(least(feature_value, 20))` biến 281 NULL thành 281 giá trị 20 và đẩy
> trung bình từ 5,28 lên **15,25** — cao hơn cả trung bình thô, dù đang cắt ngọn.
>
> Tôi đã dính đúng lỗi này khi kiểm tra dữ liệu sau khi nạp, và suýt kết luận là hiệu
> ứng tiêm vào bị mất. `scan.py` phải winsorize kèm chặn NULL tường minh
> (`case when v is null then null else least(v, cap) end`), và bài test cho nó là một
> cột có NULL.

Xác nhận lại bằng thống kê đúng: hiệu ứng ×1,9 có trong DB — **trung vị dịch từ 2 lên 4**
ở ba tháng tiêm, và wmean p95 đạt 8,96 so với dải nền 3,45–5,41.

### 2.4 "Hằng đêm" trên dữ liệu tĩnh

Dữ liệu dừng ở 2025-12 và không có bản ghi mới. Dùng **đồng hồ mô phỏng**:

```bash
python nightly/run_nightly.py --as-of 2025-09    # coi 2025-09 là tháng vừa đóng sổ
python nightly/run_nightly.py                     # mặc định: tháng mới nhất có dữ liệu
```

Ghi rõ trong runbook rằng đây là mô phỏng. Không giấu — mà `--as-of` cũng chính là thứ
cho phép chạy backtest 12 tháng ở mục 4.1.

---

## 3. Thành phần phải viết

```
dev/metabot-poc/nightly/
├── scan.py           # metric + luật phát hiện → findings.json
├── narrate.py        # findings.json → tóm tắt tiếng Việt (LLM)
├── fidelity.py       # cổng chặn: đối chiếu từng con số trong văn bản
├── publish.py        # sink: file / Slack webhook / stdout
├── link_questions.py # tạo saved question trong Metabase cho mỗi finding
├── run_nightly.py    # điều phối
└── test_scan.py      # fixture tiêm shock + backtest
```

Cộng thêm:
- service `scheduler` trong `compose.yml` (cron trong container, không phụ thuộc host)
- `RUNBOOK.md` — vận hành, xử lý sự cố, đổi ngưỡng
- `PRESENTATION_FINAL.md`

### `fidelity.py` — phần đáng viết nhất

Trích mọi số trong văn bản LLM sinh ra, đối chiếu với `findings.json`:

- số phải xuất hiện trong findings (cho phép sai số làm tròn), **hoặc**
- suy ra được từ hai trường trong findings bằng một phép tính đã khai báo trước

Không khớp → **không gửi**, log ra và báo lỗi. Đây là câu trả lời trực tiếp cho thất bại
Q10/Q12 ở Sprint 2: ở đó không có cổng nào, model nói gì người dùng nhận nấy.

---

## 4. Cách chứng minh nó chạy đúng

### 4.1 Backtest im lặng — bài kiểm tra chính

Chạy scanner qua cả 12 tháng thật. **Kỳ vọng: gần như không finding nào.** Đo tỉ lệ báo
động giả, rồi chốt ngưỡng từ chính số đó thay vì chọn cảm tính.

Nếu nó kêu ầm ĩ trên dữ liệu không có tín hiệu, bộ dò sai — đó là kết quả cần biết, và
biết trước buổi demo.

### 4.2 Tiêm shock — bài kiểm tra độ nhạy

**Đã dựng xong** (`warehouse/gen_scenario_data.py`, `load_scenario.py`). Baseline là 12
tháng 2025 **thật, giữ nguyên**; sáu tháng 2026-01..06 được resample từ chính các dòng
thật — nên giữ nguyên phân phối amount, product, province — rồi mới tiêm hiệu ứng.

| Scenario | Tiêm gì | Đo được | Phải kêu |
| --- | --- | --- | :---: |
| `tet_surge` | Tết 17/02, dồn chuyến trước Tết, rỗng tuần lễ | taxi 670 → **1.053** (dải 557–712) | ✅ |
| `province_expansion` | mở Khánh Hòa, ramp 3 tháng | 0 → 123 → 340 | ✅ |
| `corporate_whale` | 4 chuyến express 8–14M | doanh thu **117M** (dải 58–96M) | ✅ |
| `pipeline_gap` | sự cố ingest event 9 ngày | event **2.621** (dải 3.253–3.437) | ✅ |
| `feature_store_shift` | đẩy 1 cột feature ×1,9 | wmean **8,96** (dải 3,45–5,41) | ✅ |
| `corporate_whale` (W2) | *cùng dữ liệu, winsorize p99* | **64M** (dải 42–74M) | ❌ |
| `corporate_whale` (W3) | *cùng dữ liệu, đếm giao dịch* | 2.677, phẳng | ❌ |
| `pipeline_gap` (G2) | *cùng dữ liệu, đếm giao dịch* | phẳng | ❌ |
| `food_churn` | −4%/tháng, cộng dồn −19% | bước lớn nhất −9% | ❌ |
| `vinfast_push` | chiến dịch ×1,8 | 31 → 56 dòng | ❌ |
| `null` | resample, không hiệu ứng | — | ❌ |

**Sáu dòng ❌ quan trọng ngang năm dòng ✅.** Cặp W1/W2 là cả bài kiểm tra tách đuôi:
cùng một tháng, doanh thu thô kêu, doanh thu đã cắt đuôi im — finding nào sống ở W1 mà
chết ở W2 thì bắt buộc phải kể là *"do bốn chuyến lớn"*, không được kể là tăng trưởng.

Hai chỗ suýt sai khi dựng, ghi lại vì cùng một bài học — **biên độ phải lấy từ phân phối
thật, không phải bốc**:

- Whale ban đầu để 4–6 **tỉ**, trong khi cả tháng chỉ 72 triệu. Gấp 280 lần tổng tháng
  thì không kiểm được gì. p99 thật là 479.908 và max lịch sử 8,67M, nên 8–14M mới là
  "chuyến lớn nhưng có thể xảy ra".
- Feature shift ban đầu để ×1,35, nằm gọn trong dải nhiễu 44% của chính cột đó.

Và VinFast phải **kẹp** số rút mỗi tháng vào dải thật 12–51: một lần rút Gauss không kẹp
ra 58, nhân 1,8 thành 3,4 lần — fixture khi đó kiểm cái máy rút số chứ không kiểm hiệu ứng.

### 4.3 Cách ly: dữ liệu bịa không được chạm vào `analytics`

Biến động tiêm vào **không phải fact**. Nếu chúng nằm trong `analytics`, MetaBot sẽ trả
lời "tháng nào giảm mạnh nhất" bằng một sự kiện chưa từng xảy ra — đúng loại lỗi của 14
cột `cancelled`, chỉ khác đường vào.

Mỗi scenario nằm ở schema riêng `scenario_<name>`, chặn bằng **hai lớp độc lập**:

1. `schema-filters-type: inclusion` = `analytics` → sync không thấy;
2. `REVOKE ALL ... FROM metabase_reader` → chặn ở tầng database.

Lớp 2 không thừa: lớp 1 là một ô cấu hình sửa được trong hai cú bấm ở admin UI, lớp 2
fail closed. Đã kiểm bằng cách kết nối thật bằng role đó:

```
scenario_null.fact_transactions  -> BLOCKED: permission denied for schema scenario_null
scenario_null.transactions       -> BLOCKED: permission denied for schema scenario_null
analytics.fact_transactions      -> 31685
```

Và ground truth Sprint 2 không suy suyển: `analytics` vẫn đúng 31.685 dòng, nên 16 đáp án
trong `EXPECTED_RESULTS.md` còn nguyên giá trị, không phải chạy lại bộ nào.

### 4.4 Kiểm tra độ trung thực số

Chạy `narrate.py` 10 lần trên cùng một findings, đếm số lần cổng chặn bắt được số bịa.
Con số đó nên được báo cáo thẳng trong buổi cuối — nó là bằng chứng định lượng cho luận
điểm chính của cả POC.

---

## 5. Kênh gửi

Mặc định **ghi file** `nightly/out/summary-YYYY-MM.md`, luôn chạy được, không cần gì
thêm. Slack là adapter tuỳ chọn bật bằng `SLACK_WEBHOOK_URL` trong `.env`.

Nếu có Slack workspace thật thì tôi bật; không thì demo bằng file kèm ảnh chụp định dạng
tin nhắn. Không chặn phần còn lại của sprint vì thiếu một cái webhook.

> Đã cân nhắc dùng **dashboard subscription có sẵn của Metabase** — nó gửi chart theo
> lịch được, nhưng gửi *mọi* lần chạy, không có khái niệm "chỉ gửi khi có gì đáng nói",
> và không sinh văn xuôi. Đúng vế "scheduled", trượt vế "detects notable shifts".

---

## 6. Thứ tự làm

| # | Việc | Ước lượng | Chặn ai |
| --- | --- | --- | --- |
| ~~0~~ | ~~Fixture tiêm shock có nhãn~~ | **xong** | |
| 1 | `scan.py`: 3 tầng ở 2.2 + 3 luật ở 2.3, backtest 12 tháng, hiệu chuẩn ngưỡng | 1 ngày | tất cả |
| 2 | Chạy `scan.py` qua 8 scenario, đối chiếu nhãn | 0,5 ngày | cần bước 1 |
| 3 | `narrate.py` + `fidelity.py` | 1 ngày | cần findings ổn định |
| 4 | `publish.py` + service `scheduler` | 0,5 ngày | |
| 5 | `link_questions.py` | 0,5 ngày | tuỳ chọn, làm sau cùng |
| 6 | `RUNBOOK.md` + presentation cuối | 1 ngày | |

Bước 1 phải xong trước khi động vào LLM. Nếu bộ dò còn nhiễu thì narration chỉ là bịa
cho mượt mà hơn.

---

## 7. Rủi ro

| Rủi ro | Xử lý |
| --- | --- |
| Không tiêm shock thì scanner chẳng bao giờ có gì để kể → demo trống | Demo hai lần: chạy thật (im lặng, đúng) rồi chạy trên fixture (kêu, đúng) |
| Ngưỡng chỉnh vừa khít 12 tháng này | Ghi rõ là hiệu chuẩn trên dummy; nêu cần chỉnh lại với dữ liệu thật |
| `gpt-5.6-luna` viết văn xuôi kèm số bịa | Đó là lý do có `fidelity.py`. Bắt được thì báo cáo, đừng đổi model để giấu |
| Gateway chết lúc 2 giờ sáng | Retry rồi bỏ; gửi findings dạng bảng không có narration còn hơn không gửi |

---

## 8. Điều cần chốt

Kênh gửi. Tôi **mặc định làm file + adapter Slack**, không chờ. Nếu có webhook Slack
thật cho một channel nào đó thì đưa tôi, tôi bật lên và demo đúng vế "designated team
channel" của đề bài. Không có cũng không ảnh hưởng phần còn lại.
