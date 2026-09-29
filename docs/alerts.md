# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1

- Tên: high_latency_p95
- Severity: warning
- Duration: 5m
- Kênh thông báo: Slack (#alerts-day13-monitoring)
- SLI/SLO liên quan: `fast_successful_requests` (SLO 99.5% requests <= 3000ms trong 28 ngày)
- Điều kiện và thời gian duy trì: Latency P95 vượt quá 3000ms liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: Người dùng nhận câu trả lời chậm, trải nghiệm hội thoại bị gián đoạn, nguy cơ timeout client.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel Latency trên dashboard xem P95 và TTFT tăng đột biến từ thời điểm nào.
  2. Lọc `data/logs.jsonl` tìm các request có `latency_ms > 3000` và trích xuất `correlation_id`.
  3. Mở Langfuse tìm trace theo `correlation_id`, kiểm tra span waterfall xem chậm ở child span `retrieval` hay `generation`.
- Mitigation tạm thời: Nếu do retrieval chậm (vector store chậm), chuyển sang chế độ bypass retrieval hoặc fallback cached context; nếu do LLM nghẽn, kiểm tra rate limit hoặc restart service.
- Owner: oncall-engineer

## Alert 2

- Tên: high_error_rate
- Severity: critical
- Duration: 3m
- Kênh thông báo: Slack (#alerts-day13-monitoring)
- SLI/SLO liên quan: Guardrail `error_rate_pct_max: 2` (tỷ lệ lỗi tối đa 2%)
- Điều kiện và thời gian duy trì: Tỷ lệ request thất bại (`request_failed / request_received * 100`) vượt quá 2% liên tục trong 3 phút.
- Ảnh hưởng tới người dùng: Người dùng nhận mã lỗi 500 Internal Server Error, không nhận được câu trả lời từ chatbot.
- Ba bước kiểm tra đầu tiên:
  1. Kiểm tra panel Errors trên dashboard để biết `error_type` phổ biến (ví dụ `RuntimeError`, `HTTPException`).
  2. Tra cứu log trong `data/logs.jsonl` với `event == "request_failed"` để xem trường `payload.detail` và `correlation_id`.
  3. Mở Langfuse trace để xác định span bị lỗi (màu đỏ) và stack trace chi tiết.
- Mitigation tạm thời: Tắt incident nếu đang trong bài test giả lập (`python scripts/inject_incident.py --disable`), hoặc bật circuit-breaker trả thông báo thân thiện cho người dùng trong khi điều tra backend.
- Owner: oncall-engineer

## Alert 3

- Tên: low_retrieval_success_rate
- Severity: warning
- Duration: 5m
- Kênh thông báo: Slack (#alerts-day13-monitoring)
- SLI/SLO liên quan: Guardrail `retrieval_success_rate_pct_min: 90` (tỷ lệ retrieval thành công >= 90%)
- Điều kiện và thời gian duy trì: Tỷ lệ truy vấn tri thức thành công rơi xuống dưới 90% trong 5 phút.
- Ảnh hưởng tới người dùng: Câu trả lời của bot bị mất ngữ cảnh chính xác từ tài liệu, giảm chất lượng nội dung hoặc rơi vào fallback câu trả lời chung.
- Ba bước kiểm tra đầu tiên:
  1. Xem panel Errors trên dashboard, kiểm tra chỉ số `tool_success_rate_pct`.
  2. Lọc log có `tool_name == "retrieval"` và `tool_success == false`.
  3. Kiểm tra kết nối tới cơ sở dữ liệu vector/retrieval service và kiểm tra trace span `retrieval`.
- Mitigation tạm thời: Kích hoạt cache tài liệu cục bộ hoặc fallback corpus tĩnh để bot vẫn có tài liệu trả lời tạm thời.
- Owner: rag-team
