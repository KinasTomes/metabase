# MetaBot POC warehouse

PostgreSQL warehouse chứa dữ liệu BI cho POC, tách hoàn toàn khỏi application
database của Metabase.

## Nội dung

| File | Vai trò |
| --- | --- |
| `sql/01_init_bronze_silver_gold.sql` | DDL Bronze/Silver/Gold từ project BI cũ, bỏ dòng `CREATE EXTENSION vector` |
| `sql/04_init_analytics_views.sql` | View `analytics` cho Metabase — **mới**, thay bản monthly-aggregate cũ |
| `load_warehouse.py` | Chạy DDL, nạp CSV, tạo login read-only |

## Tại sao view khác bản cũ

Bản cũ (`04_init_metabase_views.sql`) chỉ có hai view đã aggregate tới grain
tháng × company. Bộ câu hỏi demo hỏi theo tỉnh, sản phẩm và tên sự kiện —
những dimension đó bị mất khi lên Gold, nên chỉ 5/13 câu trả lời được.

Bản mới đọc thẳng từ Silver ở grain giao dịch và event:

| View | Grain | Dòng |
| --- | --- | ---: |
| `analytics.fact_transactions` | 1 giao dịch | 31.685 |
| `analytics.fact_events` | 1 event | 40.000 |

MetaBot tự viết `GROUP BY`, nên fact-grain hợp hơn pre-aggregate. Số liệu không
lệch: doanh thu theo tháng tính từ view mới trùng khít `gold.gold_monthly_pnl`.

Bronze không được nạp — nó gần như trùng Silver và không có consumer nào.

### Múi giờ

`transaction_date` và `event_date` trong Silver là `TIMESTAMPTZ` lưu ở nửa đêm
UTC. `::DATE` và `TO_CHAR()` trần sẽ quy đổi theo session timezone, nên mọi
connection ở phía tây UTC bị lùi một ngày — đã đo được: dưới
`America/Los_Angeles`, bản chưa sửa cho ra **13** tháng và đẩy 59 event ngược
sang `2024-12`. Metabase set session timezone theo report-timezone của nó, nên
cả hai view ghim cứng `AT TIME ZONE 'UTC'`. Đã verify ổn định từ UTC-11 tới
UTC+7.

## Mô hình phân quyền

Metabase **không** kết nối bằng superuser. `load_warehouse.py` tạo role
`metabase_reader` chỉ có `SELECT` trên schema `analytics`, `search_path` ghim
vào `analytics`.

Đã kiểm chứng bằng cách kết nối trực tiếp bằng role này:

| Thao tác | Kết quả |
| --- | --- |
| `SELECT` trên `fact_transactions` (không qualify) | 31.685 dòng |
| `SELECT` trên `silver.transactions` | `permission denied for schema silver` |
| `SELECT` trên `gold.gold_monthly_pnl` | `permission denied for schema gold` |
| `SELECT` trên `bronze.transactions` | `permission denied for schema bronze` |
| `CREATE TABLE` trong `analytics` | `permission denied for schema analytics` |
| Schema nhìn thấy được | chỉ `analytics`, đúng 2 bảng |

## Chạy lần đầu

Cần `local-context/data/pipeline/` (untracked) và `psycopg2`.

```powershell
Copy-Item dev\metabot-poc\.env.example dev\metabot-poc\.env
```

Đặt `WAREHOUSE_PASSWORD` và `WAREHOUSE_READER_PASSWORD` trong `.env`, rồi bật
warehouse:

```powershell
docker compose --env-file dev\metabot-poc\.env -f dev\metabot-poc\compose.yml up -d warehouse
```

Nạp dữ liệu từ host:

```powershell
$env:WAREHOUSE_PASSWORD = "<mật khẩu vừa đặt>"
$env:WAREHOUSE_READER_PASSWORD = "<mật khẩu reader>"
python dev\metabot-poc\warehouse\load_warehouse.py
```

Kỳ vọng cuối output:

```text
Curated views:
  - analytics.fact_transactions: 31685
  - analytics.fact_events: 40000
```

## Nạp lại

Script `TRUNCATE` trước khi nạp nên chạy lại bao nhiêu lần cũng được. DDL dùng
`CREATE OR REPLACE` / `DROP VIEW IF EXISTS`, sửa view rồi chạy lại là đủ.

## Kết nối từ Metabase

| Trường | Giá trị |
| --- | --- |
| Host | `warehouse` (trong Docker network) hoặc `localhost` từ host |
| Port | `5432` trong network, `5433` từ host |
| Database | `bi_warehouse` |
| Username | `metabase_reader` |
| Schema | chỉ `analytics` hiển thị |

Sau khi kết nối, chạy sync để Metabase đọc comment của view và cột thành field
description — đó là ngữ cảnh MetaBot thực sự nhìn thấy.
