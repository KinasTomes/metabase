# Plan — Phase 3 bằng cách fork

Mục tiêu: tuỳ biến hành vi và cách xưng hô của MetaBot cho ngữ cảnh BI tiếng Việt,
trong điều kiện không có entitlement `:ai-controls`.

## Ranh giới quan trọng — đọc trước khi code

Có **hai** cách đạt được "custom system prompt", và chúng khác nhau về bản chất:

| Cách | Bản chất | Làm hay không |
| --- | --- | --- |
| Sửa file `.selmer` trong `resources/metabot/prompts/` | Sửa code OSS trong fork của mình | **Làm** |
| Gỡ `:feature :ai-controls` khỏi `defsetting` | Vô hiệu hoá license check để mở tính năng trả phí | **Không làm** |

Cả hai đều ra kết quả giống nhau trên màn hình, nhưng cách thứ hai là qua mặt cơ
chế cấp phép thương mại của Metabase. Plan này chỉ dùng cách thứ nhất.

Sửa template cũng hợp lý hơn về mặt kỹ thuật cho một fork: setting sinh ra để cấu
hình lúc chạy, còn fork thì muốn đổi mặc định lúc build.

## Bản đồ code (đã verify)

**Nơi lắp ráp prompt** — `src/metabase/metabot/agent/prompts.clj:150-192`

```
template-name  = profile :prompt-template, mặc định "internal.selmer"
template       = get-cached-system-prompt → load-resource
                 "metabot/prompts/system/<tên>"
render         = Selmer, context gồm:
                   metabot_name        ← metabot-name        (bị :ai-controls khoá)
                   custom_instructions ← *-system-prompt     (bị :ai-controls khoá)
                   skill_catalog, skill_always_on
                   has_sql_generation / has_nlq / has_query_tools / has_other_tools
                   sql_dialect, sql_dialect_loaded
```

Hai biến bị khoá chỉ là **đầu vào** của template. Template thì không bị khoá gì cả.

**Template chính** — `resources/metabot/prompts/system/internal.selmer` (62 dòng),
lắp từ các mảnh trong `resources/metabot/prompts/shared/prompt_snippets/`:

| Snippet | Dòng | Nội dung |
| --- | ---: | --- |
| `personality.selmer` | 10 | giọng điệu |
| `communication.selmer` | 5 | cách trình bày câu trả lời |
| `grounding.selmer` | 35 | bắt buộc kiểm chứng giá trị trước khi filter |
| `data-sources.selmer` | 19 | chọn nguồn: metric / model / table |
| `discovery.selmer` | 29 | chiến lược search |
| `mbql-shape.selmer` | 27 | hình dạng MBQL |
| `field-references.selmer` | 9 | cách tham chiếu field |
| `banned-patterns.selmer` | 12 | những thứ cấm làm |

Các template hệ thống khác cùng thư mục: `natural-language-querying-only`,
`natural-language-querying-fallback`, `sql-querying-only` (357+ dòng),
`embedding-next`, `explorations`, `slackbot`.

Chỗ chèn custom instructions có sẵn trong mọi template:
`{% if custom_instructions %}...{{ custom_instructions|safe }}{% endif %}`
— khi không có license thì biến này luôn nil, nên khối đó không bao giờ render.

## Vòng lặp iterate — không cần rebuild 17 phút

Template nằm trong uberjar tại `metabot/prompts/system/internal.selmer`
(đã verify bằng cách đọc jar từ container đang chạy). `java -jar` bỏ qua `-cp`
nên không chèn được thư mục resource từ ngoài, nhưng patch thẳng vào jar thì được:

1. Sửa file trong `resources/metabot/prompts/`
2. `docker cp` jar ra host
3. Ghi lại jar bằng Python `zipfile`, thay entry tương ứng (jar ~709 MB, mất ~30–60 giây)
4. `docker cp` trả lại container, `docker restart`

Tổng khoảng 1–2 phút một vòng, thay vì 17 phút. Nên viết thành
`dev/metabot-poc/patch_prompts.py`.

Cảnh báo: `get-cached-system-prompt` có cache, nên **phải restart container**, reload
không đủ.

## Các bước

### Bước 1 — Dựng công cụ iterate — XONG

`patch_prompts.py` đã có. Vòng lặp mất ~70 giây (rewrite jar 66s + restart).

```powershell
python dev\metabot-poc\patch_prompts.py --dry-run           # xem gì khác
python dev\metabot-poc\patch_prompts.py --only personality  # patch có chọn lọc
python dev\metabot-poc\patch_prompts.py --restore           # về jar gốc
```

**Phát hiện chặn đường: image đang chạy không build từ HEAD.** Nó cũ hơn commit
`62cdfb57c2`; 10 template khác với working tree, và `explorations.selmer` chưa hề
tồn tại trong jar. Patch bừa từ tree sẽ kéo theo thay đổi upstream không liên quan,
và nguy hiểm hơn — template mới có thể tham chiếu biến render-context mà
`prompts.clj` cũ trong jar không cung cấp. Tool mặc định **từ chối** patch khi thấy
nhiều file lệch; phải dùng `--only`.

Trước khi làm bước 3 nên **rebuild image từ master** để tree và jar khớp nhau. Không
rebuild thì mọi chỉnh sửa prompt đều phải patch từng file một qua `--only`, và luôn
có rủi ro lệch phiên bản giữa template và code.

**Cách verify đã dùng:** cắm marker vào prompt rồi hỏi model thì *không* kết luận
được — model bỏ qua chỉ thị mềm, kể cả `MANDATORY: begin every reply with...`. Cách
chứng minh được: đặt cú pháp Selmer sai rồi xem `selmer.parser$render` nổ trong
server log. Build production không lưu prompt đã render và `debug` bị gate bởi
`config/is-dev?`, nên đây là bằng chứng khả dụng duy nhất.

Điều này cũng là dữ kiện cho bước 3: `qmodel_38max` phớt lờ chỉ thị mềm trong khối
personality. Đừng kỳ vọng nhiều vào prompt engineering với model này.

### Bước 2 — Chụp baseline
Chạy acceptance suite 3 lượt với template gốc, ghi lại tỉ lệ pass từng câu. Không có
baseline thì không biết thay đổi prompt làm tốt lên hay xấu đi — đây chính là sai lầm
đã mắc khi thêm metric (xem `NEXT_STEPS.md` hướng 3).

### Bước 3 — Tuỳ biến cho ngữ cảnh BI tiếng Việt
Sửa `internal.selmer` và/hoặc các snippet để đưa vào:

- Bối cảnh nghiệp vụ: GSM và VinFast là hai công ty, dữ liệu chỉ 2025.
- Cảnh báo doanh thu VinFast bằng 0 — hiện MetaBot tự phát hiện nhờ `COMMENT ON`,
  nhưng đưa vào prompt thì chắc chắn hơn.
- Quy ước trả lời bằng tiếng Việt khi người dùng hỏi tiếng Việt.
- Ưu tiên metric trong collection `BI Analytics` hơn là tự aggregate view thô.

Mỗi thay đổi một lần, đo lại, giữ nếu tốt lên.

### Bước 4 — Branding
`{{metabot_name}}` lấy từ setting bị khoá nên luôn ra "Metabot". Đổi tên hiển thị thì
sửa giá trị `:default` của `defsetting metabot-name` trong
`src/metabase/metabot/settings.clj:29` — đổi mặc định, không đụng `:feature`.

Việc này cần rebuild thật vì là code Clojure, không phải resource.

### Bước 5 — Đo lại và ghi chép
Chạy suite 3 lượt với template đã sửa, so với baseline bước 2. Ghi kết quả vào
`ACCEPTANCE_REPORT.md` và cập nhật `METABOT_CUSTOMIZATION_WALKTHROUGH.md`.

## Rủi ro

- **Fork drift**: sửa file trong `resources/` và `src/` sẽ xung đột khi merge upstream.
  Giữ thay đổi càng nhỏ và tập trung càng tốt; ưu tiên sửa snippet thay vì template lớn.
- **Prompt dài hơn = chậm hơn và tốn token hơn**, trên model free thì dễ chạm giới hạn.
  Theo dõi thời gian mỗi câu trong suite.
- **Model hiện tại chập chờn sẵn** (Q11 loop `construct_notebook_query` bốn lần).
  Đừng nhầm nhiễu của model với tác động của prompt — đó là lý do cần 3 lượt, không phải 1.

## Câu cần trả lời khi xong

Prompt tuỳ biến có thực sự cải thiện gì so với việc chỉ dựa vào `COMMENT ON` và metric
không? Nếu không, đó cũng là một kết quả đáng giá: nó nói rằng với dataset này,
semantic layer quan trọng hơn prompt engineering.
