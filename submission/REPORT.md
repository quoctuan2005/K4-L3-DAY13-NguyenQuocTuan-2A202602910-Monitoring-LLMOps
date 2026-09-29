# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Nguyễn Quốc Tuấn
- **MSSV:** 2A202602910
- **Lớp:** K4-L3A
- **Repository URL:** https://github.com/quoctuan2005/K4-L3A-Day13-Monitoring-LLMOps.git
- **Commit SHA cuối:** `a0cb10d2221393ae83b89a1fbf1894de704a0dea` (`a0cb10d`)
- **Challenge ID:** day13-k4-l3a-monitoring-llmops-v1
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602910`

---

## 2. Evidence index

| Evidence | Đường dẫn | Mô tả ngắn |
|---|---|---|
| Pytest cuối | `evidence/01-pytest.png` | Bộ 26/26 unit tests passed 100% |
| Log validator | `evidence/02-log-validator.png` | Kết quả validate_logs.py đạt 100/100 |
| Dashboard validator | `evidence/03-dashboard-validator.png` | Kết quả validate_dashboard.py đạt 6/6 panels |
| Structured log | `evidence/04-structured-log.png` | Format JSON log có timestamp, event, correlation_id, model, env, feature, latency |
| PII redaction | `evidence/05-pii-redaction.png` | Che toàn diện Email, SĐT VN, CCCD 12 số, Thẻ tín dụng 16 số |
| Trace list | `evidence/06-trace-list.png` | Danh sách traces trong project cá nhân day13-k4-l3a-2A202602910 |
| Trace waterfall | `evidence/07-trace-waterfall.png` | Cây trace phân cấp: root span lab-agent-run -> retrieval -> generation |
| Trace metadata | `evidence/08-trace-metadata.png` | Metadata chi tiết của trace: correlation_id, model, feature, prompt version/label |
| Prompt versions | `evidence/09-prompt-versions.png` | Quản lý prompt day13-chat với version 1 (production, baseline) và version 2 (candidate) |
| Prompt rollback | `evidence/10-prompt-rollback.png` | Giao diện promote/rollback production label an toàn trên Langfuse |
| Dashboard runtime | `evidence/11-dashboard-overview.png` | Giao diện Dashboard 6 panel runtime theo thiết kế Steep warm paper |
| Incident metric | `evidence/12-incident-metric.png` | Đột biến P95 Latency tăng vọt lên 2889 ms (vượt ngưỡng 2000 ms) |
| Incident log | `evidence/13-incident-log.png` | Log line bất thường req-7a933bea có latency_ms: 2672, feature: monitoring |
| Incident trace | `evidence/14-incident-trace.png` | Trace 5c3ad96f3c12cb027c78f5f605f986a9 có span retrieval chiếm 2.50s (94% latency) |

---

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | **100/100** | Đạt điểm tối đa sau khi bổ sung middleware correlation ID, structlog event, metadata và scrub PII |
| `validate_dashboard.py` | 0/6 panels | **6/6 panels** | Hoàn thành đủ 6 panels: Latency, Traffic, Error rate, Cost, Token, Quality |
| `pytest` | 24 passed | **26 passed** | Vượt baseline nhờ viết thêm 2 unit tests kiểm thử CCCD và thẻ ngân hàng |
| Số traces hợp lệ | 0 traces | **> 35 traces** | Tất cả traces được gửi về project cá nhân `day13-k4-l3a-2A202602910` |
| Số PII leak | 4 rò rỉ (email, phone) | **0 rò rỉ** | Redact thành công Email, SĐT VN, CCCD 12 số, Thẻ tín dụng 16 số, Hash SHA-256 user_id |
| Latency P95 / TTFT P95 | ~120 ms / 50 ms | **132 ms / 55 ms** *(bình thường)*<br>**2889 ms / 55 ms** *(lúc incident)* | Hệ thống ghi nhận chính xác tail latency và bắt trọn sự cố trong đợt challenge |
| Retrieval success rate | 100% | **100.0%** | Tỷ lệ thành công của tool retrieval được theo dõi liên tục |

---

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:**
  - Được triển khai thông qua custom middleware tại `app/middleware.py`.
  - Middleware kiểm tra header incoming `x-request-id`. Nếu client gửi lên, hệ thống sẽ tái sử dụng ID đó; nếu không có hoặc không hợp lệ, middleware sẽ tự động tạo correlation ID theo chuẩn `req-<8-hex>` (ví dụ: `req-7a933bea`).
  - Correlation ID được bind vào ContextVar của `structlog` (`structlog.contextvars.bind_contextvars(correlation_id=corr_id)`), giúp mọi log sinh ra trong suốt vòng đời xử lý request đều mang chung ID này.
  - Cuối request, middleware đính kèm ngược lại vào response headers: `x-request-id` và `x-response-time-ms`. Trước khi kết thúc request, ContextVar được dọn dẹp sạch sẽ để chống leak giữa các request concurrent (`structlog.contextvars.clear_contextvars()`).

- **Các metadata được ghi vào structured log:**
  - Mỗi log event dạng JSON bao gồm: `ts` (ISO-8601 UTC), `level`, `event` (`request_received`, `response_sent`), `correlation_id`, `service` (`api`), `env` (`dev`/`prod`), `model` (`claude-sonnet-4-5`), `feature` (`qa`, `monitoring`,...), `session_id`, `user_id_hash` (chuỗi 12-hex hash SHA-256 của user ID gốc), `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`.

- **Cách bảo đảm PII được scrub trước khi ghi:**
  - Tách bạch logic xử lý PII trong `app/pii.py` với các regex chuẩn xác cho 4 loại dữ liệu nhạy cảm:
    1. Email: `REDACTED_EMAIL`
    2. Số điện thoại Việt Nam (các đầu số 03, 05, 07, 08, 09 hoặc +84): `REDACTED_PHONE_VN`
    3. Căn cước công dân (12 chữ số): `REDACTED_CCCD`
    4. Số thẻ tín dụng / thanh toán (16 chữ số, có phân tách bởi dấu cách hoặc gạch ngang): `REDACTED_CREDIT_CARD`
  - Trong `app/logging_config.py`, một processor chuyên dụng `scrub_event` được cắm vào pipeline của `structlog` **ngay trước bước serialize JSON**. Processor này đệ quy duyệt qua tất cả key-value trong event dictionary và thực hiện scrub text, bảo đảm không có bất kỳ PII thô nào lọt vào log storage hay stream stdout.

- **Cách kiểm chứng kết quả:**
  - Chạy `python3 scripts/validate_logs.py` đạt **100/100 points**.
  - Chạy `pytest tests/test_pii.py` với bộ unit test toàn diện cho cả 4 rule redact và kiểm tra che PII trong prompt preview.

---

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
  - Toàn bộ trace được gửi trực tiếp lên Langfuse Cloud với API credentials cá nhân trong `.env` trỏ vào project riêng: `day13-k4-l3a-2A202602910`.
  - Trên màn hình Langfuse (ảnh `06-trace-list.png`), hiển thị rõ ràng định danh project `day13-k4-l3a-2A202602910` cùng danh sách hơn 35 traces do chính workload của tôi tạo ra.

- **Cấu trúc root/retrieval/generation observations:**
  - Cây trace được thiết kế chuẩn cấu trúc phân cấp (Parent - Child hierarchy) thông qua Langfuse v4 SDK:
    - **Root Span:** `lab-agent-run` (type: `agent`) ghi nhận toàn bộ vòng đời tác vụ của agent, thời gian tổng, tags (`lab`, feature, model), environment.
    - **Child Span 1 (Retriever):** `retrieval` (type: `retriever`) đo lường bước vector search/tài liệu ngữ cảnh, ghi nhận `doc_count` và latency truy xuất.
    - **Child Span 2 (Generation):** `generation` (type: `generation`) đo lường bước sinh câu trả lời của mô hình LLM, ghi nhận số lượng input/output tokens, calculated cost USD, model parameter, và liên kết trực tiếp với Langfuse Prompt version.

- **Cách nối trace với log:**
  - Cả log và trace đều chia sẻ chung một trường metadata `correlation_id` (ví dụ `req-7a933bea`).
  - Trong log: trường `correlation_id` nằm ở top-level JSON.
  - Trong trace: được truyền thông qua `propagate_attributes(metadata={"correlation_id": correlation_id, "feature": feature, "model": self.model})` và hiển thị trên tab Metadata của Langfuse.

- **Prompt name:** `day13-chat`
- **Version/label baseline:** Version 1 mang label `baseline` và `production`.
- **Version/label candidate:** Version 2 mang label `candidate` và `latest`.
- **Trace ID của mỗi version:**
  - Trace ID chạy với Version 1 (`production`): `593d17be8e17f320d6a7caf2f8155a4e` (hoặc `48b774dfd34c1cb41785f8382c733f38`).
  - Trace ID chạy với Version 2 (`candidate`): `0e0cbfae829375498877bc95679dc6db`.
- **Cách promote và rollback `production`:**
  - Trong file `app/prompt_management.py`, hàm `resolve_prompt` gọi `langfuse_client.get_prompt("day13-chat", label="production")`.
  - Trên giao diện Langfuse Prompt Management:
    - **Promote:** Chọn prompt v2, mở modal gán label và tick chọn `production` ➔ Lưu. Khi đó ứng dụng ngay lập tức kéo v2 về chạy mà không cần sửa code hay redeploy server.
    - **Rollback:** Khi phát hiện v2 gặp lỗi hoặc chi phí cao, chọn lại v1, gán lại label `production` ➔ Lưu. Ngay lập tức hệ thống hoàn nguyên về phiên bản v1 ổn định.

---

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
  - Dashboard được xây dựng tại `/dashboard` theo phong cách thiết kế hiện đại Steep warm paper, phục vụ đầy đủ 6 khía cạnh observability của AI Agent:
    1. **Panel 01 • Latency & TTFT:** P50, P95, P99 tail latency và TTFT P95 kèm sparkline trực quan.
    2. **Panel 02 • Traffic Throughput:** Tổng số request received, request throughput tính theo rpm (rolling 60m).
    3. **Panel 03 • Reliability & Retrieval:** Error rate (tỷ lệ lỗi 5xx/failures) và tỷ lệ thành công của retrieval tool.
    4. **Panel 04 • Expenditure (Cost):** Tổng chi phí USD tích lũy trong cửa sổ quan sát so với hạn mức ngân sách.
    5. **Panel 05 • Quotas (Token Usage):** Tổng tokens, tỷ lệ phân bổ prompt tokens in vs completion tokens out.
    6. **Panel 06 • Quality Evaluation:** Điểm chất lượng trung bình (quality proxy score) kết hợp kiểm tra rò rỉ dữ liệu.

- **SLO và lý do chọn:**
  - Dựa trên file cấu hình `config/slo.yaml`:
    - **Latency SLO:** `P95 latency <= 3000 ms` — Đảm bảo trải nghiệm tương tác thời gian thực của người dùng không bị nghẽn.
    - **Reliability SLO:** `Error rate <= 2.0%` — Đảm bảo tính khả dụng cao của API backend.
    - **Tool SLO:** `Retrieval success rate >= 95.0%` — Đảm bảo agent luôn truy xuất được tri thức RAG trước khi sinh câu trả lời.

- **Cách tính error budget:**
  - Error budget = `100% - SLO Target`.
  - Ví dụ với độ khả dụng: SLO là 98.0% thành công thì Error Budget cho phép là 2.0% tổng số request trong cửa sổ 60 phút. Nếu trong 1000 request có hơn 20 request lỗi, error budget bị cạn kiệt (burn-rate cao), kích hoạt cảnh báo on-call.

- **Ba alert và runbook tương ứng:**
  - Đã cấu hình tại `config/alert_rules.yaml` và tài liệu hóa trong `docs/alerts.md`:
    1. `high_latency_p95`: Cảnh báo khi P95 Latency vượt 2000 ms trong 5 phút. Runbook: Kiểm tra xem nghẽn ở vector DB retrieval hay mô hình LLM thông qua Trace Waterfall.
    2. `high_error_rate`: Cảnh báo khi tỷ lệ lỗi vượt 5.0% trong 5 phút. Runbook: Kiểm tra exception logs, trạng thái HTTP status codes và dependency downstream.
    3. `low_retrieval_success_rate`: Cảnh báo khi tỷ lệ retrieval thành công dưới 90%. Runbook: Kiểm tra kết nối Vector Database, embedding service hoặc index degradation.

---

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3a-monitoring-llmops-v1`
- **Khoảng thời gian điều tra:** 2026-09-29 09:34:00 UTC đến 09:36:15 UTC (tức 16:34:00 đến 16:36:15 giờ Việt Nam).
- **Triệu chứng từ metrics (`evidence/12-incident-metric.png`):**
  - Panel Latency trên Dashboard ghi nhận **P95 Latency tăng vọt lên 2889 ms** (vượt xa ngưỡng cảnh báo 2000 ms của challenge).
- **Log line và correlation ID liên quan (`evidence/13-incident-log.png`):**
  - Correlation ID: `req-7a933bea`
  - Trích xuất JSON Log:
    ```json
    {
      "service": "api",
      "latency_ms": 2672,
      "ttft_ms": 55,
      "tokens_in": 35,
      "tokens_out": 174,
      "cost_usd": 0.002715,
      "quality_score": 0.8,
      "tool_name": "retrieval",
      "tool_success": true,
      "event": "response_sent",
      "feature": "monitoring",
      "session_id": "k4-l3a-challenge-s03",
      "model": "claude-sonnet-4-5",
      "user_id_hash": "dc9b2ec8da9d",
      "correlation_id": "req-7a933bea",
      "env": "dev",
      "level": "info",
      "ts": "2026-09-29T09:36:04.039810Z"
    }
    ```
- **Trace ID và span gây ảnh hưởng (`evidence/14-incident-trace.png`):**
  - Trace ID trên Langfuse Cloud: `5c3ad96f3c12cb027c78f5f605f986a9`.
  - Phân tích Waterfall:
    - Root span `lab-agent-run`: tổng thời gian **2.67s**.
    - Span con `retrieval`: tiêu tốn **2.50s** (chiếm ~94% tổng latency của request).
    - Span con `generation`: chỉ tiêu tốn **0.16s** (hoàn toàn bình thường).
- **Root cause:**
  - Sự cố bắt nguồn từ module truy xuất tài liệu RAG (`retrieval`) bị trễ nghiêm trọng (mô phỏng injection delay 2.5s vào vector retrieval). Nút thắt không nằm ở LLM provider hay mạng bên ngoài mà nằm hoàn toàn tại tầng Vector DB / Data Retrieval.
- **Fix action:**
  - Tắt kịch bản sự cố thông qua lệnh: `python3 scripts/inject_incident.py --disable`. Trong môi trường thực tế: scale-up cluster Vector Database, bổ sung Redis cache cho các vector query phổ biến hoặc điều chỉnh search timeout fallback.
- **Preventive measure:**
  - Thiết lập timeout nghiêm ngặt cho span retrieval (ví dụ 800ms) kèm circuit breaker; nếu vector search quá hạn sẽ tự động fallback sang lexical search (BM25) để bảo vệ trải nghiệm của người dùng và giữ P95 dưới ngưỡng SLO.

---

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
  - **Quyết định:** Sử dụng Structlog contextvars kết hợp Processor đệ quy để scrub PII tự động trước khi serialize JSON, thay vì gọi hàm scrub thủ công tại từng nơi ghi log.
  - **Lý do:** Cách làm này ngăn chặn triệt để lỗi bất cẩn từ phía lập trình viên (human error). Dù developer có truyền bất kỳ trường thông tin nào vào log, processor tập trung sẽ tự động kiểm tra và che PII trước khi ghi ra file, bảo đảm tuân thủ luật bảo vệ dữ liệu (GDPR/Nghị định 13) mà không làm ô nhiễm business logic của agent.

- **Một lỗi/blocker đã gặp:**
  - Khi nâng cấp mã nguồn tích hợp Langfuse Python SDK v4, endpoint lấy danh sách trace cũ (`/api/public/traces`) trả về HTTP 410 Gone (Deprecated) và cấu trúc khởi tạo OpenTelemetry tracer khác biệt so với SDK v3.

- **Cách tìm nguyên nhân và xử lý:**
  - Đọc kỹ tài liệu di chuyển SDK v4 của Langfuse, chuyển sang dùng `get_client()` với decorator `@observe()` và truy xuất quan sát thông qua client v4 `lf.api.observations.get_many()`. Đảm bảo tương thích hoàn toàn cho cả môi trường có và không có Langfuse SDK thông qua adapter fallback an toàn.

- **Cách hiểu luồng Metrics → Logs → Traces:**
  - **Metrics (Triệu chứng - WHAT & WHEN):** Dashboard hiển thị P95 tăng vọt giúp ta biết ngay hệ thống đang bị đau ở đâu và vào thời điểm nào mà không cần đọc từng dòng dữ liệu.
  - **Logs (Bối cảnh - WHICH):** Dựa vào mốc thời gian từ metric, ta tra cứu logs để tìm ra request cụ thể bị ảnh hưởng (`correlation_id`, user, feature, error message).
  - **Traces (Nguyên nhân gốc rễ - WHY):** Dùng `correlation_id` mở Trace Waterfall để mổ xẻ từng span thành phần (retrieval vs generation vs tool), chỉ mặt điểm tên chính xác dòng code hoặc dịch vụ downstream nào đang làm chậm hệ thống.

- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - Prompt là "code mới" trong kỷ nguyên AI. Việc quản trị version và label (`production`, `candidate`) cho phép đội ngũ phát triển thực hiện A/B testing, rollout từng phần và đặc biệt là **Rollback tức thì** khi prompt mới gây hallucination hoặc tăng đột biến token/cost mà không cần build lại container. SLO và token/cost tracking là kim chỉ nam tài chính và chất lượng để quyết định duy trì hay thu hồi một model/prompt trên production.

- **Điều quan trọng nhất đã học:**
  - Xây dựng một ứng dụng AI Agent không khó, nhưng để vận hành nó an toàn, minh bạch, kiểm soát được chi phí và có khả năng cứu hộ sự cố trong vài phút thì hệ thống Telemetry (Logging, Tracing, Metrics, PII Redaction) là yếu tố sống còn bắt buộc phải có ngay từ ngày đầu tiên.

- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - Hiện tại telemetry log stream trên dashboard mới được tính toán trực tiếp từ local jsonl file; trong tương lai ở quy mô production lớn cần kết nối với OpenTelemetry Collector và ClickHouse/Prometheus để xử lý hàng triệu requests mỗi phút.

---

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [x] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
