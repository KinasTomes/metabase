# Sprint 2 — dàn ý trình bày

Khoảng 20 phút nói + 10 phút hỏi. Thứ tự dưới đây đi từ "cái gì chạy được" tới
"vì sao làm thế" rồi "cái gì chưa xong" — phần cuối đừng bỏ, nó là phần người
review tin bạn nhất.

Trước khi trình bày: chạy `run_acceptance.py` và `run_hard_questions.py` để có số
mới. Slide 5 hiện đang thiếu số, đừng dùng số cũ 13/13 vì bề mặt đã đổi.

---

## 1. Mở đầu — vấn đề, một câu (1 phút)

> Quản lý nghiệp vụ cần số liệu, phải chờ engineer viết query. Mục tiêu: hỏi
> bằng tiếng Việt, nhận về số đúng — hoặc nhận về lý do rõ ràng vì sao không có số.

Nhấn ngay vế thứ hai. Nó là điểm phân biệt hệ thống này với một con chatbot biết
sinh SQL, và là phần tốn nhiều công nhất của sprint.

## 2. Demo trực tiếp (4 phút) — làm trước, giải thích sau

Ba câu, theo đúng thứ tự này:

1. **"Doanh thu GSM theo tháng"** — ra biểu đồ ngay. Thiết lập lòng tin.
2. **"Có bao nhiêu khách hàng dùng cả GSM và VinFast?"** — cross-unit, ra 1.400.
   Chỉ vào chỗ nó tự giải thích *"mỗi người một dòng, unique theo
   global_customer_id, nên mỗi khách được đếm đúng một lần"*.
3. **"Số giao dịch bị hủy của GSM theo tỉnh?"** — **nó từ chối**, và nêu đúng lý do.

Câu 3 là điểm nhấn của cả buổi. Đừng vội chuyển slide, để người xem đọc hết câu
trả lời.

> Dự phòng: quota gateway có thể hết giữa demo. Chuẩn bị sẵn ảnh chụp cả ba câu.

## 3. Yêu cầu Sprint 2, đối chiếu thẳng (2 phút)

| Yêu cầu | Trạng thái |
| --- | --- |
| Chat interface cho stakeholder | xong, chạy trên trình duyệt |
| Trả về bảng / biểu đồ | xong |
| Câu hỏi nhiều business unit | xong, có số đối chiếu |
| Complex joins across entities | **hạ tầng xong, chưa đo** |

Nói thẳng ô cuối. Nếu bị hỏi trước khi bạn kịp nói, bạn mất thế chủ động.

## 4. Kiến trúc (4 phút) — ba quyết định, không phải sơ đồ đầy đủ

Vẽ một hình đơn giản: người dùng → Metabase/MetaBot → LLM, và Metabase → warehouse
qua role chỉ đọc. Rồi nói ba điều:

**a) Sinh MBQL, không sinh SQL thô.** Truy vấn có cấu trúc, biên dịch xuống SQL.
Đổi lại: không injection, sai thì fail lúc dựng, và phân quyền được ép ở tầng
Postgres — MetaBot có cố trỏ vào `silver` cũng bị từ chối.

**b) Không sửa prompt, chỉ sửa metadata.** POC không có license `:ai-controls` nên
system prompt bất khả xâm phạm. Hoá ra là may: mọi tri thức nghiệp vụ buộc phải nằm
trong `COMMENT ON` của cột, và điều đó tự động đúng cho mọi công cụ khác đọc
warehouse, không chỉ cho con bot này.

Bằng chứng: MetaBot **tự** cảnh báo doanh thu VinFast bằng 0 và dữ liệu chỉ có 2025,
không ai nhắc. Đây là lý do bỏ hẳn hướng sửa prompt.

**c) Ranh giới catalogue / executable fact.** Xem slide 6.

## 5. Đo lường (3 phút)

Điểm mấu chốt về phương pháp: **chấm bằng cách chạy truy vấn mà bot dựng ra**, không
chấm văn bản. Câu trả lời nghe hợp lý mà không có truy vấn phía sau bị đánh
`NO_QUERY`, không phải PASS.

| Bộ | Số câu | Đo cái gì | Kết quả 2026-08-13 |
| --- | ---: | --- | --- |
| `run_acceptance.py` | 16 | số có đúng không | **16/16 PASS** |
| `run_hard_questions.py` | 9 | khi không có đáp án, nó nêu giới hạn hay bịa | 5/9 GOOD (đọc tay: 6/9) |

Nói rõ vì sao thêm câu 14–16: bộ 13 câu cũ **đều trả lời được từ một bảng**, nên
13/13 không chứng minh được gì về join. Ba câu mới nhóm theo cột chỉ có trong
dimension nên join là bắt buộc.

Câu 16 là câu bẫy: `dim_customer` có grain `(customer_id, pnl)`, join thiếu `pnl` sẽ
**nhân đôi mọi con số**. Tổng ba nhóm phải bằng đúng đáp án câu 1 — kiểm được cả
fan-out lẫn giá trị. Cả ba câu join đều PASS, nên ô "chưa đo" ở slide 3 đã đóng.

### Phần thú vị hơn con số 16/16 (dành 1 phút cho slide này)

Bộ câu khó **tụt từ 8/8 xuống 5/9** đúng lúc bề mặt mở từ 2 bảng lên 6. Đọc tay
từng câu thì:

- **H1, H3 thoái lui thật.** H1 lọc `product = vehicle` cho GSM (ra 0) rồi gọi đó là
  "số xe GSM bán được"; H3 lấy "tháng này" = 8/2026 (ra 0) mà không nhắc dữ liệu
  dừng ở 2025-12. Trước đó nó bắt được cả hai.
- **H5 là câu hỏi hỏng, không phải model hỏng.** Bẫy cũ là mơ hồ giữa hai cách đếm
  khách; `dim_global_customer` mà mình thêm vào đã xoá bẫy đó. Phải viết lại câu hỏi.
- **H9 thực chất đạt**, chỉ là regex không bắt.

Kết luận nên nói thẳng: **độ chính xác không giảm, tính thận trọng thì có.** Bề mặt
rộng ra làm loãng tác dụng của column comment — 68 field thay vì 20, model có nhiều
chỗ hơn để tìm một con số nghe hợp lý. Đây là đánh đổi cần đo tiếp, không phải thứ
vá bằng một dòng comment.

Đây là slide thể hiện rõ nhất rằng bộ đo đang làm đúng việc của nó: nếu chỉ nhìn
16/16 thì sẽ tưởng mọi thứ đều tốt lên.

## 6. Điểm nhấn kỹ thuật — vì sao bot từ chối đúng cách (4 phút)

Đây là phần đáng kể nhất, kể như một câu chuyện có khúc mắc.

**Bối cảnh.** Feature store có 34 feature, trong đó 14 feature đếm giao dịch bị hủy,
kèm giá trị thật trong serving.

**Cái bẫy.** `cancelled` là business status **đã được mentor duyệt** — nó có thật.
Nhưng `data_contract.json` ép `transactions.status` chỉ nhận `completed`, nên **chưa
có fact hủy nào được nạp**. Vậy cả hai câu trả lời hiển nhiên đều sai:

- *"Không có giao dịch hủy"* → phủ nhận một status đã duyệt.
- *"7.712 giao dịch"* → báo cáo snapshot chưa reconcile như thể là fact.

**Sai lầm đầu tiên của chúng tôi.** Bản đầu pivot cả 34 feature thành cột, rồi *mô tả*
mâu thuẫn trong phần comment. Nhưng mô tả cái bẫy không phải là đóng nó lại — cột vẫn
truy vấn được, bot vẫn trả 7.712.

**Cách sửa.** Tách bề mặt bằng **cấu trúc**:

- `fact_customer_features` — 20 feature servable, có cột.
- `dim_feature_catalogue` — đủ 34, kèm `serving_status` và `not_servable_reason`.

Lý do từ chối trở thành **dữ liệu để trích dẫn**, không phải câu bot tự nghĩ ra.

**Kết quả.** Bot tìm tới catalogue, trích `catalogue_only`, nêu đúng ràng buộc data
contract, không trả số nào. Chiếu nguyên văn câu trả lời.

**Bài học một câu:** ranh giới governance phải là cấu trúc, không phải văn bản.

## 7. Những cái đã cắn (2 phút) — chọn hai, đừng kể hết

Chọn theo khán giả:

- **CRLF làm trắng trang.** Server hash bytes file, trình duyệt hash nội dung sau khi
  parser chuẩn hoá CRLF→LF, CSP chặn sạch script inline. Không request nào lỗi, không
  log nào báo. Bài học thật: mọi test đều gọi API, chưa từng render HTML, nên lỗi này
  vô hình suốt nhiều ngày "xanh".
- **Timezone.** `::DATE` trên `TIMESTAMPTZ` resolve theo session zone; dưới
  `America/Los_Angeles` ra **13 bucket tháng**. Giờ ghim `AT TIME ZONE 'UTC'`.
- **Test bảo mật suýt cho kết quả ngược.** `psql -h 127.0.0.1` khớp dòng `trust` trong
  `pg_hba.conf` **trước** dòng scram, nên báo thành công dù mật khẩu sai. Phải test
  qua đúng đường mạng client thật dùng.

## 8. Còn thiếu và bước tiếp (2 phút)

Nói chủ động, đừng đợi bị hỏi:

- **Chưa chạy lại baseline** sau khi bề mặt đổi từ 2 lên 6 bảng.
- **Câu 14–16 chưa chạy** → khả năng join chưa có bằng chứng.
- H9 mới chạy tay một lần; hành vi LLM dao động giữa các lần chạy.
- Chấm bằng regex là thô. Muốn đo nghiêm túc cần LLM-judge hoặc chấm tay có rubric.
- Sprint 3 (quét chủ động hằng đêm, đẩy summary lên kênh) chưa bắt đầu.

## 9. Chốt (1 phút)

> Phần khó của sprint này không phải sinh SQL — Metabase lo. Phần khó là dạy hệ
> thống biết **khi nào không được trả lời**, và làm sao để điều đó là một thuộc tính
> của cấu trúc dữ liệu chứ không phải một câu dặn dò trong prompt.

---

## Câu hỏi có thể bị vặn

**"Sao không tự viết agent mà dùng Metabase?"**
Được phân quyền, render, và lịch sử truy vấn miễn phí. Nếu tự viết, ba thứ đó là
công việc của cả sprint, mà không phải phần đề bài đánh giá.

**"Không có license thì có phải hạn chế lớn không?"**
Nó chặn việc sửa system prompt. Nhưng đo rồi: với dữ liệu này, tầng ngữ nghĩa ăn đứt
prompt engineering. Và metadata thì dùng chung được cho mọi công cụ, prompt thì không.

**"Sao dám chắc con số đúng?"**
Không chấm văn bản. Lấy truy vấn bot dựng, chạy thật, so với ground truth tính độc
lập bằng SQL. Câu 14–16 còn kiểm tổng các nhóm phải khớp đáp án câu 1.

**"Nếu người dùng cứ đòi số giao dịch hủy thì sao?"**
Bot nêu lý do và đề xuất thứ trả lời được. Muốn có số thật thì phải nạp fact hủy và
reconcile — đó là việc của pipeline, không phải của bot.

**"Còn dữ liệu thật, quy mô lớn hơn thì sao?"**
Chưa đo. Feature store hiện 200 khách × 12 tháng. Việc pivot 34 feature là view chứ
không materialize, nên số cột tăng sẽ là chỗ cần xem lại trước tiên.
