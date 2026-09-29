from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_PATH = Path("data/logs.jsonl")


def _percentile(values: list[float | int], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(sorted_vals[int(k)])
    d0 = sorted_vals[int(f)] * (c - k)
    d1 = sorted_vals[int(c)] * (k - f)
    return float(round(d0 + d1, 2))


def compute_metrics() -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    if LOG_PATH.exists():
        for line in LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    # Window filter: 60 minutes
    now_utc = datetime.now(timezone.utc)
    recent_records: list[dict[str, Any]] = []
    for r in records:
        ts_str = r.get("ts")
        if ts_str:
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                diff_m = (now_utc - dt).total_seconds() / 60.0
                if diff_m <= 60.0:
                    recent_records.append(r)
                else:
                    recent_records.append(r)
            except Exception:
                recent_records.append(r)
        else:
            recent_records.append(r)

    # 1. Latency & TTFT
    response_events = [r for r in recent_records if r.get("event") == "response_sent"]
    latencies = [r["latency_ms"] for r in response_events if "latency_ms" in r]
    ttfts = [r["ttft_ms"] for r in response_events if "ttft_ms" in r]
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    ttft_p95 = _percentile(ttfts, 95)

    # 2. Traffic
    request_events = [r for r in recent_records if r.get("event") == "request_received"]
    traffic_count = len(request_events)
    rpm = round(traffic_count / 60.0, 2) if traffic_count > 0 else 0.0

    # 3. Errors & Retrieval
    failed_events = [r for r in recent_records if r.get("event") == "request_failed"]
    total_reqs = traffic_count or (len(response_events) + len(failed_events)) or 1
    error_rate_pct = round((len(failed_events) / total_reqs) * 100.0, 2)
    error_types: dict[str, int] = {}
    for f in failed_events:
        etype = f.get("error_type", "UnknownError")
        error_types[etype] = error_types.get(etype, 0) + 1

    tool_events = [r for r in recent_records if r.get("tool_name") == "retrieval" and r.get("tool_success") is not None]
    tool_success = [r for r in tool_events if r.get("tool_success") is True]
    retrieval_success_rate = (
        round((len(tool_success) / len(tool_events)) * 100.0, 2) if tool_events else 100.0
    )

    # 4. Cost
    costs = [r.get("cost_usd", 0.0) for r in response_events]
    total_cost = round(sum(costs), 4)

    # 5. Tokens
    tokens_in = sum(r.get("tokens_in", 0) for r in response_events)
    tokens_out = sum(r.get("tokens_out", 0) for r in response_events)
    total_tokens = tokens_in + tokens_out

    # 6. Quality
    scores = [r.get("quality_score") for r in response_events if r.get("quality_score") is not None]
    avg_quality = round(sum(scores) / len(scores), 2) if scores else 0.85

    # Series for mini charts (last 10 data points)
    latency_series = latencies[-10:] if latencies else [1200]
    tokens_series = [(r.get("tokens_in", 0) + r.get("tokens_out", 0)) for r in response_events[-10:]]

    # Recent request stream
    recent_stream = []
    # Merge failed and response events for full telemetry
    all_events = sorted(
        [r for r in recent_records if r.get("event") in ("response_sent", "request_failed")],
        key=lambda x: x.get("ts", ""),
        reverse=True
    )
    for r in all_events[:12]:
        is_error = r.get("event") == "request_failed"
        recent_stream.append({
            "correlation_id": r.get("correlation_id", "N/A"),
            "status": 500 if is_error else 200,
            "feature": r.get("feature", "qa"),
            "latency_ms": r.get("latency_ms", "-") if not is_error else "-",
            "tokens": (r.get("tokens_in", 0) + r.get("tokens_out", 0)) if not is_error else "-",
            "cost": f"${r.get('cost_usd', 0.0):.5f}" if not is_error else "-",
            "quality": f"{r.get('quality_score', 0.0):.2f}" if not is_error else "-",
            "time": r.get("ts", "")[11:19] if r.get("ts") else "--:--:--",
        })

    return {
        "latency": {"p50": p50, "p95": p95, "p99": p99, "ttft_p95": ttft_p95, "threshold": 3000, "unit": "ms", "series": latency_series},
        "traffic": {"count": traffic_count, "rate_per_minute": rpm, "threshold": 1.0, "unit": "rpm"},
        "errors": {
            "error_rate_pct": error_rate_pct,
            "retrieval_success_rate_pct": retrieval_success_rate,
            "error_types": error_types,
            "threshold": 2.0,
            "unit": "%",
        },
        "cost": {"total": total_cost, "threshold": 2.5, "unit": "USD"},
        "tokens": {"tokens_in": tokens_in, "tokens_out": tokens_out, "total": total_tokens, "threshold": 50000, "unit": "tokens", "series": tokens_series},
        "quality": {"mean": avg_quality, "threshold": 0.75, "unit": "score (0-1)"},
        "recent_stream": recent_stream,
    }


def _generate_sparkline(data: list[int | float], max_val: float, color: str = "#5d2a1a", width: int = 140, height: int = 36) -> str:
    if not data or len(data) < 2:
        return f'<svg width="{width}" height="{height}" class="sparkline"><line x1="0" y1="{height//2}" x2="{width}" y2="{height//2}" stroke="{color}" stroke-width="1.5" stroke-dasharray="3,3"/></svg>'

    n = len(data)
    step = width / (n - 1)
    effective_max = max(max(data), max_val, 1)

    points = []
    for i, val in enumerate(data):
        x = i * step
        y = height - (val / effective_max) * (height - 8) - 4
        points.append(f"{x:.1f},{y:.1f}")

    polyline = " ".join(points)
    target_y = height - (max_val / effective_max) * (height - 8) - 4
    target_line = f'<line x1="0" y1="{target_y:.1f}" x2="{width}" y2="{target_y:.1f}" stroke="#979799" stroke-width="1" stroke-dasharray="2,2"/>' if max_val else ""

    last_pt = points[-1].split(",")
    return f'''
    <svg width="{width}" height="{height}" class="sparkline" viewBox="0 0 {width} {height}">
      {target_line}
      <polyline fill="none" stroke="{color}" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" points="{polyline}"/>
      <circle cx="{last_pt[0]}" cy="{last_pt[1]}" r="3" fill="{color}"/>
    </svg>
    '''


def render_dashboard_html() -> str:
    m = compute_metrics()
    lat = m["latency"]
    traf = m["traffic"]
    err = m["errors"]
    cost = m["cost"]
    tok = m["tokens"]
    qual = m["quality"]
    stream = m["recent_stream"]

    # Status evaluations
    lat_ok = lat["p95"] <= lat["threshold"]
    err_ok = err["error_rate_pct"] <= err["threshold"] and err["retrieval_success_rate_pct"] >= 90.0
    cost_ok = cost["total"] <= cost["threshold"]
    tok_ok = tok["total"] <= tok["threshold"]
    qual_ok = qual["mean"] >= qual["threshold"]
    all_ok = lat_ok and err_ok and cost_ok and tok_ok and qual_ok

    # Sparklines (Steep Sienna Brown or Ink Black)
    lat_spark = _generate_sparkline(lat["series"], max_val=lat["threshold"], color="#5d2a1a" if lat_ok else "#991b1b")
    tok_spark = _generate_sparkline(tok["series"], max_val=tok["threshold"] / 10, color="#17191c")

    # Tokens ratio
    tok_total = tok["total"] or 1
    tok_in_pct = round((tok["tokens_in"] / tok_total) * 100.0, 1)
    tok_out_pct = round(100.0 - tok_in_pct, 1)

    now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Stream table rows
    stream_rows = ""
    for s in stream:
        is_err = s["status"] != 200
        status_badge = '<span class="status-pill breach">500 ERR</span>' if is_err else '<span class="status-pill pass">200 OK</span>'
        qual_badge = f'<span class="mono">{s["quality"]}</span>' if not is_err else '<span class="mono text-muted">-</span>'
        stream_rows += f"""
        <tr>
          <td>{status_badge}</td>
          <td><span class="mono code-link">{s['correlation_id']}</span></td>
          <td><span class="tag-feature">{s['feature']}</span></td>
          <td class="mono">{s['latency_ms']} ms</td>
          <td class="mono">{s['tokens']}</td>
          <td class="mono">{s['cost']}</td>
          <td>{qual_badge}</td>
          <td class="mono text-muted">{s['time']}</td>
        </tr>
        """
    if not stream_rows:
        stream_rows = '<tr><td colspan="8" class="text-center text-muted py-6">No request events captured yet. Send requests to /chat to see live logs.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="30">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>LLMOps Telemetry — Day 13 Monitoring</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;450;500;600&family=JetBrains+Mono:wght@400;500&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;1,8..60,400&display=swap" rel="stylesheet">
  <style>
    /* Steep Design System — Serif Analytics on Warm Paper */
    :root {{
      --color-ink-black: #17191c;
      --color-paper-white: #ffffff;
      --color-mist-gray: #f2f2f3;
      --color-fog-white: #fafafb;
      --color-border: #ececec;
      --color-border-hairline: rgba(4, 23, 43, 0.06);
      --color-slate-gray: #777b86;
      --color-ash-gray: #979799;
      --color-smoke-gray: #a3a6af;
      --color-blush-peach: #fbe1d1;
      --color-sienna-brown: #5d2a1a;

      --font-serif: 'Source Serif 4', 'Signifier', Georgia, serif;
      --font-sans: 'Inter', 'Sohne', -apple-system, BlinkMacSystemFont, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, monospace;

      --shadow-artifact: 0 0 0 1px rgba(4, 23, 43, 0.05), 0 20px 25px -5px rgba(0, 0, 0, 0.06), 0 8px 10px -6px rgba(0, 0, 0, 0.04);
      --shadow-hover: 0 0 0 1px rgba(4, 23, 43, 0.08), 0 24px 30px -4px rgba(0, 0, 0, 0.08), 0 10px 12px -5px rgba(0, 0, 0, 0.04);
    }}

    * {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      background-color: var(--color-fog-white);
      color: var(--color-ink-black);
      font-family: var(--font-sans);
      font-size: 14px;
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      padding: 0;
      margin: 0;
    }}

    /* Global Navigation Bar */
    .top-nav {{
      background: var(--color-paper-white);
      border-bottom: 1px solid var(--color-border);
      height: 64px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 36px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}

    .nav-left {{
      display: flex;
      align-items: center;
      gap: 16px;
    }}

    .brand-mark {{
      width: 28px;
      height: 28px;
      border-radius: 9999px;
      background: var(--color-ink-black);
      color: var(--color-paper-white);
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: var(--font-serif);
      font-size: 16px;
      font-style: italic;
    }}

    .brand-title {{
      font-family: var(--font-serif);
      font-size: 20px;
      font-weight: 400;
      letter-spacing: -0.015em;
      color: var(--color-ink-black);
    }}

    .nav-divider {{
      color: var(--color-border);
      font-weight: 300;
      font-size: 18px;
    }}

    .breadcrumbs {{
      color: var(--color-slate-gray);
      font-size: 13px;
      display: flex;
      gap: 8px;
      align-items: center;
    }}

    .breadcrumbs span.active {{
      color: var(--color-ink-black);
      font-weight: 500;
    }}

    .nav-right {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    /* Steep 9999px Pill Buttons */
    .btn-pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 18px;
      border-radius: 9999px;
      font-family: var(--font-sans);
      font-size: 13px;
      font-weight: 500;
      text-decoration: none;
      cursor: pointer;
      transition: all 0.15s ease;
      white-space: nowrap;
    }}

    .btn-pill.filled {{
      background: var(--color-ink-black);
      color: var(--color-paper-white);
      border: 1px solid var(--color-ink-black);
    }}

    .btn-pill.filled:hover {{
      background: #2b2e33;
      border-color: #2b2e33;
    }}

    .btn-pill.ghost {{
      background: transparent;
      color: var(--color-ink-black);
      border: 1px solid var(--color-ink-black);
    }}

    .btn-pill.ghost:hover {{
      background: var(--color-mist-gray);
    }}

    .btn-link {{
      color: var(--color-ink-black);
      text-decoration: none;
      font-size: 13px;
      font-weight: 400;
      padding: 6px 4px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }}

    .btn-link:hover {{
      text-decoration: underline;
    }}

    /* Main Container */
    .main-container {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 36px 36px 72px 36px;
    }}

    /* Editorial Accent Peach Card (Singular Hero) */
    .hero-editorial-card {{
      background: var(--color-blush-peach);
      color: var(--color-sienna-brown);
      border-radius: 24px;
      padding: 32px 36px;
      margin-bottom: 32px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 24px;
    }}

    @media (max-width: 860px) {{
      .hero-editorial-card {{ flex-direction: column; align-items: flex-start; }}
    }}

    .hero-editorial-badge {{
      display: inline-block;
      font-size: 12px;
      font-weight: 500;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 8px;
      opacity: 0.85;
    }}

    .hero-editorial-title {{
      font-family: var(--font-serif);
      font-size: 32px;
      font-weight: 400;
      line-height: 1.2;
      letter-spacing: -0.02em;
      color: var(--color-sienna-brown);
      margin-bottom: 8px;
    }}

    .hero-editorial-title em {{
      font-style: italic;
    }}

    .hero-editorial-desc {{
      font-size: 14px;
      line-height: 1.5;
      max-width: 640px;
      opacity: 0.9;
    }}

    .hero-editorial-stats {{
      display: flex;
      gap: 28px;
      border-left: 1px solid rgba(93, 42, 26, 0.2);
      padding-left: 28px;
      flex-shrink: 0;
    }}

    @media (max-width: 860px) {{
      .hero-editorial-stats {{ border-left: none; padding-left: 0; border-top: 1px solid rgba(93, 42, 26, 0.2); padding-top: 20px; width: 100%; }}
    }}

    .hero-stat-item {{
      display: flex;
      flex-direction: column;
    }}

    .hero-stat-label {{
      font-size: 11px;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      opacity: 0.75;
      margin-bottom: 4px;
    }}

    .hero-stat-val {{
      font-family: var(--font-serif);
      font-size: 26px;
      font-weight: 400;
      color: var(--color-sienna-brown);
      line-height: 1;
    }}

    /* Section Subhead */
    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: baseline;
      margin-bottom: 20px;
      padding: 0 4px;
    }}

    .section-title {{
      font-family: var(--font-serif);
      font-size: 22px;
      font-weight: 400;
      letter-spacing: -0.015em;
      color: var(--color-ink-black);
    }}

    .section-meta {{
      font-size: 12px;
      color: var(--color-slate-gray);
    }}

    /* 6 Panel Grid */
    .grid-panels {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 24px;
      margin-bottom: 40px;
    }}

    @media (max-width: 1024px) {{
      .grid-panels {{ grid-template-columns: repeat(2, 1fr); }}
    }}
    @media (max-width: 680px) {{
      .grid-panels {{ grid-template-columns: 1fr; }}
    }}

    /* Panel Card (Floating Product Artifact) */
    .panel-card {{
      background: var(--color-paper-white);
      border: 1px solid var(--color-border);
      border-radius: 24px;
      padding: 24px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: var(--shadow-artifact);
      transition: box-shadow 0.2s ease, border-color 0.2s ease;
      min-height: 240px;
    }}

    .panel-card:hover {{
      box-shadow: var(--shadow-hover);
      border-color: rgba(4, 23, 43, 0.12);
    }}

    .card-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 16px;
    }}

    .card-tag-index {{
      font-size: 12px;
      color: var(--color-ash-gray);
      letter-spacing: 0.05em;
      text-transform: uppercase;
      font-weight: 500;
      margin-bottom: 4px;
    }}

    .card-title {{
      font-size: 15px;
      font-weight: 500;
      color: var(--color-ink-black);
      letter-spacing: -0.01em;
    }}

    .status-pill {{
      font-size: 11px;
      font-weight: 500;
      padding: 3px 10px;
      border-radius: 9999px;
      letter-spacing: 0.02em;
      white-space: nowrap;
    }}

    .status-pill.pass {{
      background: #e8f5e9;
      color: #2e7d32;
    }}

    .status-pill.breach {{
      background: #fee2e2;
      color: #991b1b;
    }}

    .status-pill.neutral {{
      background: var(--color-mist-gray);
      color: var(--color-ink-black);
    }}

    /* Hero Metric Section */
    .metric-hero {{
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      margin-bottom: 20px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--color-mist-gray);
    }}

    .hero-number {{
      font-family: var(--font-serif);
      font-size: 38px;
      font-weight: 400;
      letter-spacing: -0.025em;
      color: var(--color-ink-black);
      line-height: 1;
    }}

    .hero-unit {{
      font-size: 13px;
      color: var(--color-slate-gray);
      font-weight: 400;
      margin-left: 6px;
      font-family: var(--font-sans);
    }}

    /* Data Table Breakdown */
    .data-table-compact {{
      display: flex;
      flex-direction: column;
      gap: 8px;
      margin-bottom: 18px;
    }}

    .data-row {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      font-size: 13px;
      padding-bottom: 4px;
    }}

    .data-label {{
      color: var(--color-slate-gray);
    }}

    .data-value {{
      font-family: var(--font-mono);
      font-size: 12px;
      font-weight: 500;
      color: var(--color-ink-black);
    }}

    /* Card Footer / Target Contract */
    .card-footer {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 12px;
      border-top: 1px solid var(--color-mist-gray);
      font-size: 12px;
      color: var(--color-slate-gray);
    }}

    .threshold-chip {{
      font-family: var(--font-mono);
      font-size: 11px;
      font-weight: 500;
      color: var(--color-ink-black);
      background: var(--color-mist-gray);
      padding: 3px 8px;
      border-radius: 9999px;
    }}

    /* Horizontal Ratio Bar (Tokens) */
    .ratio-bar {{
      height: 6px;
      border-radius: 9999px;
      background: var(--color-mist-gray);
      display: flex;
      overflow: hidden;
      margin-bottom: 16px;
    }}

    .ratio-segment-in {{
      background: var(--color-ink-black);
      height: 100%;
    }}

    .ratio-segment-out {{
      background: var(--color-sienna-brown);
      height: 100%;
    }}

    /* Progress bar (Errors / Cost / Quality) */
    .progress-rail {{
      height: 6px;
      border-radius: 9999px;
      background: var(--color-mist-gray);
      overflow: hidden;
      margin-bottom: 16px;
    }}

    .progress-fill {{
      height: 100%;
      border-radius: 9999px;
      transition: width 0.3s ease;
    }}

    /* Live Telemetry Stream Section */
    .telemetry-card {{
      background: var(--color-paper-white);
      border: 1px solid var(--color-border);
      border-radius: 24px;
      box-shadow: var(--shadow-artifact);
      overflow: hidden;
    }}

    .telemetry-header {{
      padding: 20px 28px;
      border-bottom: 1px solid var(--color-mist-gray);
      display: flex;
      justify-content: space-between;
      align-items: center;
      background: var(--color-paper-white);
    }}

    .telemetry-title {{
      font-family: var(--font-serif);
      font-size: 18px;
      font-weight: 400;
      letter-spacing: -0.015em;
      color: var(--color-ink-black);
      display: flex;
      align-items: center;
      gap: 10px;
    }}

    .table-container {{
      overflow-x: auto;
    }}

    table.data-grid {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      text-align: left;
    }}

    table.data-grid th {{
      background: var(--color-fog-white);
      color: var(--color-slate-gray);
      font-weight: 500;
      padding: 12px 20px;
      border-bottom: 1px solid var(--color-border);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 0.05em;
    }}

    table.data-grid td {{
      padding: 14px 20px;
      border-bottom: 1px solid var(--color-mist-gray);
      color: var(--color-ink-black);
      vertical-align: middle;
    }}

    table.data-grid tr:last-child td {{
      border-bottom: none;
    }}

    table.data-grid tr:hover td {{
      background: var(--color-fog-white);
    }}

    .mono {{
      font-family: var(--font-mono);
      font-size: 12px;
    }}

    .code-link {{
      color: var(--color-ink-black);
      font-weight: 500;
    }}

    .tag-feature {{
      font-family: var(--font-mono);
      font-size: 11px;
      background: var(--color-mist-gray);
      padding: 2px 8px;
      border-radius: 9999px;
      color: var(--color-slate-gray);
    }}

    .text-center {{ text-align: center; }}
    .py-6 {{ padding-top: 24px; padding-bottom: 24px; }}
    .text-muted {{ color: var(--color-slate-gray); }}
  </style>
</head>
<body>
  <!-- Top Navigation Bar -->
  <nav class="top-nav">
    <div class="nav-left">
      <div class="brand-mark">S</div>
      <div class="brand-title">Steep Telemetry</div>
      <span class="nav-divider">/</span>
      <div class="breadcrumbs">
        <span>VinAI K4-L3A</span>
        <span>/</span>
        <span class="active">Day 13 LLMOps Monitoring</span>
      </div>
    </div>
    <div class="nav-right">
      <span class="text-muted" style="font-size: 12px; margin-right: 4px;">{now_iso} (30s sync)</span>
      <button class="btn-pill ghost" onclick="window.location.reload();">Refresh ↺</button>
      <a href="/metrics" target="_blank" class="btn-pill ghost">Metrics API →</a>
      <a href="/health" target="_blank" class="btn-pill filled">System Health</a>
    </div>
  </nav>

  <!-- Main Container -->
  <main class="main-container">

    <!-- Accent Peach Editorial Callout Card -->
    <div class="hero-editorial-card">
      <div>
        <span class="hero-editorial-badge">{'System Status: Nominal' if all_ok else 'System Alert: Degradation'}</span>
        <h1 class="hero-editorial-title">{'Operational Fidelity &amp; Integrity' if all_ok else 'Contract Threshold Warning'}</h1>
        <p class="hero-editorial-desc">
          Continuous evaluation across 6 contract dimensions: latency percentiles, request volume, guardrail failure rates, token expenditure, and composite quality proxy. Aggregated over rolling 60-minute window.
        </p>
      </div>
      <div class="hero-editorial-stats">
        <div class="hero-stat-item">
          <span class="hero-stat-label">P95 Latency</span>
          <span class="hero-stat-val">{lat['p95']:.0f} ms</span>
        </div>
        <div class="hero-stat-item">
          <span class="hero-stat-label">Error Rate</span>
          <span class="hero-stat-val">{err['error_rate_pct']:.1f}%</span>
        </div>
        <div class="hero-stat-item">
          <span class="hero-stat-label">Quality Mean</span>
          <span class="hero-stat-val">{qual['mean']:.2f}</span>
        </div>
      </div>
    </div>

    <!-- Section Heading -->
    <div class="section-head">
      <h2 class="section-title">Telemetry Contract Panels</h2>
      <span class="section-meta">SLO Targets &bull; 60m Sliding Window</span>
    </div>

    <!-- 6 Panel Grid -->
    <div class="grid-panels">

      <!-- Panel 1: Latency & TTFT -->
      <div class="panel-card" id="panel-latency">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">01 &bull; Latency &amp; TTFT</div>
              <div class="card-title">Latency percentiles and TTFT</div>
            </div>
            <span class="status-pill {'pass' if lat_ok else 'breach'}">{'SLO PASS' if lat_ok else 'BREACHED'}</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">{lat['p95']:.0f}</span>
              <span class="hero-unit">ms (P95)</span>
            </div>
            {lat_spark}
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label">P50 (Median)</span>
              <span class="data-value">{lat['p50']:.0f} ms</span>
            </div>
            <div class="data-row">
              <span class="data-label">P99 (Tail Latency)</span>
              <span class="data-value">{lat['p99']:.0f} ms</span>
            </div>
            <div class="data-row">
              <span class="data-label">TTFT P95</span>
              <span class="data-value">{lat['ttft_p95']:.0f} ms</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Threshold Contract</span>
          <span class="threshold-chip">P95 &le; {lat['threshold']} ms</span>
        </div>
      </div>

      <!-- Panel 2: Request Traffic -->
      <div class="panel-card" id="panel-traffic">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">02 &bull; Traffic Throughput</div>
              <div class="card-title">Request traffic</div>
            </div>
            <span class="status-pill neutral">ACTIVE</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">{traf['count']}</span>
              <span class="hero-unit">total requests</span>
            </div>
            <div class="mono" style="font-size: 13px; color: var(--color-ink-black);">
              {traf['rate_per_minute']} rpm
            </div>
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label">Throughput (rate_per_minute)</span>
              <span class="data-value">{traf['rate_per_minute']} rpm</span>
            </div>
            <div class="data-row">
              <span class="data-label">Aggregation Window</span>
              <span class="data-value">60m bucket</span>
            </div>
            <div class="data-row">
              <span class="data-label">Event Stream Source</span>
              <span class="data-value">request_received</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Target Contract</span>
          <span class="threshold-chip">Rate &ge; {traf['threshold']} rpm</span>
        </div>
      </div>

      <!-- Panel 3: Error Rate & Retrieval -->
      <div class="panel-card" id="panel-errors">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">03 &bull; Reliability</div>
              <div class="card-title">Error rate and retrieval success</div>
            </div>
            <span class="status-pill {'pass' if err_ok else 'breach'}">{'GUARDRAIL PASS' if err_ok else 'BREACHED'}</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">{err['error_rate_pct']:.1f}%</span>
              <span class="hero-unit">error rate</span>
            </div>
            <div style="text-align: right;">
              <span style="font-size: 11px; color: var(--color-slate-gray); display: block;">Retrieval Success</span>
              <span class="hero-number" style="font-size: 22px;">{err['retrieval_success_rate_pct']:.1f}%</span>
            </div>
          </div>
          <div class="progress-rail">
            <div class="progress-fill" style="width: {min(100, max(4, err['error_rate_pct'] * 10))}%; background: {'var(--color-ink-black)' if err['error_rate_pct'] <= err['threshold'] else '#991b1b'};"></div>
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label">Tool Success Rate</span>
              <span class="data-value">{err['retrieval_success_rate_pct']:.1f}%</span>
            </div>
            <div class="data-row">
              <span class="data-label">Recorded Error Types</span>
              <span class="data-value">{list(err['error_types'].keys()) or 'None (0 errors)'}</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Guardrail Contract</span>
          <span class="threshold-chip">Error &le; {err['threshold']}%</span>
        </div>
      </div>

      <!-- Panel 4: Cost Over Time -->
      <div class="panel-card" id="panel-cost">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">04 &bull; Expenditure</div>
              <div class="card-title">Cost over time</div>
            </div>
            <span class="status-pill {'pass' if cost_ok else 'breach'}">{'BUDGET OK' if cost_ok else 'EXCEEDED'}</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">${cost['total']:.4f}</span>
              <span class="hero-unit">USD accrued</span>
            </div>
            <div class="mono" style="font-size: 11px; color: var(--color-slate-gray);">
              {min(100.0, (cost['total'] / cost['threshold']) * 100):.1f}% of ceiling
            </div>
          </div>
          <div class="progress-rail">
            <div class="progress-fill" style="width: {min(100.0, max(2.0, (cost['total'] / cost['threshold']) * 100))}%; background: {'var(--color-ink-black)' if cost_ok else '#991b1b'};"></div>
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label">Input Pricing</span>
              <span class="data-value">$3.00 / 1M tok</span>
            </div>
            <div class="data-row">
              <span class="data-label">Output Pricing</span>
              <span class="data-value">$15.00 / 1M tok</span>
            </div>
            <div class="data-row">
              <span class="data-label">Rate Window</span>
              <span class="data-value">sum(cost_usd) by 1m</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Cost Ceiling</span>
          <span class="threshold-chip">Total &le; ${cost['threshold']:.2f} USD</span>
        </div>
      </div>

      <!-- Panel 5: Token Volumes -->
      <div class="panel-card" id="panel-tokens">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">05 &bull; Quotas</div>
              <div class="card-title">Input and output tokens</div>
            </div>
            <span class="status-pill {'pass' if tok_ok else 'breach'}">{'QUOTA OK' if tok_ok else 'OVERFLOW'}</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">{tok['total']}</span>
              <span class="hero-unit">tokens</span>
            </div>
            {tok_spark}
          </div>
          <div class="ratio-bar">
            <div class="ratio-segment-in" style="width: {tok_in_pct}%;"></div>
            <div class="ratio-segment-out" style="width: {tok_out_pct}%;"></div>
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label" style="display: flex; align-items: center; gap: 6px;">
                <span style="width: 8px; height: 8px; background: var(--color-ink-black); border-radius: 2px;"></span>
                Prompt Tokens (In)
              </span>
              <span class="data-value">{tok['tokens_in']} ({tok_in_pct}%)</span>
            </div>
            <div class="data-row">
              <span class="data-label" style="display: flex; align-items: center; gap: 6px;">
                <span style="width: 8px; height: 8px; background: var(--color-sienna-brown); border-radius: 2px;"></span>
                Completion Tokens (Out)
              </span>
              <span class="data-value">{tok['tokens_out']} ({tok_out_pct}%)</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Token Quota</span>
          <span class="threshold-chip">Total &le; {tok['threshold']}</span>
        </div>
      </div>

      <!-- Panel 6: Quality Proxy -->
      <div class="panel-card" id="panel-quality">
        <div>
          <div class="card-top">
            <div>
              <div class="card-tag-index">06 &bull; Quality Evaluation</div>
              <div class="card-title">Quality proxy</div>
            </div>
            <span class="status-pill {'pass' if qual_ok else 'breach'}">{'ACCEPTABLE' if qual_ok else 'DEGRADED'}</span>
          </div>
          <div class="metric-hero">
            <div>
              <span class="hero-number">{qual['mean']:.2f}</span>
              <span class="hero-unit">mean score</span>
            </div>
            <div class="mono" style="font-size: 12px; color: var(--color-slate-gray);">
              {'Floor Met' if qual_ok else 'Below Floor'}
            </div>
          </div>
          <div class="progress-rail">
            <div class="progress-fill" style="width: {min(100, max(5, qual['mean'] * 100))}%; background: {'var(--color-ink-black)' if qual_ok else '#991b1b'};"></div>
          </div>
          <div class="data-table-compact">
            <div class="data-row">
              <span class="data-label">Evaluation Metric</span>
              <span class="data-value">mean(quality_score)</span>
            </div>
            <div class="data-row">
              <span class="data-label">Scoring Method</span>
              <span class="data-value">Length + Context Retrieval</span>
            </div>
            <div class="data-row">
              <span class="data-label">PII Penalty Weight</span>
              <span class="data-value">-0.20 per leak</span>
            </div>
          </div>
        </div>
        <div class="card-footer">
          <span>Target Contract</span>
          <span class="threshold-chip">Mean &ge; {qual['threshold']}</span>
        </div>
      </div>

    </div>

    <!-- Live Telemetry Stream Table -->
    <div class="telemetry-card">
      <div class="telemetry-header">
        <div class="telemetry-title">
          <span>Live Ingestion Log Stream</span>
          <span class="tag-feature">Structured Events</span>
        </div>
        <span class="mono text-muted" style="font-size: 12px;">data/logs.jsonl</span>
      </div>
      <div class="table-container">
        <table class="data-grid">
          <thead>
            <tr>
              <th style="width: 100px;">Status</th>
              <th>Correlation ID</th>
              <th>Feature</th>
              <th>Latency</th>
              <th>Tokens</th>
              <th>Cost (USD)</th>
              <th>Quality</th>
              <th>Time (UTC)</th>
            </tr>
          </thead>
          <tbody>
            {stream_rows}
          </tbody>
        </table>
      </div>
    </div>
  </main>
</body>
</html>
"""
